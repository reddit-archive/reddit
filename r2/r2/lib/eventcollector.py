# The contents of this file are subject to the Common Public Attribution
# License Version 1.0. (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy of the License at
# http://code.reddit.com/LICENSE. The License is based on the Mozilla Public
# License Version 1.1, but Sections 14 and 15 have been added to cover use of
# software over a computer network and provide for limited attribution for the
# Original Developer. In addition, Exhibit A has been modified to be consistent
# with Exhibit B.
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License for
# the specific language governing rights and limitations under the License.
#
# The Original Code is reddit.
#
# The Original Developer is the Initial Developer.  The Initial Developer of
# the Original Code is reddit Inc.
#
# All portions of the code written by reddit are Copyright (c) 2006-2015 reddit
# Inc. All Rights Reserved.
###############################################################################
import datetime
import hashlib
import hmac
import itertools
import json
import pytz
import requests
import time

from pylons import g
from uuid import uuid4
from wsgiref.handlers import format_date_time

import r2.lib.amqp
from r2.lib import hooks
from r2.lib.utils import domain, epoch_timestamp, sampled, squelch_exceptions


MAX_EVENT_SIZE = 4096
MAX_CONTENT_LENGTH = 40 * 1024


def _make_http_date(when=None):
    if when is None:
        when = datetime.datetime.now(pytz.UTC)
    return format_date_time(time.mktime(when.timetuple()))


def _epoch_to_millis(timestamp):
    """Convert an epoch_timestamp from seconds (float) to milliseconds (int)"""
    return int(timestamp * 1000)


class EventQueue(object):
    def __init__(self, queue=r2.lib.amqp):
        self.queue = queue

    def save_event(self, event):
        if isinstance(event, EventV2):
            if event.testing:
                self.queue.add_item("event_collector_test", event.dump())
            else:
                self.queue.add_item("event_collector", event.dump())
        else:
            self.queue.add_item("event_collector", json.dumps(event))

    @squelch_exceptions
    @sampled("events_collector_vote_sample_rate")
    def vote_event(self, vote, old_vote=None,
            context_data=None, sensitive_context_data=None):
        """Create a 'vote' event for event-collector

        vote: An Storage object representing the new vote, as handled by
            vote.py / queries.py
        old_vote: A Storage object representing the previous vote on this
            thing, if there is one. NOTE: This object has a different
            set of attributes compared to the new "vote" object.
        context_data: A dict of fields from EventV2.get_context_data().
            Necessary because the vote event is sent from an async process
            separate from the actual vote request.
        sensitive_context_data: A dict of fields from
            EventV2.get_sensitive_context_data(). Will be sent to the event
            collector flagged as needing obfuscation. Necessary for the
            same reason as `context_data`.

        """
        # Mapping of stored vote "names" to more readable ones
        vote_dirs = {"1": "up", "0": "clear", "-1": "down"}

        event = EventV2(
            topic="vote_server",
            event_type="server_vote",
            time=vote._date,
            data=context_data,
            obfuscated_data=sensitive_context_data,
        )

        event.add("vote_direction", vote_dirs[vote._name])

        subreddit = vote._thing2.subreddit_slow
        event.add("sr_id", subreddit._id)
        event.add("sr_name", subreddit.name)

        target = vote._thing2
        target_type = target.__class__.__name__.lower()
        if target_type == "link" and target.is_self:
            target_type = "self"
        event.add("target_fullname", target._fullname)
        event.add("target_type", target_type)

        if old_vote:
            event.add("prev_vote_direction",  vote_dirs[old_vote.direction])
            event.add("prev_vote_ts", _epoch_to_millis(old_vote.date))

        if event.get("user_id") == target.author_id and not old_vote:
            event.add("auto_self_vote", True)

        hook = hooks.get_hook("event.get_private_vote_data")
        private_data = hook.call_until_return(vote=vote)
        if private_data:
            for name, value in private_data.iteritems():
                event.add(name, value)

        self.save_event(event)

    @squelch_exceptions
    @sampled("events_collector_submit_sample_rate")
    def submit_event(self, new_link, event_base=None, request=None,
                     context=None):
        """Create a 'submit' event for event-collector

        new_link: An r2.models.Link object
        event_base: The base fields for an Event. If not given, caller MUST
            supply a pylons.request and pylons.c object to build a base from
        request, context: Should be pylons.request & pylons.c respectively;
            used to build the base Event if event_base is not given

        """
        if event_base is None:
            event_base = Event.base_from_request(request, context)

        event_base["event_topic"] = "submit"
        event_base["event_name"] = "submit_server"

        submit_ts = epoch_timestamp(new_link._date)
        event_base["event_ts"] = _epoch_to_millis(submit_ts)
        event_base["id"] = new_link._fullname
        event_base["type"] = "self" if new_link.is_self else "link"

        sr = new_link.subreddit_slow
        event_base["sr"] = sr.name
        event_base["sr_id"] = str(sr._id)

        event_base["title"] = new_link.title

        if new_link._spam:
            event_base["flagged_spam"] = True
            banner = getattr(new_link, "ban_info", {}).get("banner")
            if banner:
                event_base["spam_reason"] = banner

        content = new_link.selftext if new_link.is_self else new_link.url
        content_length = len(content)

        event_base["length"] = content_length
        event_base["text"] = content

        size_so_far = len(json.dumps(event_base))
        oversize = size_so_far - MAX_EVENT_SIZE
        if oversize > 0:
            event_base["text"] = event_base["text"][:-oversize]

        self.save_event(event_base)

    @squelch_exceptions
    @sampled("events_collector_mod_sample_rate")
    def mod_event(self, modaction, subreddit, mod, target=None,
            request=None, context=None):
        """Create a 'mod' event for event-collector.

        modaction: An r2.models.ModAction object
        subreddit: The Subreddit the mod action is being performed in
        mod: The Account that is performing the mod action
        target: The Thing the mod action was applied to
        request, context: Should be pylons.request & pylons.c respectively

        """
        event = EventV2(
            topic="mod_events",
            event_type=modaction.action,
            time=modaction.date,
            uuid=modaction._id,
            request=request,
            context=context,
        )

        event.add("sr_id", subreddit._id)
        event.add("sr_name", subreddit.name)

        if modaction.details_text:
            event.add("details_text", modaction.details_text)

        if target:
            from r2.models import Account

            event.add("target_fullname", target._fullname)
            event.add("target_type", target.__class__.__name__.lower())
            event.add("target_id", target._id)
            if isinstance(target, Account):
                event.add("target_name", target.name)

        self.save_event(event)

    @squelch_exceptions
    @sampled("events_collector_quarantine_sample_rate")
    def quarantine_event(self, event_type, subreddit,
            request=None, context=None):
        """Create a 'quarantine' event for event-collector.

        event_type: quarantine_interstitial_view, quarantine_opt_in,
            quarantine_opt_out, quarantine_interstitial_dismiss
        subreddit: The quarantined subreddit
        request, context: Should be pylons.request & pylons.c respectively

        """
        event = EventV2(
            topic="quarantine",
            event_type=event_type,
            request=request,
            context=context,
        )

        if context:
            if context.user_is_loggedin:
                event.add("verified_email", context.user.email_verified)
            else:
                event.add("verified_email", False)

        event.add("sr_id", subreddit._id)
        event.add("sr_name", subreddit.name)

        # Due to the redirect, the request object being sent isn't the 
        # original, so referrer and action data is missing for certain events
        if request and (event_type == "quarantine_interstitial_view" or
                 event_type == "quarantine_opt_out"):
            request_vars = request.environ["pylons.routes_dict"]
            event.add("sr_action", request_vars.get("action", None))

            # The thing_id the user is trying to view is a comment
            if request.environ["pylons.routes_dict"].get("comment", None):
                thing_id36 = request_vars.get("comment", None)
            # The thing_id is a link
            else:
                thing_id36 = request_vars.get("article", None)

            if thing_id36:
                event.add("thing_id", int(thing_id36, 36))

            referrer_url = request.headers.get('Referer', None)
            if referrer_url:
                event.add("referrer_url", referrer_url)
                event.add("referrer_domain", domain(referrer_url))

        self.save_event(event)

    @squelch_exceptions
    def event_base(self, request, context):
        return Event.base_from_request(request, context)


class EventV2(object):
    def __init__(self, topic, event_type,
            time=None, uuid=None, request=None, context=None, testing=False,
            data=None, obfuscated_data=None):
        """Create a new event for event-collector.

        topic: Used to filter events into appropriate streams for processing
        event_type: Used for grouping and sub-categorizing events
        time: Should be a datetime.datetime object in UTC timezone
        uuid: Should be a UUID object
        request, context: Should be pylons.request & pylons.c respectively
        testing: Whether to send the event to the test endpoint
        data: A dict of field names/values to initialize the payload with
        obfuscated_data: Same as `data`, but fields that need obfuscation
        """
        self.topic = topic
        self.event_type = event_type
        self.testing = testing

        if not time:
            time = datetime.datetime.now(pytz.UTC)
        self.timestamp = _epoch_to_millis(epoch_timestamp(time))

        if not uuid:
            uuid = uuid4()
        self.uuid = str(uuid)

        self.payload = data or {}
        self.obfuscated_data = obfuscated_data or {}

        if context and request:
            self.payload.update(self.get_context_data(request, context))
            self.obfuscated_data.update(
                self.get_sensitive_context_data(request, context))

    def add(self, field, value, obfuscate=False):
        if obfuscate:
            self.obfuscated_data[field] = value
        else:
            self.payload[field] = value

    def get(self, field, obfuscated=False):
        if obfuscated:
            return self.obfuscated_data.get(field, None)
        else:
            return self.payload.get(field, None)

    @classmethod
    def get_context_data(self, request, context):
        data = {}

        if context.user_is_loggedin:
            data["user_id"] = context.user._id
            data["user_name"] = context.user.name
        else:
            loid = request.cookies.get("loid", None)
            if loid:
                data["loid"] = loid

        oauth2_client = getattr(context, "oauth2_client", None)
        if oauth2_client:
            data["oauth2_client_id"] = oauth2_client._id

        data["domain"] = request.host
        data["user_agent"] = request.user_agent

        return data

    @classmethod
    def get_sensitive_context_data(self, request, context):
        data = {}
        if getattr(request, "ip", None):
            data["client_ip"] = request.ip

        return data

    def dump(self):
        """Returns the JSON representation of the event."""
        data = {
            "event_topic": self.topic,
            "event_type": self.event_type,
            "event_ts": self.timestamp,
            "uuid": self.uuid,
            "payload": self.payload,
        }
        if self.obfuscated_data:
            data["payload"]["obfuscated_data"] = self.obfuscated_data

        return json.dumps(data)


class Event(dict):
    """Deprecated. All new events should use EventV2."""
    REQUIRED_FIELDS = (
        "event_name",
        "event_ts",
        "utc_offset",
        "user_agent",
        "client_ip",
        "domain",
        "uuid",
    )
    @classmethod
    def base_from_request(cls, request, context, **kw):
        if context.user_is_loggedin:
            user_id = str(context.user._id)
            loid = None
        else:
            user_id = None
            loid = request.cookies.get("loid", None)

        if getattr(context, "oauth2_client", None):
            oauth2_client_id = context.oauth2_client._id
        else:
            oauth2_client_id = None

        return cls.base(
            user_agent=request.user_agent,
            ip=request.ip,
            domain=request.host,
            user_id=user_id,
            loid=loid,
            oauth2_client_id=oauth2_client_id,
            **kw
        )

    @classmethod
    def base(cls, event_name=None, timestamp=None, user_agent=None, ip=None,
              domain=None, user_id=None, loid=None, oauth2_client_id=None,
              event_uuid=None, **kw):
        ret = cls(kw)

        if event_uuid is None:
            ret["uuid"] = str(uuid4())

        if event_name is not None:
            ret["event_name"] = event_name
        if timestamp is not None:
            ret["event_ts"] = timestamp
        if user_agent is not None:
            ret["user_agent"] = user_agent
        if ip is not None:
            ret["client_ip"] = ip
        if domain is not None:
            ret["domain"] = domain
        if user_id is not None:
            ret["user_id"] = user_id
        if loid is not None:
            ret["loid"] = loid
        if oauth2_client_id is not None:
            ret["oauth_client_id"] = oauth2_client_id

        return ret

    def missing_fields(self):
        return (f for f in self.REQUIRED_FIELDS if f not in self)


def _split_list(some_list):
    return some_list[:len(some_list)/2], some_list[len(some_list)/2:]


class EventPublisher(object):
    def __init__(self, url, signature_key, secret, user_agent, stats,
                 max_content_length=MAX_CONTENT_LENGTH, timeout=None):
        self.url = url
        self.signature_key = signature_key
        self.secret = secret
        self.user_agent = user_agent
        self.timeout = timeout
        self.stats = stats
        self.max_content_length = max_content_length

        self.session = requests.Session()

    def _make_signature(self, payload):
        mac = hmac.new(self.secret, payload, hashlib.sha256).hexdigest()
        return "key={key}, mac={mac}".format(key=self.signature_key, mac=mac)

    def _publish(self, events):
        # Note: If how the JSON payload is created is changed,
        # update the content-length estimations in `_chunk_events`
        events_json = "[" + ", ".join(events) + "]"
        headers = {
            "Date": _make_http_date(),
            "User-Agent": self.user_agent,
            "Content-Type": "application/json",
            "X-Signature": self._make_signature(events_json),
        }

        with self.stats.get_timer("providers.event_collector"):
            resp = self.session.post(self.url, data=events_json,
                                     headers=headers, timeout=self.timeout)
            return resp

    def _chunk_events(self, events):
        to_send = []
        # base content-length is 2 for the `[` and `]`
        send_size = 2
        for event in events:
            # increase estimated content-length by length of message,
            # plus the length of the `, ` used to join the events JSON
            send_size += len(event) + len(", ")

            # If adding this event would put us over the batch limit,
            # yield the current set of events first
            if send_size >= self.max_content_length:
                yield to_send
                to_send = []
                send_size = 2 + len(event) + len(", ")

            to_send.append(event)

        if to_send:
            yield to_send

    def publish(self, events):
        for some_events in self._chunk_events(events):
            resp = self._publish(some_events)
            # read from resp.content, so that the connection can be re-used
            # http://docs.python-requests.org/en/latest/user/advanced/#keep-alive
            ignored = resp.content
            yield resp, some_events


def _get_reason(response):
    return (getattr(response, "reason", None) or
            getattr(response.raw, "reason", "{unknown}"))


def process_events(g, timeout=5.0, max_event_size=MAX_EVENT_SIZE, **kw):
    publisher = EventPublisher(
        g.events_collector_url,
        g.secrets["events_collector_key"],
        g.secrets["events_collector_secret"],
        g.useragent,
        g.stats,
        timeout=timeout,
    )
    test_publisher = EventPublisher(
        g.events_collector_test_url,
        g.secrets["events_collector_key"],
        g.secrets["events_collector_secret"],
        g.useragent,
        g.stats,
        timeout=timeout,
    )

    @g.stats.amqp_processor("event_collector")
    def processor(msgs, chan):
        events = []
        test_events = []

        for msg in msgs:
            if len(msg.body) > max_event_size:
                g.log.warning("Event too large (%s); dropping", len(msg.body))
                g.log.warning("%r", msg.body)
                continue

            if msg.delivery_info["routing_key"] == "event_collector_test":
                test_events.append(msg.body)
            else:
                events.append(msg.body)

        to_publish = itertools.chain(
            publisher.publish(events),
            test_publisher.publish(test_events),
        )
        for response, sent in to_publish:
            if response.ok:
                g.log.info("Published %s events", len(sent))
            else:
                g.log.warning(
                    "Event send failed %s - %s",
                    response.status_code,
                    _get_reason(response),
                )
                g.log.warning("Response headers: %r", response.headers)
                response.raise_for_status()

    r2.lib.amqp.handle_items("event_collector", processor, **kw)
