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
# The Original Code is Reddit.
# 
# The Original Developer is the Initial Developer.  The Initial Developer of the
# Original Code is CondeNet, Inc.
# 
# All portions of the code written by CondeNet are Copyright (c) 2006-2009
# CondeNet, Inc. All Rights Reserved.
################################################################################
from validator import *
from pylons.i18n import _
from r2.models import *
from r2.lib.pages import *
from r2.lib.pages.things import wrap_links
from r2.lib.menus import *
from r2.controllers import ListingController

from r2.controllers.reddit_base import RedditController

from r2.lib.promote import get_promoted
from r2.lib.utils import timetext

from datetime import datetime

class PromoteController(RedditController):
    @validate(VSponsor())
    def GET_index(self):
        return self.GET_current_promos()

    @validate(VSponsor())
    def GET_current_promos(self):
        render_list = list(wrap_links(get_promoted()))
        for x in render_list:
            if x.promote_until:
                x.promote_expires = timetext(datetime.now(g.tz) - x.promote_until)
        page = PromotePage('current_promos',
                           content = PromotedLinks(render_list))
    
        return page.render()

    @validate(VSponsor())
    def GET_new_promo(self):
        page = PromotePage('new_promo',
                           content = PromoteLinkForm())
        return page.render()

    @validate(VSponsor(),
              link = VLink('link'))
    def GET_edit_promo(self, link):
        sr = Subreddit._byID(link.sr_id)
        listing = wrap_links(link)
        rendered = listing.render()

        timedeltatext = ''
        if link.promote_until:
            timedeltatext = timetext(link.promote_until - datetime.now(g.tz),
                                     resultion=2)

        form = PromoteLinkForm(sr = sr, link = link,
                               listing = rendered,
                               timedeltatext = timedeltatext)
        page = PromotePage('new_promo', content = form)

        return page.render()

