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

import pytz
import requests
from wsgiref.handlers import format_date_time

import r2.lib.amqp
from r2.lib.utils import epoch_timestamp, sampled, squelch_exceptions


def _make_http_date(when=None):
    if when is None:
        when = datetime.datetime.now(pytz.UTC)
    return format_date_time(time.mktime(when.timetuple()))


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
        event_base["event_ts"] = epoch_timestamp(vote._date)
        event_base["vote_target"] = vote._thing2._fullname
        event_base["vote_direction"] = self.VOTES[vote._name]
        if old_vote:
            event_base["prev_vote_direction"] = self.VOTES[old_vote.direction]
            event_base["prev_vote_ts"] = old_vote.date
        event_base["vote_type"] = vote._thing2.__class__.__name__.lower()
        if event_base["vote_type"] == "link" and vote._thing2.is_self:
            event_base["vote_type"] = "self"
        event_base["sr"] = vote._thing2.subreddit_slow.name
        event_base["sr_id"] = vote._thing2.subreddit_slow._id

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
        "ip",
        "domain",
    )
    @classmethod
    def base_from_request(cls, request, context, **kw):
        if context.user_is_loggedin:
            user_id = context.user._id
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
              **kw):
        ret = cls(kw)

        ret["event_name"] = event_name
        ret["timestamp"] = timestamp
        ret["user_agent"] = user_agent
        ret["ip"] = ip
        ret["domain"] = domain

        if user_id:
            ret["user_id"] = user_id
        if loid:
            ret["loid"] = loid

        if oauth2_client_id:
            ret["oauth_client_id"] = oauth2_client_id

        return ret

    def missing_fields(self):
        return (f for f in self.REQUIRED_FIELDS if f not in self)


class EventPublisher(object):
    def __init__(self, url, signature_key, secret, user_agent, stats,
                 timeout=None):
        self.url = url
        self.signature_key = signature_key
        self.secret = secret
        self.user_agent = user_agent
        self.timeout = timeout
        self.stats = stats

        self.session = requests.Session()

    def _make_signature(self, payload):
        mac = hmac.new(self.secret, payload, hashlib.sha256).hexdigest()
        return "key={key}, mac={mac}".format(key=self.signature_key, mac=mac)

    def publish(self, events):
        events_json = json.dumps(events)
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


def process_events(g, timeout=5.0, **kw):
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
        events = [json.loads(msg.body) for msg in msgs]
        response = publisher.publish(events)
        if response.ok:
            g.log.info("%s - Published %s events",
                       response.status_code, len(events))
        else:
            g.log.warning(
                "Event send failed %s - %s",
                response.status_code,
                response.raw.reason,
            )
            g.log.warning("%r", response.content)
            g.log.warning("%r", response.request.headers)
            g.log.warning("%r", response.request.data)
            response.raise_for_status()

    r2.lib.amqp.handle_items("event_collector", processor, **kw)
