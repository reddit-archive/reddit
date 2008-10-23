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
# All portions of the code written by CondeNet are Copyright (c) 2006-2008
# CondeNet, Inc. All Rights Reserved.
################################################################################
from r2.controllers.reddit_base import RedditController
from r2.controllers.reddit_base import base_listing

from r2.controllers.validator import *
from r2.lib.pages import *
from r2.models import *

from r2.lib import organic

from pylons.i18n import _

def admin_profile_query(vuser, location, db_sort):
    return None 

class AdminController(RedditController):
    @validate(VAdmin(),
              thing = VByName('fullname'))
    @validate(VAdmin())
    def GET_promote(self):
        current_list = organic.get_promoted()

        b = IDBuilder([ x._fullname for x in current_list])

        render_list = b.get_items()[0]

        return AdminPage(content = Promote(render_list),
                         title = _('promote'),
                         nav_menus = []).render()


try:
    from r2admin.controllers.admin import *
except ImportError:
    pass
