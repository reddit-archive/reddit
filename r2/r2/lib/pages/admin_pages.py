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
from pylons         import c, g
from r2.lib.wrapped import Wrapped
from pages   import Reddit
from r2.lib.menus   import NavButton, NavMenu, menu

class AdminSidebar(Wrapped):
    def __init__(self, user):
        self.user = user


class Details(Wrapped):
    def __init__(self, link):
        Wrapped.__init__(self)
        self.link = link


class AdminPage(Reddit):
    create_reddit_box  = False
    submit_box         = False
    extension_handling = False
    
    def __init__(self, nav_menus = None, *a, **kw):
        #add admin options to the nav_menus
        if c.user_is_admin:
            buttons  = [NavButton(menu.i18n, "")] \
                if g.translator else []
            admin_menu = NavMenu(buttons, title='show', base_path = '/admin',
                                 type="lightdrop")
            if nav_menus:
                nav_menus.insert(0, admin_menu)
            else:
                nav_menus = [admin_menu]

        Reddit.__init__(self, nav_menus = nav_menus, *a, **kw)

class AdminProfileMenu(NavMenu):
    def __init__(self, path):
        NavMenu.__init__(self, [], base_path = path,
                         title = 'admin', type="tabdrop")

try:
    from r2admin.lib.pages import *
except ImportError:
    pass
