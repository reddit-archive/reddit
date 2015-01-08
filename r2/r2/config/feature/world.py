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

from pylons import c, g, request


class World(object):
    """A World is the proxy to the app/request state for Features.

    Proxying through World allows for easy testing and caching if needed.
    """

    @staticmethod
    def get_safe(o, key, default=None):
        try:
            return getattr(o, key)
        except TypeError:
            return default

    def current_user(self):
        if c.user_is_loggedin:
            return self.get_safe(c, 'user')

    def current_subreddit(self):
        site = self.get_safe(c, 'site')
        if not site:
            # In non-request code (eg queued jobs), there isn't necessarily a
            # site name (or other request-type data).  In those cases, we don't
            # want to trigger any subreddit-specific code.
            return ''
        return site.name

    def current_subdomain(self):
        return self.get_safe(c, 'subdomain')

    def is_admin(self, user):
        if not user or not hasattr(user, 'name'):
            return False

        return user.name in self.get_safe(g, 'admins', [])

    def is_employee(self, user):
        if not user:
            return False
        return user.employee

    def has_gold(self, user):
        if not user:
            return False

        return user.gold

    def url_features(self):
        return set(request.GET.getall('feature'))

    def live_config(self, name):
        live = self.get_safe(g, 'live_config', {})
        return live.get(name)
