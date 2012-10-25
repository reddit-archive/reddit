#!/usr/bin/env python

import collections
import unittest

from r2.lib import utils


class UtilsTest(unittest.TestCase):
    def test_weighted_lottery_errors(self):
        self.assertRaises(ValueError, utils.weighted_lottery, {})
        self.assertRaises(ValueError, utils.weighted_lottery, {'x': 0})
        self.assertRaises(
            ValueError, utils.weighted_lottery,
            collections.OrderedDict([('x', -1), ('y', 1)]))

    def test_weighted_lottery(self):
        weights = collections.OrderedDict(
            [('x', 2), (None, 0), (None, 0), ('y', 3), ('z', 1)])

        def expect(result, random_value):
            scaled_r = float(random_value) / sum(weights.itervalues())
            self.assertEquals(
                result,
                utils.weighted_lottery(weights, _random=lambda: scaled_r))

        expect('x', 0)
        expect('x', 1)
        expect('y', 2)
        expect('y', 3)
        expect('y', 4)
        expect('z', 5)
        self.assertRaises(ValueError, expect, None, 6)

if __name__ == '__main__':
    unittest.main()
