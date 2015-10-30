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
import random
import string
import unittest

import mock

from r2.config.feature.state import FeatureState
from r2.config.feature.world import World
from r2.tests import RedditTestCase


class MockAccount(object):
    def __init__(self, name, _fullname):
        self.name = name
        self._fullname = _fullname
        _, _, _id = _fullname.partition("_")
        self._id = int(_id, 36)

gary = MockAccount(name='gary', _fullname='t2_beef')
all_uppercase = MockAccount(name='ALL_UPPERCASE', _fullname='t2_f00d')

class MockWorld(World):
    def _make_state(self, config):
        # Mock by hand because _parse_config is called in __init__, so we
        # can't instantiate then update.
        class MockState(FeatureState):
            def _parse_config(*args, **kwargs):
                return config
        return MockState('test_state', self)

class TestFeature(unittest.TestCase):
    _world = None
    # Append user-supplied error messages to the default output, rather than
    # overwriting it.
    longMessage = True

class TestFeatureBase(RedditTestCase):
    # Append user-supplied error messages to the default output, rather than
    # overwriting it.
    longMessage = True

    def setUp(self):
        self.world = MockWorld()
        self.world.current_user = mock.Mock(return_value='')
        self.world.current_subreddit = mock.Mock(return_value='')
        self.world.current_loid = mock.Mock(return_value='')

    @classmethod
    def generate_loid(cls):
        return ''.join(random.sample(string.letters + string.digits, 16))


class TestFeature(TestFeatureBase):

    def _assert_fuzzy_percent_true(self, results, percent):
        stats = collections.Counter(results)
        total = sum(stats.values())
        # _roughly_ `percent` should have been `True`
        diff = abs((float(stats[True]) / total) - (percent / 100.0))
        self.assertTrue(diff < 0.1)

    def test_calculate_bucket(self):
        """Test FeatureState's _calculate_bucket function."""
        feature_state = self._make_state(config={})

        # Give ourselves enough users that we can get some reasonable amount of
        # precision when checking amounts per bucket.
        NUM_USERS = FeatureState.NUM_BUCKETS * 2000
        fullnames = []
        for i in xrange(NUM_USERS):
            fullnames.append("t2_%s" % str(i))

        counter = collections.Counter()
        for fullname in fullnames:
            bucket = feature_state._calculate_bucket(fullname)
            counter[bucket] += 1
            # Ensure bucketing is deterministic.
            self.assertEqual(bucket, feature_state._calculate_bucket(fullname))

        for bucket in xrange(FeatureState.NUM_BUCKETS):
            # We want an even distribution across buckets.
            expected = NUM_USERS / FeatureState.NUM_BUCKETS
            actual = counter[bucket]
            # Calculating the percentage difference instead of looking at the
            # raw difference scales better as we change NUM_USERS.
            percent_equal = float(actual)/expected
            self.assertAlmostEqual(percent_equal, 1.0, delta=.10,
                                   msg='bucket: %s' % bucket)

    def test_choose_variant(self):
        """Test FeatureState's _choose_variant function."""
        no_variants = {}
        three_variants = {
            'remove_vote_counters': 5,
            'control_1': 10,
            'control_2': 5,
        }
        three_variants_more = {
            'remove_vote_counters': 15.6,
            'control_1': 10,
            'control_2': 20,
        }

        counters = collections.defaultdict(collections.Counter)
        for bucket in xrange(FeatureState.NUM_BUCKETS):
            variant = FeatureState._choose_variant(bucket, no_variants)
            if variant:
                counters['no_variants'][variant] += 1
            # Ensure variant-choosing is deterministic.
            self.assertEqual(
                    variant,
                    FeatureState._choose_variant(bucket, no_variants))

            variant = FeatureState._choose_variant(bucket, three_variants)
            if variant:
                counters['three_variants'][variant] += 1
            # Ensure variant-choosing is deterministic.
            self.assertEqual(
                    variant,
                    FeatureState._choose_variant(bucket, three_variants))

            previous_variant = variant
            variant = FeatureState._choose_variant(bucket, three_variants_more)
            if variant:
                counters['three_variants_more'][variant] += 1
            # Ensure variant-choosing is deterministic.
            self.assertEqual(
                    variant,
                    FeatureState._choose_variant(bucket, three_variants_more))
            # If previously we had a variant, we should still have the same one
            # now.
            if previous_variant:
                self.assertEqual(variant, previous_variant)

        # Only controls chosen in the no-variant case.
        for variant, percentage in FeatureState.DEFAULT_CONTROL_GROUPS.items():
            count = counters['no_variants'][variant]
            # The variant percentage is expressed as a part of 100, so we need
            # to calculate the fraction-of-1 percentage and scale it
            # accordingly.
            scaled_percentage = float(count) / (FeatureState.NUM_BUCKETS / 100)
            self.assertEqual(scaled_percentage, percentage)
        for variant, percentage in three_variants.items():
            count = counters['three_variants'][variant]
            scaled_percentage = float(count) / (FeatureState.NUM_BUCKETS / 100)
            self.assertEqual(scaled_percentage, percentage)
        for variant, percentage in three_variants_more.items():
            count = counters['three_variants_more'][variant]
            scaled_percentage = float(count) / (FeatureState.NUM_BUCKETS / 100)
            self.assertEqual(scaled_percentage, percentage)

        # Test boundary conditions around the maximum percentage allowed for
        # variants.
        fifty_fifty = {
            'control_1': 50,
            'control_2': 50,
        }
        almost_fifty_fifty = {
            'control_1': 49,
            'control_2': 51,
        }
        for bucket in xrange(FeatureState.NUM_BUCKETS):
            variant = FeatureState._choose_variant(bucket, fifty_fifty)
            counters['fifty_fifty'][variant] += 1
            variant = FeatureState._choose_variant(bucket, almost_fifty_fifty)
            counters['almost_fifty_fifty'][variant] += 1
        count = counters['fifty_fifty']['control_1']
        scaled_percentage = float(count) / (FeatureState.NUM_BUCKETS / 100)
        self.assertEqual(scaled_percentage, 50)

        count = counters['fifty_fifty']['control_2']
        scaled_percentage = float(count) / (FeatureState.NUM_BUCKETS / 100)
        self.assertEqual(scaled_percentage, 50)

        count = counters['almost_fifty_fifty']['control_1']
        scaled_percentage = float(count) / (FeatureState.NUM_BUCKETS / 100)
        self.assertEqual(scaled_percentage, 49)

        count = counters['almost_fifty_fifty']['control_2']
        scaled_percentage = float(count) / (FeatureState.NUM_BUCKETS / 100)
        self.assertEqual(scaled_percentage, 50)

    def test_enabled(self):
        cfg = {'enabled': 'on'}
        feature_state = self.world._make_state(cfg)
        self.assertTrue(feature_state.is_enabled())
        self.assertTrue(feature_state.is_enabled(user=gary))

    def test_disabled(self):
        cfg = {'enabled': 'off'}
        feature_state = self.world._make_state(cfg)
        self.assertFalse(feature_state.is_enabled())
        self.assertFalse(feature_state.is_enabled(user=gary))

    def test_admin_enabled(self):
        cfg = {'admin': True}
        self.world.is_admin = mock.Mock(return_value=True)
        feature_state = self.world._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(user=gary))

    def test_admin_disabled(self):
        cfg = {'admin': True}
        self.world.is_admin = mock.Mock(return_value=False)
        feature_state = self.world._make_state(cfg)
        self.assertFalse(feature_state.is_enabled(user=gary))

    def test_employee_enabled(self):
        cfg = {'employee': True}
        self.world.is_employee = mock.Mock(return_value=True)
        feature_state = self.world._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(user=gary))

    def test_employee_disabled(self):
        cfg = {'employee': True}
        self.world.is_employee = mock.Mock(return_value=False)
        feature_state = self.world._make_state(cfg)
        self.assertFalse(feature_state.is_enabled(user=gary))

    def test_beta_enabled(self):
        cfg = {'beta': True}
        self.world.user_has_beta_enabled = mock.Mock(return_value=True)
        feature_state = self.world._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(user=gary))

    def test_beta_disabled(self):
        cfg = {'beta': True}
        self.world.user_has_beta_enabled = mock.Mock(return_value=False)
        feature_state = self.world._make_state(cfg)
        self.assertFalse(feature_state.is_enabled(user=gary))

    def test_gold_enabled(self):
        cfg = {'gold': True}
        self.world.has_gold = mock.Mock(return_value=True)
        feature_state = self.world._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(user=gary))

    def test_gold_disabled(self):
        cfg = {'gold': True}
        self.world.has_gold = mock.Mock(return_value=False)
        feature_state = self.world._make_state(cfg)
        self.assertFalse(feature_state.is_enabled(user=gary))

    def test_loggedin_enabled(self):
        cfg = {'loggedin': True}
        self.world.is_user_loggedin = mock.Mock(return_value=True)
        feature_state = self.world._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(user=gary))

    def test_loggedin_disabled(self):
        cfg = {'loggedin': False}
        self.world.is_user_loggedin = mock.Mock(return_value=True)
        feature_state = self.world._make_state(cfg)
        self.assertFalse(feature_state.is_enabled(user=gary))

    def test_loggedout_enabled(self):
        cfg = {'loggedout': True}
        self.world.is_user_loggedin = mock.Mock(return_value=False)
        feature_state = self.world._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(user=gary))

    def test_loggedout_disabled(self):
        cfg = {'loggedout': False}
        self.world.is_user_loggedin = mock.Mock(return_value=False)
        feature_state = self.world._make_state(cfg)
        self.assertFalse(feature_state.is_enabled(user=gary))

    def test_percent_loggedin(self):
        num_users = 2000
        users = []
        for i in xrange(num_users):
            users.append(MockAccount(name=str(i), _fullname="t2_%s" % str(i)))

        def simulate_percent_loggedin(wanted_percent):
            cfg = {'percent_loggedin': wanted_percent}
            self.world.is_user_loggedin = mock.Mock(return_value=True)
            feature_state = self.world._make_state(cfg)
            return (feature_state.is_enabled(x) for x in users)

        self.assertFalse(any(simulate_percent_loggedin(0)))
        self.assertTrue(all(simulate_percent_loggedin(100)))
        self._assert_fuzzy_percent_true(simulate_percent_loggedin(25), 25)
        self._assert_fuzzy_percent_true(simulate_percent_loggedin(10), 10)
        self._assert_fuzzy_percent_true(simulate_percent_loggedin(50), 50)
        self._assert_fuzzy_percent_true(simulate_percent_loggedin(99), 99)

    def test_percent_loggedout(self):
        num_users = 2000

        def simulate_percent_loggedout(wanted_percent):
            cfg = {'percent_loggedout': wanted_percent}
            for i in xrange(num_users):
                loid = self.generate_loid()
                self.world.current_loid = mock.Mock(return_value=loid)
                self.world.is_user_loggedin = mock.Mock(return_value=False)
                feature_state = self.world._make_state(cfg)
                yield feature_state.is_enabled()

        self.assertFalse(any(simulate_percent_loggedout(0)))
        self.assertTrue(all(simulate_percent_loggedout(100)))
        self._assert_fuzzy_percent_true(simulate_percent_loggedout(25), 25)
        self._assert_fuzzy_percent_true(simulate_percent_loggedout(10), 10)
        self._assert_fuzzy_percent_true(simulate_percent_loggedout(50), 50)
        self._assert_fuzzy_percent_true(simulate_percent_loggedout(99), 99)

    @mock.patch('r2.config.feature.state.g')
    def test_experiment(self, g):
        num_users = 2000
        users = []
        for i in xrange(num_users):
            users.append(MockAccount(name=str(i), _fullname="t2_%s" % str(i)))

        def test_simulation(experiment):
            cfg = {'experiment': experiment}

            mock_world = self.world()
            mock_world.is_user_loggedin = mock.Mock(return_value=False)
            feature_state = self._make_state(cfg, mock_world)
            self.assertFalse(feature_state.is_enabled(None))

            mock_world = self.world()
            mock_world.is_user_loggedin = mock.Mock(return_value=True)
            feature_state = self._make_state(cfg, mock_world)
            counter = collections.Counter()
            for user in users:
                if feature_state.is_enabled(user):
                    counter[feature_state.variant(user)] += 1

            for variant, percent in experiment['variants'].items():
                # Our actual percentage should be within our expected percent
                # (expressed as a part of 100 rather than a fraction of 1)
                # +- 1%.
                measured_percent = (float(counter[variant]) / num_users) * 100
                self.assertAlmostEqual(measured_percent, percent, delta=1)

        experiment = {'variants': {'larger': 5, 'smaller': 10}}
        test_simulation(experiment)
        experiment['enabled'] = True
        test_simulation(experiment)

        experiment['enabled'] = False
        cfg = {'experiment': experiment}
        mock_world = self.world()
        mock_world.is_user_loggedin = mock.Mock(return_value=True)
        feature_state = self._make_state(cfg, mock_world)
        for user in users:
            self.assertFalse(feature_state.is_enabled(user))

    def test_url_enabled(self):

        cfg = {'url': 'test_state'}
        self.world.url_features = mock.Mock(return_value={'test_state'})
        feature_state = self.world._make_state(cfg)
        self.assertTrue(feature_state.is_enabled())
        self.assertTrue(feature_state.is_enabled(user=gary))

        cfg = {'url': 'test_state'}
        self.world.url_features = mock.Mock(return_value={'x', 'test_state'})
        feature_state = self.world._make_state(cfg)
        self.assertTrue(feature_state.is_enabled())
        self.assertTrue(feature_state.is_enabled(user=gary))

        cfg = {'url': {'test_state_a': 'a', 'test_state_b': 'b'}}
        mock_world.url_features = mock.Mock(return_value={'x', 'test_state_b'})
        feature_state = self._make_state(cfg, mock_world)
        self.assertTrue(feature_state.is_enabled())
        self.assertEqual(feature_state.variant(user=gary), 'b')

    def test_url_disabled(self):

        cfg = {'url': 'test_state'}
        self.world.url_features = mock.Mock(return_value={})
        feature_state = self.world._make_state(cfg)
        self.assertFalse(feature_state.is_enabled())
        self.assertFalse(feature_state.is_enabled(user=gary))

        cfg = {'url': 'test_state'}
        self.world.url_features = mock.Mock(return_value={'x'})
        feature_state = self.world._make_state(cfg)
        self.assertFalse(feature_state.is_enabled())
        self.assertFalse(feature_state.is_enabled(user=gary))

        cfg = {'url': {'test_state_a': 'a', 'test_state_b': 'b'}}
        mock_world.url_features = mock.Mock(return_value={'x'})
        feature_state = self._make_state(cfg, mock_world)
        self.assertFalse(feature_state.is_enabled())

        cfg = {'url': {'test_state_c1': 'control_1', 'test_state_c2': 'control_2'}}
        mock_world.url_features = mock.Mock(return_value={'x', 'test_state_c2'})
        feature_state = self._make_state(cfg, mock_world)
        self.assertFalse(feature_state.is_enabled())

    def test_user_in(self):
        cfg = {'users': ['Gary']}
        feature_state = self.world._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(user=gary))

        cfg = {'users': ['ALL_UPPERCASE']}
        feature_state = self.world._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(user=all_uppercase))

        cfg = {'users': ['dave', 'gary']}
        feature_state = self.world._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(user=gary))

    def test_user_not_in(self):
        cfg = {'users': ['']}
        featurestate = self.world._make_state(cfg)
        self.assertFalse(featurestate.is_enabled(user=gary))

        cfg = {'users': ['dave', 'joe']}
        featurestate = self.world._make_state(cfg)
        self.assertFalse(featurestate.is_enabled(user=gary))

    def test_subreddit_in(self):
        cfg = {'subreddits': ['WTF']}
        feature_state = self.world._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(subreddit='wtf'))

        cfg = {'subreddits': ['wtf']}
        feature_state = self.world._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(subreddit='WTF'))

        cfg = {'subreddits': ['aww', 'wtf']}
        feature_state = self.world._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(subreddit='wtf'))

    def test_subreddit_not_in(self):
        cfg = {'subreddits': []}
        feature_state = self.world._make_state(cfg)
        self.assertFalse(feature_state.is_enabled(subreddit='wtf'))

        cfg = {'subreddits': ['aww', 'wtfoobar']}
        feature_state = self.world._make_state(cfg)
        self.assertFalse(feature_state.is_enabled(subreddit='wtf'))

    def test_subdomain_in(self):
        cfg = {'subdomains': ['BETA']}
        feature_state = self.world._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(subdomain='beta'))

        cfg = {'subdomains': ['beta']}
        feature_state = self.world._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(subdomain='BETA'))

        cfg = {'subdomains': ['www', 'beta']}
        feature_state = self.world._make_state(cfg)
        self.assertTrue(feature_state.is_enabled(subdomain='beta'))

    def test_subdomain_not_in(self):
        cfg = {'subdomains': []}
        feature_state = self.world._make_state(cfg)
        self.assertFalse(feature_state.is_enabled(subdomain='beta'))
        self.assertFalse(feature_state.is_enabled(subdomain=''))

        cfg = {'subdomains': ['www', 'betanauts']}
        feature_state = self.world._make_state(cfg)
        self.assertFalse(feature_state.is_enabled(subdomain='beta'))

    def test_multiple(self):
        # is_admin, globally off should still be False
        cfg = {'enabled': 'off', 'admin': True}
        self.world.is_admin = mock.Mock(return_value=True)
        featurestate = self.world._make_state(cfg)
        self.assertFalse(featurestate.is_enabled(user=gary))

        # globally on but not admin should still be True
        cfg = {'enabled': 'on', 'admin': True}
        self.world.is_admin = mock.Mock(return_value=False)
        featurestate = self.world._make_state(cfg)
        self.assertTrue(featurestate.is_enabled(user=gary))
        self.assertTrue(featurestate.is_enabled())

        # no URL but admin should still be True
        cfg = {'url': 'test_featurestate', 'admin': True}
        self.world.url_features = mock.Mock(return_value={})
        self.world.is_admin = mock.Mock(return_value=True)
        featurestate = self.world._make_state(cfg)
        self.assertTrue(featurestate.is_enabled(user=gary))
