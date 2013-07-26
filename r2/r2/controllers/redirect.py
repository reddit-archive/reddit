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
# All portions of the code written by reddit are Copyright (c) 2006-2013 reddit
# Inc. All Rights Reserved.
###############################################################################
from pylons import request
from pylons.controllers.util import abort, redirect_to

from r2.lib.base import BaseController
from r2.lib.validator import chkuser, chksrname


class RedirectController(BaseController):
    def GET_redirect(self, dest):
        return redirect_to(str(dest))

    def GET_user_redirect(self, username, rest=None):
        user = chkuser(username)
        if not user:
            abort(400)
        url = "/user/" + user
        if rest:
            url += "/" + rest
        if request.query_string:
            url += "?" + request.query_string
        return redirect_to(str(url), _code=301)

    def GET_timereddit_redirect(self, timereddit, rest=None):
        tr_name = chksrname(timereddit)
        if not tr_name:
            abort(400)
        if rest:
            rest = str(rest)
        else:
            rest = ''
        return redirect_to("/r/t:%s/%s" % (tr_name, rest), _code=301)

    def GET_gilded_comments(self):
        return redirect_to("/r/all/comments/gilded", _code=301)
