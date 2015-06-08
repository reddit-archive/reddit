#!/usr/bin/env python
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

import collections
import unittest

import mock

from r2.config.feature.state import FeatureState
from r2.config.feature.world import World


class MockAccount(object):
    def __init__(self, name, _fullname):
        self.name = name
        self._fullname = _fullname
gary = MockAccount(name='gary', _fullname='t2_beef')
all_uppercase = MockAccount(name='ALL_UPPERCASE', _fullname='t2_f00d')


class TestFeature(unittest.TestCase):
    _world = None

    @classmethod
    def world(cls):
        if not cls._world:
            cls._world = World()
            cls._world.current_user = mock.Mock(return_value='')
            cls._world.current_subreddit = mock.Mock(return_value='')

        return cls._world

    def _make_state(self, config, world=None):
        # Mock by hand because _parse_config is called in __init__, so we
        # can't instantiate then update.
        class MockState(FeatureState):
            def _parse_config(*args, **kwargs):
                return config
        if not world:
            world = self.world()
        return MockState('test_state', world)

    def test_enabled(self):
        cfg = {'enabled': 'on'}
        feature_state = self._make_state(cfg)
        self.assertTrue(feature_state.is_enabled())
        self.assertTrue(feature_state.is_enabled(user=gary))

    def test_disabled(self):
        cfg = {'enabled': 'off'}
        feature_state = self._make_state(cfg)
        self.assertFalse(feature_state.is_enabled())
        self.assertFalse(feature_state.is_enabled(user=gary))

    def test_admin_enabled(self):
        cfg = {'admin': True}
        mock_world = self.world()
        mock_world.is_admin = mock.Mock(return_value=True)
        feature_state = self._make_state(cfg, mock_world)
        self.assertTrue(feature_state.is_enabled(user=gary))

    def test_admin_disabled(self):
        cfg = {'admin': True}
        mock_world = self.world()
        mock_world.is_admin = mock.Mock(return_value=False)
        feature_state = self._make_state(cfg, mock_world)
        self.assertFalse(feature_state.is_enabled(user=gary))

    def test_employee_enabled(self):
        cfg = {'employee': True}
        mock_world = self.world()
        mock_world.is_employee = mock.Mock(return_value=True)
        feature_state = self._make_state(cfg, mock_world)
        self.assertTrue(feature_state.is_enabled(user=gary))

    def test_employee_disabled(self):
        cfg = {'employee': True}
        mock_world = self.world()
        mock_world.is_employee = mock.Mock(return_value=False)
        feature_state = self._make_state(cfg, mock_world)
        self.assertFalse(feature_state.is_enabled(user=gary))

    def test_beta_enabled(self):
        cfg = {'beta': True}
        mock_world = self.world()
        mock_world.user_has_beta_enabled = mock.Mock(return_value=True)
        feature_state = self._make_state(cfg, mock_world)
        self.assertTrue(feature_state.is_enabled(user=gary))

    def test_beta_disabled(self):
        cfg = {'beta': True}
        mock_world = self.world()
        mock_world.user_has_beta_enabled = mock.Mock(return_value=False)
        feature_state = self._make_state(cfg, mock_world)
        self.assertFalse(feature_state.is_enabled(user=gary))

    def test_gold_enabled(self):
        cfg = {'gold': True}
        mock_world = self.world()
        mock_world.has_gold = mock.Mock(return_value=True)
        feature_state = self._make_state(cfg, mock_world)
        self.assertTrue(feature_state.is_enabled(user=gary))

    def test_gold_disabled(self):
        cfg = {'gold': True}
        mock_world = self.world()
        mock_world.has_gold = mock.Mock(return_value=False)
        feature_state = self._make_state(cfg, mock_world)
        self.assertFalse(feature_state.is_enabled(user=gary))

    def test_loggedin_enabled(self):
        cfg = {'loggedin': True}
        mock_world = self.world()
        mock_world.is_user_loggedin = mock.Mock(return_value=True)
        feature_state = self._make_state(cfg, mock_world)
        self.assertTrue(feature_state.is_enabled(user=gary))

    def test_loggedin_disabled(self):
        cfg = {'loggedin': False}
        mock_world = self.world()
        mock_world.is_user_loggedin = mock.Mock(return_value=True)
        feature_state = self._make_state(cfg, mock_world)
        self.assertFalse(feature_state.is_enabled(user=gary))

    def test_loggedout_enabled(self):
        cfg = {'loggedout': True}
        mock_world = self.world()
        mock_world.is_user_loggedin = mock.Mock(return_value=False)
        feature_state = self._make_state(cfg, mock_world)
        self.assertTrue(feature_state.is_enabled(user=gary))

    def test_loggedout_disabled(self):
        cfg = {'loggedout': False}
        mock_world = self.world()
        mock_world.is_user_loggedin = mock.Mock(return_value=False)
        feature_state = self._make_state(cfg, mock_world)
        self.assertFalse(feature_state.is_enabled(user=gary))

    def test_percent_loggedin(self):
        num_users = 2000
        users = []
        for i in xrange(num_users):
            users.append(MockAccount(name=str(i), _fullname="t2_%s" % str(i)))

        def simulate_percent_loggedin(wanted_percent):
            cfg = {'percent_loggedin': wanted_percent}
            mock_world = self.world()
            mock_world.is_user_loggedin = mock.Mock(return_value=True)
            feature_state = self._make_state(cfg, mock_world)
            return (feature_state.is_enabled(x) for x in users)

        def assert_fuzzy_percent_true(results, percent):
            stats = collections.Counter(results)
            # _roughly_ `percent` should have been `True`
            diff = abs((float(stats[True]) / num_users) - (percent / 100.0))
            self.assertTrue(diff < 0.1)

        self.assertFalse(any(simulate_percent_loggedin(0)))
        self.assertTrue(all(simulate_percent_loggedin(100)))
        assert_fuzzy_percent_true(simulate_percent_loggedin(25), 25)
        assert_fuzzy_percent_true(simulate_percent_loggedin(10), 10)
        assert_fuzzy_percent_true(simulate_percent_loggedin(50), 50)
        assert_fuzzy_percent_true(simulate_percent_loggedin(99), 99)

    def test_url_enabled(self):
        mock_world = self.world()

        cfg = {'url': 'test_state'}
        mock_world.url_features = mock.Mock(return_value={'test_state'})
        feature_state = self._make_state(cfg, mock_world)
        self.assertTrue(feature_state.is_enabled())
        self.assertTrue(feature_state.is_enabled(user=gary))

        cfg = {'url': 'test_state'}
        mock_world.url_features = mock.Mock(return_value={'x', 'test_state'})
        feature_state = self._make_state(cfg, mock_world)
        self.assertTrue(feature_state.is_enabled())
        self.assertTrue(feature_state.is_enabled(user=gary))

    def test_url_disabled(self):
        mock_world = self.world()

        cfg = {'url': 'test_state'}
        mock_world.url_features = mock.Mock(return_value={})
        feature_state = self._make_state(cfg, mock_world)
        self.assertFalse(feature_state.is_enabled())
        self.assertFalse(feature_state.is_enabled(user=gary))

        cfg = {'url': 'test_state'}
        mock_world.url_features = mock.Mock(return_value={'x'})
        feature_state = self._make_state(cfg, mock_world)
        self.assertFalse(feature_state.is_enabled())
        self.assertFalse(feature_state.is_enabled(user=gary))

    def test_user_in(self):
        cfg = {'users': ['Gary']}
        feature_state = self._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(user=gary))

        cfg = {'users': ['ALL_UPPERCASE']}
        feature_state = self._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(user=all_uppercase))

        cfg = {'users': ['dave', 'gary']}
        feature_state = self._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(user=gary))

    def test_user_not_in(self):
        cfg = {'users': ['']}
        featurestate = self._make_state(cfg)
        self.assertFalse(featurestate.is_enabled(user=gary))

        cfg = {'users': ['dave', 'joe']}
        featurestate = self._make_state(cfg)
        self.assertFalse(featurestate.is_enabled(user=gary))

    def test_subreddit_in(self):
        cfg = {'subreddits': ['WTF']}
        feature_state = self._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(subreddit='wtf'))

        cfg = {'subreddits': ['wtf']}
        feature_state = self._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(subreddit='WTF'))

        cfg = {'subreddits': ['aww', 'wtf']}
        feature_state = self._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(subreddit='wtf'))

    def test_subreddit_not_in(self):
        cfg = {'subreddits': []}
        feature_state = self._make_state(cfg)
        self.assertFalse(feature_state.is_enabled(subreddit='wtf'))

        cfg = {'subreddits': ['aww', 'wtfoobar']}
        feature_state = self._make_state(cfg)
        self.assertFalse(feature_state.is_enabled(subreddit='wtf'))

    def test_subdomain_in(self):
        cfg = {'subdomains': ['BETA']}
        feature_state = self._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(subdomain='beta'))

        cfg = {'subdomains': ['beta']}
        feature_state = self._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(subdomain='BETA'))

        cfg = {'subdomains': ['www', 'beta']}
        feature_state = self._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(subdomain='beta'))

    def test_subdomain_not_in(self):
        cfg = {'subdomains': []}
        feature_state = self._make_state(cfg)
        self.assertFalse(feature_state.is_enabled(subdomain='beta'))
        self.assertFalse(feature_state.is_enabled(subdomain=''))

        cfg = {'subdomains': ['www', 'betanauts']}
        feature_state = self._make_state(cfg)
        self.assertFalse(feature_state.is_enabled(subdomain='beta'))

    def test_multiple(self):
        # is_admin, globally off should still be False
        cfg = {'enabled': 'off', 'admin': True}
        mock_world = self.world()
        mock_world.is_admin = mock.Mock(return_value=True)
        featurestate = self._make_state(cfg, mock_world)
        self.assertFalse(featurestate.is_enabled(user=gary))

        # globally on but not admin should still be True
        cfg = {'enabled': 'on', 'admin': True}
        mock_world = self.world()
        mock_world.is_admin = mock.Mock(return_value=False)
        featurestate = self._make_state(cfg, mock_world)
        self.assertTrue(featurestate.is_enabled(user=gary))
        self.assertTrue(featurestate.is_enabled())

        # no URL but admin should still be True
        cfg = {'url': 'test_featurestate', 'admin': True}
        mock_world = self.world()
        mock_world.url_features = mock.Mock(return_value={})
        mock_world.is_admin = mock.Mock(return_value=True)
        featurestate = self._make_state(cfg, mock_world)
        self.assertTrue(featurestate.is_enabled(user=gary))
