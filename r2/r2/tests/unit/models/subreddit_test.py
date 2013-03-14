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

import unittest

from r2.lib.permissions import PermissionSet

from r2.models.account import Account
from r2.models.subreddit import SRMember, Subreddit

class TestPermissionSet(PermissionSet):
    info = dict(x={}, y={})


class SRMemberTest(unittest.TestCase):
    def setUp(self):
        a = Account()
        a._commit()
        sr = Subreddit()
        sr._commit()
        self.rel = SRMember(sr, a, 'test')

    def test_get_permissions(self):
        self.assertRaises(NotImplementedError, self.rel.get_permissions)
        self.rel._permission_class = TestPermissionSet
        self.assertEquals('', self.rel.get_permissions().dumps())
        self.rel.encoded_permissions = '+x,-y'
        self.assertEquals('+x,-y', self.rel.get_permissions().dumps())

    def test_has_permission(self):
        self.assertRaises(NotImplementedError, self.rel.has_permission, 'x')
        self.rel._permission_class = TestPermissionSet
        self.assertFalse(self.rel.has_permission('x'))
        self.rel.encoded_permissions = '+x,-y'
        self.assertTrue(self.rel.has_permission('x'))
        self.assertFalse(self.rel.has_permission('y'))
        self.rel.encoded_permissions = '+all'
        self.assertTrue(self.rel.has_permission('x'))
        self.assertTrue(self.rel.has_permission('y'))
        self.assertFalse(self.rel.has_permission('z'))

    def test_update_permissions(self):
        self.assertRaises(NotImplementedError,
                          self.rel.update_permissions, x=True)
        self.rel._permission_class = TestPermissionSet
        self.rel.update_permissions(x=True, y=False)
        self.assertEquals('+x,-y', self.rel.encoded_permissions)
        self.rel.update_permissions(x=None)
        self.assertEquals('-y', self.rel.encoded_permissions)
        self.rel.update_permissions(y=None, z=None)
        self.assertEquals('', self.rel.encoded_permissions)
        self.rel.update_permissions(x=True, y=False, all=True)
        self.assertEquals('+all', self.rel.encoded_permissions)

    def test_set_permissions(self):
        self.rel.set_permissions(PermissionSet(x=True, y=False))
        self.assertEquals('+x,-y', self.rel.encoded_permissions)

    def test_is_superuser(self):
        self.assertRaises(NotImplementedError, self.rel.is_superuser)
        self.rel._permission_class = TestPermissionSet
        self.assertFalse(self.rel.is_superuser())
        self.rel.encoded_permissions = '+all'
        self.assertTrue(self.rel.is_superuser())

if __name__ == '__main__':
    unittest.main()
