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
from mock import patch, MagicMock
import json

from routes.util import url_for
from pylons import app_globals as g

from r2.lib.validator import VThrottledLogin, VUname
from r2.models import Account, NotFound
from r2.tests import RedditControllerTestCase


class LoginRegTests(RedditControllerTestCase):

    def setUp(self):
        super(LoginRegTests, self).setUp()
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
            url_for(controller="api", action=action),
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

    def test_login(self):
        body = "user=test&passwd=test123"
        with self.mock_login():
            res = self.do_post("login", body)
            self.assertEqual(res.status, 200)
            self.assertTrue("error" not in res)

    def test_login_fail(self):
        body = "user=test&passwd=test123"
        with patch.object(Account, "_by_name", side_effect=NotFound):
            res = self.do_post("login", body)
            self.assertEqual(res.status, 200)
            self.assertTrue("WRONG_PASSWORD" in res)

    def test_register(self):
        from r2.controllers import login
        body = "user=test&passwd=test123&passwd2=test123"
        with contextlib.nested(
            patch.object(login, "register"),
            patch.object(VUname, "run", return_value="test"),
        ):
            res = self.do_post("register", body)
            self.assertEqual(res.status, 200)
            self.assertTrue("error" not in res)

    def test_register_username_taken(self):
        body = "user=test&passwd=test123&passwd2=test123"
        with patch.object(Account, "_by_name", return_value=MagicMock()):
            res = self.do_post("register", body)
            self.assertEqual(res.status, 200)
            self.assertTrue("error" in res)
            self.assertTrue("USERNAME_TAKEN" in res)
