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

import unittest

from r2.tests import stage_for_paste
stage_for_paste()

from pylons import c
from r2.lib.errors import errors, ErrorSet
from r2.lib.validator import VSubredditName, ValidEmail


class ValidatorTests(unittest.TestCase):
    def _test_failure(self, input, error):
        """Helper for testing bad inputs."""
        self.validator.run(input)
        self.assertTrue(self.validator.has_errors)
        self.assertTrue(c.errors.get((error, None)))

    def _test_success(self, input, assertEqual=True):
        result = self.validator.run(input)
        self.assertFalse(self.validator.has_errors)
        self.assertEqual(len(c.errors), 0)
        if assertEqual:
            self.assertEqual(result, input)

        return result


class TestVSubredditName(ValidatorTests):
    def setUp(self):
        # Reset the validator state and errors before every test.
        self.validator = VSubredditName(None)
        c.errors = ErrorSet()

    def _test_failure(self, input, error=errors.BAD_SR_NAME):
        super(TestVSubredditName, self)._test_failure(input, error)

    # Most of this validator's logic is already covered in `IsValidNameTest`.

    def test_slash_r_slash(self):
        result = self._test_success('/r/foo', assertEqual=False)
        self.assertEqual(result, 'foo')

    def test_r_slash(self):
        result = self._test_success('r/foo', assertEqual=False)
        self.assertEqual(result, 'foo')

    def test_two_prefixes(self):
        self._test_failure('/r/r/foo')

    def test_slash_not_prefix(self):
        self._test_failure('foo/r/')


class TestValidEmail(ValidatorTests):
    """Lightly test email address ("addr-spec") validation against RFC 2822.

    http://www.faqs.org/rfcs/rfc2822.html
    """
    def setUp(self):
        # Reset the validator state and errors before every test.
        self.validator = ValidEmail()
        c.errors = ErrorSet()

    def test_valid_emails(self):
        self._test_success('test@example.com')
        self._test_success('test@example.co.uk')
        self._test_success('test+foo@example.com')

    def _test_failure(self, email, error=errors.BAD_EMAIL):
        super(TestValidEmail, self)._test_failure(email, error)

    def test_blank_email(self):
        self._test_failure('', errors.NO_EMAIL)
        self.setUp()
        self._test_failure(' ', errors.NO_EMAIL)

    def test_no_whitespace(self):
        self._test_failure('test @example.com')
        self.setUp()
        self._test_failure('test@ example.com')
        self.setUp()
        self._test_failure('test@example. com')
        self.setUp()
        self._test_failure("test@\texample.com")

    def test_no_hostname(self):
        self._test_failure('example')
        self.setUp()
        self._test_failure('example@')

    def test_no_username(self):
        self._test_failure('example.com')
        self.setUp()
        self._test_failure('@example.com')

    def test_two_hostnames(self):
        self._test_failure('test@example.com@example.com')

