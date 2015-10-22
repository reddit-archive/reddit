#!/usr/bin/env python
# coding=utf-8
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

import json
from r2.tests import RedditTestCase
from pylons import app_globals as g
from mock import MagicMock, patch


class TestEventCollector(RedditTestCase):

    def setUp(self):
        p = patch.object(json, "dumps", lambda x: x)
        p.start()
        self.addCleanup(p.stop)

        p = patch("r2.lib.eventcollector.domain")
        self.domain_mock = p.start()
        self.addCleanup(p.stop)

    def _patch_liveconfig(self, k, v):
        def cleanup(orig=g.live_config[k]):
            g.live_config[k] = orig
        g.live_config[k] = v
        self.addCleanup(cleanup)

    def assert_event_item(self, queue, expected_data):
        # there should have been a call to add item!
        self.assertEqual(queue.add_item.call_count, 1)

        # pull the args
        calla, _ = queue.add_item.call_args_list[0]
        queue_name, data = calla

        # queued properly?
        self.assertEqual(queue_name, "event_collector")

        # and do they have a timestamp, uuid, and payload?
        self.assertNotEqual(data.pop("event_ts", None), None)
        self.assertNotEqual(data.pop("uuid", None), None)
        # there is some variability, but this should at least be present
        self.assertIn("event_topic", data)

        # these prints are for debgging when the subsequent assert fails
        print "GOT: ", data
        print "WANT:", expected_data
        self.assert_same_dict(data, expected_data)

    def test_vote_event(self):
        self._patch_liveconfig("events_collector_vote_sample_rate", 1.0)
        with patch.object(g.events, "queue") as queue:
            upvote = MagicMock(_name="1")
            oldvote = MagicMock(direction="-1")
            g.events.vote_event(upvote)

            self.assert_event_item(
                queue, dict(
                    event_topic="vote_server",
                    event_type="server_vote",
                    payload={
                        'vote_direction': 'up',
                        'target_type': 'magicmock',
                        'sr_id': upvote._thing2.subreddit_slow._id,
                        'sr_name': upvote._thing2.subreddit_slow.name,
                        'target_fullname': upvote._thing2._fullname,
                        'prev_vote_ts': 1,
                        'prev_vote_direction': 'down',
                    }
                )
            )

    def test_submit_event(self):
        self._patch_liveconfig("events_collector_submit_sample_rate", 1.0)
        with patch.object(g.events, "queue") as queue:
            new_link = MagicMock()
            context = MagicMock()
            request = MagicMock()
            g.events.submit_event(new_link, context=context, request=request)

            self.assert_event_item(
                queue, {
                    'event_topic': 'submit',
                    'event_name': 'submit_server',
                    'length': 0,
                    # values from the request
                    'client_ip': request.ip,
                    'user_agent': request.user_agent,
                    # values from the context
                    'user_id': str(context.user._id),
                    'oauth_client_id': context.oauth2_client._id,
                    # values from the new_link
                    'flagged_spam': True,   # bool(new_link._spam) == True
                    'type': 'self',
                    'sr': new_link.subreddit_slow.name,
                    'title': new_link.title,
                    'domain': request.host,
                    'text': new_link.selftext,
                    'sr_id': str(new_link.subreddit_slow._id),
                    'spam_reason': new_link.ban_info.get(),
                    'id': new_link._fullname,
                }
            )

    def test_mod_event(self):
        self._patch_liveconfig("events_collector_mod_sample_rate", 1.0)
        with patch.object(g.events, "queue") as queue:
            mod = None  # TODO: this value appears to not be used?
            modaction = MagicMock()
            subreddit = MagicMock()
            context = MagicMock()
            request = MagicMock()
            g.events.mod_event(
                modaction, subreddit, mod, context=context, request=request
            )

            self.assert_event_item(
                queue, {
                    'event_type': modaction.action,
                    'event_topic': 'mod_events',
                    'payload': {
                        'sr_id': subreddit._id,
                        'sr_name': subreddit.name,
                        'domain': request.host,
                        'user_agent': request.user_agent,
                        'referrer_url': request.headers.get(),
                        'user_id': context.user._id,
                        'user_name': context.user.name,
                        'oauth2_client_id': context.oauth2_client._id,
                        'referrer_domain': self.domain_mock(),
                        'details_text': modaction.details_text,
                        'geoip_country': context.location,
                        'obfuscated_data': {
                            'client_ip': request.ip,
                        }
                    }
                }
            )

    def test_quarantine_event(self):
        self._patch_liveconfig("events_collector_quarantine_sample_rate", 1.0)
        with patch.object(g.events, "queue") as queue:
            event_type = MagicMock()
            subreddit = MagicMock()
            context = MagicMock()
            request = MagicMock()
            g.events.quarantine_event(
                event_type, subreddit, context=context, request=request
            )

            self.assert_event_item(
                queue, {
                    'event_type': event_type,
                    'event_topic': 'quarantine',
                    "payload": {
                        'domain': request.host,
                        'referrer_domain': self.domain_mock(),
                        'verified_email': context.user.email_verified,
                        'user_id': context.user._id,
                        'sr_name': subreddit.name,
                        'referrer_url': request.headers.get(),
                        'user_agent': request.user_agent,
                        'sr_id': subreddit._id,
                        'user_name': context.user.name,
                        'oauth2_client_id': context.oauth2_client._id,
                        'geoip_country': context.location,
                        'obfuscated_data': {
                            'client_ip': request.ip
                        },
                    }
                }
            )
