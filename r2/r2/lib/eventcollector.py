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
import json
import time
import uuid

import pytz
import requests
from wsgiref.handlers import format_date_time

import r2.lib.amqp
from r2.lib.utils import epoch_timestamp, sampled, squelch_exceptions


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
        self.queue.add_item("event_collector", json.dumps(event))

    # Mapping of stored vote "names" to more readable ones
    VOTES = {"1": "up", "0": "clear", "-1": "down"}

    @squelch_exceptions
    @sampled("events_collector_sample_rate")
    def vote_event(self, vote, old_vote=None, event_base=None, request=None,
                   context=None):
        """Create a 'vote' event for event-collector

        vote: An Storage object representing the new vote, as handled by
            vote.py / queries.py
        old_vote: A Storage object representing the previous vote on this
            thing, if there is one. NOTE: This object has a different
            set of attributes compared to the new "vote" object.
        event_base: The base fields for an Event. If not given, caller MUST
            supply a pylons.request and pylons.c object to build a base from
        request, context: Should be pylons.request & pylons.c respectively;
            used to build the base Event if event_base is not given

        """
        if event_base is None:
            event_base = Event.base_from_request(request, context)

        event_base["event_topic"] = "vote"
        event_base["event_name"] = "vote_server"
        event_base["event_ts"] = _epoch_to_millis(epoch_timestamp(vote._date))
        event_base["vote_target"] = vote._thing2._fullname
        event_base["vote_direction"] = self.VOTES[vote._name]
        if old_vote:
            event_base["prev_vote_direction"] = self.VOTES[old_vote.direction]
            event_base["prev_vote_ts"] = _epoch_to_millis(old_vote.date)
        event_base["vote_type"] = vote._thing2.__class__.__name__.lower()
        if event_base["vote_type"] == "link" and vote._thing2.is_self:
            event_base["vote_type"] = "self"
        event_base["sr"] = vote._thing2.subreddit_slow.name
        event_base["sr_id"] = str(vote._thing2.subreddit_slow._id)

        self.save_event(event_base)

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
    def event_base(self, request, context):
        return Event.base_from_request(request, context)


class Event(dict):
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
            ret["uuid"] = str(uuid.uuid4())

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

    @g.stats.amqp_processor("event_collector")
    def processor(msgs, chan):
        events = []
        for msg in msgs:
            if len(msg.body) <= max_event_size:
                events.append(msg.body)
            else:
                g.log.warning("Event too large (%s); dropping", len(msg.body))
                g.log.warning("%r", msg.body)
        for response, sent in publisher.publish(events):
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
