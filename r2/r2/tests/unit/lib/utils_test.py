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
# All portions of the code written by reddit are Copyright (c) 2006-2013 reddit
# Inc. All Rights Reserved.
###############################################################################

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


class TestCanonicalizeEmail(unittest.TestCase):
    def test_empty_string(self):
        canonical = utils.canonicalize_email("")
        self.assertEquals(canonical, "")

    def test_unicode(self):
        canonical = utils.canonicalize_email(u"\u2713@example.com")
        self.assertEquals(canonical, "\xe2\x9c\x93@example.com")

    def test_localonly(self):
        canonical = utils.canonicalize_email("invalid")
        self.assertEquals(canonical, "")

    def test_multiple_ats(self):
        canonical = utils.canonicalize_email("invalid@invalid@invalid")
        self.assertEquals(canonical, "")

    def test_remove_dots(self):
        canonical = utils.canonicalize_email("d.o.t.s@example.com")
        self.assertEquals(canonical, "dots@example.com")

    def test_remove_plus_address(self):
        canonical = utils.canonicalize_email("fork+nork@example.com")
        self.assertEquals(canonical, "fork@example.com")

    def test_unicode_in_byte_str(self):
        # this shouldn't ever happen, but some entries in postgres appear
        # to be byte strings with non-ascii in 'em.
        canonical = utils.canonicalize_email("\xe2\x9c\x93@example.com")
        self.assertEquals(canonical, "\xe2\x9c\x93@example.com")
