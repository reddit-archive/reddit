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
import contextlib
from mock import patch, MagicMock

from routes.util import url_for
from pylons import app_globals as g

from r2.lib.validator import VThrottledLogin, VUname
from r2.models import Account, NotFound
from r2.tests import RedditControllerTestCase


class PostLoginRegTests(RedditControllerTestCase):

    def setUp(self):
        super(PostLoginRegTests, self).setUp()
        p = patch.object(json, "dumps", lambda x: x)
        p.start()
        self.addCleanup(p.stop)

        self.amqp = self.patch_eventcollector()

        self.simple_event = self.autopatch(g.stats, "simple_event")

        self.user_agent = "Hacky McBrowser/1.0"
        self.device_id = "deadbeef"

    def do_post(self, action, params, headers=None, expect_errors=False):
        headers = headers or {}
        return self.app.post(
            url_for(controller="post", action=action),
            extra_environ={"REMOTE_ADDR": "1.2.3.4"},
            headers=headers,
            params=params,
            expect_errors=expect_errors,
        )

    @contextlib.contextmanager
    def mock_login(self):
        account = MagicMock()
        account.name = "test"
        account.make_cookie.return_value = "cookievaluehere"
        with patch.object(VThrottledLogin, "run", return_value=account):
            yield account

    def find_headers(self, res, name):
        for k, v in res.headers:
            if k == name.lower():
                yield v

    def assert_headers(self, res, name, test):
        for value in self.find_headers(res, name):
            if callable(test) and test(value):
                return
            elif value == test:
                return
        raise AssertionError("No matching %s header found" % name)

    def test_login(self):
        dest = "/foo"
        body = "user=test&passwd=test123&dest=%s" % dest
        with self.mock_login():
            res = self.do_post("login", body)
            self.assertEqual(res.status, 302)
            self.assert_headers(
                res,
                "Location",
                lambda value: value.endswith(dest)
            )
            self.assert_headers(
                res,
                "Set-Cookie",
                lambda value: value.startswith("reddit_session=")
            )

    def test_login_fail(self):
        body = "user=test&passwd=test123"
        with patch.object(Account, "_by_name", side_effect=NotFound):
            res = self.do_post("login", body)
            # counterintuitively, failure to login will return a 200
            # (compared to a redirect).
            self.assertEqual(res.status, 200)

    def test_register(self):
        from r2.controllers import login
        dest = "/foo"
        body = "user=test&passwd=test123&passwd2=test123&dest=%s" % dest
        with contextlib.nested(
            patch.object(login, "register"),
            patch.object(VUname, "run", return_value="test"),
        ):
            res = self.do_post("reg", body)
            self.assertEqual(res.status, 302)
            self.assert_headers(
                res,
                "Location",
                lambda value: value.endswith(dest)
            )
            self.assert_headers(
                res,
                "Set-Cookie",
                lambda value: value.startswith("reddit_session=")
            )

    def test_register_username_taken(self):
        body = "user=test&passwd=test123&passwd2=test123"
        with patch.object(Account, "_by_name", return_value=MagicMock()):
            res = self.do_post("reg", body)
            self.assertEqual(res.status, 200)
