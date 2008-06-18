# "The contents of this file are subject to the Common Public Attribution
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
# The Original Code is Reddit.
# 
# The Original Developer is the Initial Developer.  The Initial Developer of the
# Original Code is CondeNet, Inc.
# 
# All portions of the code written by CondeNet are Copyright (c) 2006-2008
# CondeNet, Inc. All Rights Reserved.
################################################################################
from reddit_base import RedditController, proxyurl
from pylons import request
from r2.lib.pages import Embed, BoringPage
from pylons.i18n import _
from urllib2 import HTTPError
from pylons import c


def force_redirect(dest):
    def _force_redirect(self, *a, **kw):
        return self.redirect(dest)
    return _force_redirect

class EmbedController(RedditController):

    def rendercontent(self, content):
        if content.startswith("<!--TEMPLATE-->"):
            return BoringPage(_("help"),
                              content = Embed(content=content),
                              show_sidebar = None,
                              space_compress = False).render()
        else:
            return content

    def renderurl(self):
        try:
            content = proxyurl("http://reddit.infogami.com"+request.fullpath)
            return self.rendercontent(content)
        except HTTPError, e:
            if e.code == 404:
                return self.abort404()
            else:
                print "error %s" % e.code
                print e.fp.read()

    GET_help = POST_help = renderurl

    GET_blog = force_redirect("http://blog.reddit.com/")
