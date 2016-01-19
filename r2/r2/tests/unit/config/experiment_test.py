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

import mock

from r2.config.feature.state import FeatureState
from . feature_test import TestFeatureBase, MockAccount


class TestFeature(TestFeatureBase):
    _world = None
    # Append user-supplied error messages to the default output, rather than
    # overwriting it.
    longMessage = True

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
            percent_equal = float(actual) / expected
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

    def do_experiment_simulation(self, users, experiment):
        num_users = len(users)
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
            variant = feature_state.variant(user)
            if feature_state.is_enabled(user):
                self.assertIsNotNone(
                    variant, "an enabled experiment should have a variant!")
                counter[variant] += 1

        for variant, percent in experiment['variants'].items():
            # Our actual percentage should be within our expected percent
            # (expressed as a part of 100 rather than a fraction of 1)
            # +- 1%.
            measured_percent = (float(counter[variant]) / num_users) * 100
            self.assertAlmostEqual(measured_percent, percent, delta=1)

    @mock.patch('r2.config.feature.state.g')
    def test_experiment(self, g, num_users = 2000):
        users = []
        for i in xrange(num_users):
            users.append(MockAccount(name=str(i), _fullname="t2_%s" % str(i)))

        experiment = {'variants': {'larger': 5, 'smaller': 10}}
        self.do_experiment_simulation(users, experiment)

        experiment['enabled'] = True
        self.do_experiment_simulation(users, experiment)

        experiment['enabled'] = False
        cfg = {'experiment': experiment}
        mock_world = self.world()
        mock_world.is_user_loggedin = mock.Mock(return_value=True)
        feature_state = self._make_state(cfg, mock_world)
        for user in users:
            self.assertFalse(feature_state.is_enabled(user))
