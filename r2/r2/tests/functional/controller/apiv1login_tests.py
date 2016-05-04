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
import contextlib
import json
from mock import patch, MagicMock

from routes.util import url_for
from pylons import app_globals as g

from r2.lib import signing
from r2.lib.validator import VThrottledLogin, VUname
from r2.tests import RedditControllerTestCase, MockEventQueue


class APIV1LoginTests(RedditControllerTestCase):

    def setUp(self):
        super(APIV1LoginTests, self).setUp()

        self.autopatch(g.events, "queue_production", MockEventQueue())
        self.autopatch(g.events, "queue_test", MockEventQueue())

        self.simple_event = self.autopatch(g.stats, "simple_event")

        self.user_agent = "Hacky McBrowser/1.0"
        self.device_id = "deadbeef"

    def do_post(self, action, params, headers=None, expect_errors=False):
        headers = headers or {}
        headers.setdefault('User-Agent', self.user_agent)
        headers.setdefault('Client-Vendor-ID', self.device_id)
        return self.app.post(
            url_for(controller="apiv1login", action=action),
            extra_environ={"REMOTE_ADDR": "1.2.3.4"},
            headers=headers,
            params=params,
            expect_errors=expect_errors,
        )

    def make_ua_signature(self, platform="test", version=1):
        payload = "User-Agent:{}|Client-Vendor-ID:{}".format(
            self.user_agent, self.device_id,
        )
        return self.sign(payload, platform, version)

    def sign(self, payload, platform="test", version=1):
        return signing.sign_v1_message(payload, platform, version)

    @contextlib.contextmanager
    def mock_login(self):
        account = MagicMock()
        account.name = "test"
        account.make_cookie.return_value = "cookievaluehere"
        with patch.object(VThrottledLogin, "run", return_value=account):
            yield account

    def assert_login(self, body):
        body = json.loads(body)
        self.assertTrue("json" in body)
        errors = body['json'].get("errors")
        self.assertEqual(len(errors), 0)
        data = body['json'].get("data")
        self.assertTrue(bool(data))
        self.assertTrue("modhash" in data)
        self.assertTrue("cookie" in data)

    def test_nosigning_login(self):
        res = self.do_post(
            "login",
            "user=test&passwd=test123",
            expect_errors=True,
        )
        self.assertEqual(res.status, 403)
        self.simple_event.assert_any_call("signing.ua.invalid.invalid_format")

    def test_no_body_signing_login(self):
        res = self.do_post(
            "login",
            "user=test&passwd=test123",
            headers={
                signing.SIGNATURE_UA_HEADER: self.make_ua_signature(),
            },
            expect_errors=True,
        )
        self.assertEqual(res.status, 403)
        self.simple_event.assert_any_call(
            "signing.body.invalid.invalid_format"
        )

    def test_proper_signing_login(self):
        body = "user=test&passwd=test123"
        with self.mock_login():
            res = self.do_post(
                "login",
                body,
                headers={
                    signing.SIGNATURE_UA_HEADER: self.make_ua_signature(),
                    signing.SIGNATURE_BODY_HEADER: self.sign("Body:" + body),
                },
                expect_errors=True,
            )
            self.assertEqual(res.status, 200)
            self.assert_login(res.body)

    def test_nosigning_register(self):
        res = self.do_post(
            "register",
            "user=test&passwd=test123&passwd2=test123",
            expect_errors=True,
        )
        self.assertEqual(res.status, 403)
        self.simple_event.assert_any_call("signing.ua.invalid.invalid_format")

    def test_no_body_signing_register(self):
        res = self.do_post(
            "login",
            "user=test&passwd=test123&passwd2=test123",
            headers={
                signing.SIGNATURE_UA_HEADER: self.make_ua_signature(),
            },
            expect_errors=True,
        )
        self.assertEqual(res.status, 403)
        self.simple_event.assert_any_call(
            "signing.body.invalid.invalid_format"
        )

    def test_proper_signing_register(self):
        from r2.controllers import login
        body = "user=test&passwd=test123&passwd2=test123"
        with contextlib.nested(
            patch.object(login, "register"),
            patch.object(VUname, "run", return_value="test"),
        ):
            res = self.do_post(
                "register",
                body,
                headers={
                    signing.SIGNATURE_UA_HEADER: self.make_ua_signature(),
                    signing.SIGNATURE_BODY_HEADER: self.sign("Body:" + body),
                },
                expect_errors=True,
            )
            self.assertEqual(res.status, 200)
            self.assert_login(res.body)
