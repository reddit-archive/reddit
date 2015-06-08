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
import hashlib

from pylons import g


class FeatureState(object):
    """A FeatureState is the state of a feature and its condition in the world.

    It determines if this feature is enabled given the world provided.
    """

    # Special values for globally enabled properties - no need to interrogate
    # the world for these values.
    GLOBALLY_ON = "on"
    GLOBALLY_OFF = "off"

    # constant config blocks
    DISABLED_CFG = {"enabled": GLOBALLY_OFF}
    ENABLED_CFG = {"enabled": GLOBALLY_ON}

    def __init__(self, name, world):
        self.name = name
        self.world = world
        self.config = self._parse_config(name)

    def _parse_config(self, name):
        """Find and parse a config from our live config with this given name.

        :param name string - a given feature name
        :return dict - a dictionary with at least "enabled". May include more
                       depending on the enabled type.
        """
        config_name = "feature_%s" % name

        config_str = self.world.live_config(config_name)

        if not config_str or config_str == FeatureState.GLOBALLY_OFF:
            return self.DISABLED_CFG

        if config_str == FeatureState.GLOBALLY_ON:
            return self.ENABLED_CFG

        try:
            config = json.loads(config_str)
        except (ValueError, TypeError) as e:
            g.log.warning("Could not load config for name %r - %r",
                          config_name, e)
            return self.DISABLED_CFG

        if not isinstance(config, dict):
            g.log.warning("Config not dict, on or off: %r", config_name)
            return self.DISABLED_CFG

        return config

    def is_enabled(self, user=None, subreddit=None, subdomain=None,
                   oauth_client=None):
        cfg = self.config
        world = self.world

        if cfg.get('enabled') == self.GLOBALLY_ON:
            return True

        if cfg.get('enabled') == self.GLOBALLY_OFF:
            return False

        url_flag = cfg.get('url')
        if url_flag and url_flag in world.url_features():
            return True

        if cfg.get('admin') and world.is_admin(user):
            return True

        if cfg.get('employee') and world.is_employee(user):
            return True

        if cfg.get('beta') and world.user_has_beta_enabled(user):
            return True

        if cfg.get('gold') and world.has_gold(user):
            return True

        loggedin = world.is_user_loggedin()
        if cfg.get('loggedin') and loggedin:
            return True

        if cfg.get('loggedout') and not loggedin:
            return True

        users = [u.lower() for u in cfg.get('users', [])]
        if users and user and user.name.lower() in users:
            return True

        subreddits = [s.lower() for s in cfg.get('subreddits', [])]
        if subreddits and subreddit and subreddit.lower() in subreddits:
            return True

        subdomains = [s.lower() for s in cfg.get('subdomains', [])]
        if subdomains and subdomain and subdomain.lower() in subdomains:
            return True

        clients = set(cfg.get('oauth_clients', []))
        if clients and oauth_client and oauth_client in clients:
            return True

        percent_loggedin = cfg.get('percent_loggedin', 0)
        if percent_loggedin and user:
            # Mix the feature name in with the user id so the same users
            # don't get selected for ramp-ups for every feature
            hashed = hashlib.sha1(self.name + user._fullname)
            int_digest = long(hashed.hexdigest(), 16)

            if int_digest % 100 < percent_loggedin:
                return True

        # Unknown value, default to off.
        return False
