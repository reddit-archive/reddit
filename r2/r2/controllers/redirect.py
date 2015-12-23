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

from pylons import request
from pylons import tmpl_context as c
from pylons.controllers.util import abort

from r2.lib.base import BaseController
from r2.lib.utils import UrlParser
from r2.lib.validator import chkuser, validate, VLink
from r2.models import Subreddit


class RedirectController(BaseController):
    def pre(self, *k, **kw):
        BaseController.pre(self, *k, **kw)
        c.extension = request.environ.get('extension')

    def GET_redirect(self, dest):
        return self.redirect(str(dest))

    def GET_user_redirect(self, username, rest=None):
        user = chkuser(username)
        if not user:
            abort(400)
        url = "/user/" + user
        if rest:
            url += "/" + rest
        if request.query_string:
            url += "?" + request.query_string
        return self.redirect(str(url), code=301)

    def GET_timereddit_redirect(self, timereddit, rest=None):
        sr_name = "t:" + timereddit
        if not Subreddit.is_valid_name(sr_name, allow_time_srs=True):
            abort(400)
        if rest:
            rest = str(rest)
        else:
            rest = ''
        return self.redirect("/r/%s/%s" % (sr_name, rest), code=301)

    @validate(link=VLink('link_id'))
    def GET_link_id_redirect(self, link):
        if not link:
            abort(404)
        elif not link.subreddit_slow.can_view(c.user):
            # don't disclose the subreddit/title of a post via the redirect url
            abort(403)
        else:
            redirect_url = link.make_permalink_slow(force_domain=True)
        
        query_params = dict(request.GET)
        if query_params:
            url = UrlParser(redirect_url)
            url.update_query(**query_params)
            redirect_url = url.unparse()

        return self.redirect(redirect_url, code=301)
