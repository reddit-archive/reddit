#!/usr/bin/env python

import unittest

from r2.tests import stage_for_paste

stage_for_paste()

from r2.lib.permissions import PermissionSet, ModeratorPermissionSet

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

