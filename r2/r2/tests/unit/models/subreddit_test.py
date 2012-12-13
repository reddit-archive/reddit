#!/usr/bin/env python

import unittest

from r2.models.account import Account
from r2.models.subreddit import (
    ModeratorPermissionSet,
    PermissionSet,
    SRMember,
    Subreddit,
)

class TestPermissionSet(PermissionSet):
    info = dict(x={}, y={})

class PermissionSetTest(unittest.TestCase):
    def test_dumps(self):
        self.assertEquals(
            '+all', PermissionSet(all=True).dumps())
        self.assertEquals(
            '+all', PermissionSet(all=True, other=True).dumps())
        self.assertEquals(
            '+a,-b', PermissionSet(a=True, b=False).dumps())

    def test_loads(self):
        self.assertEquals("", TestPermissionSet.loads(None).dumps())
        self.assertEquals("", TestPermissionSet.loads("").dumps())
        self.assertEquals("+x,+y", TestPermissionSet.loads("+x,+y").dumps())
        self.assertEquals("+x,-y", TestPermissionSet.loads("+x,-y").dumps())
        self.assertEquals("+all", TestPermissionSet.loads("+x,-y,+all").dumps())
        self.assertEquals("+x,-y,+z",
                          TestPermissionSet.loads("+x,-y,+z").dumps())
        self.assertRaises(ValueError,
                          TestPermissionSet.loads, "+x,-y,+z", validate=True)
        self.assertEquals(
            "+x,-y",
            TestPermissionSet.loads("-all,+x,-y", validate=True).dumps())

    def test_is_superuser(self):
        perm_set = PermissionSet()
        self.assertFalse(perm_set.is_superuser())
        perm_set[perm_set.ALL] = True
        self.assertTrue(perm_set.is_superuser())
        perm_set[perm_set.ALL] = False
        self.assertFalse(perm_set.is_superuser())

    def test_is_valid(self):
        perm_set = PermissionSet()
        self.assertFalse(perm_set.is_valid())

        perm_set = TestPermissionSet()
        self.assertTrue(perm_set.is_valid())
        perm_set['x'] = True
        self.assertTrue(perm_set.is_valid())
        perm_set[perm_set.ALL] = True
        self.assertTrue(perm_set.is_valid())
        perm_set['z'] = True
        self.assertFalse(perm_set.is_valid())

    def test_getitem(self):
        perm_set = PermissionSet()
        perm_set[perm_set.ALL] = True
        self.assertFalse(perm_set['x'])

        perm_set = TestPermissionSet()
        perm_set['x'] = True
        self.assertTrue(perm_set['x'])
        self.assertFalse(perm_set['y'])
        perm_set['x'] = False
        self.assertFalse(perm_set['x'])
        perm_set[perm_set.ALL] = True
        self.assertTrue(perm_set['x'])
        self.assertTrue(perm_set['y'])
        self.assertFalse(perm_set['z'])
        self.assertTrue(perm_set.get('x', False))
        self.assertFalse(perm_set.get('z', False))
        self.assertTrue(perm_set.get('z', True))


class ModeratorPermissionSetTest(unittest.TestCase):
    def test_loads(self):
        self.assertTrue(ModeratorPermissionSet.loads(None).is_superuser())
        self.assertFalse(ModeratorPermissionSet.loads('').is_superuser())


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
