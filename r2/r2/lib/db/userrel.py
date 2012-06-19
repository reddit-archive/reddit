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
# All portions of the code written by reddit are Copyright (c) 2006-2012 reddit
# Inc. All Rights Reserved.
###############################################################################

from r2.lib.memoize import memoize

def UserRel(name, relation, disable_ids_fn = False, disable_reverse_ids_fn = False):

    exists_fn_name = 'is_' + name
    def userrel_exists(self, user):
        if not user:
            return False

        r = relation._fast_query([self], [user], name)
        r = r.get((self, user, name))
        if r:
            return r

    update_caches_fn_name = name + 'update_' + name + '_caches'
    def update_caches(self, user):
        if not disable_ids_fn:
            getattr(self, ids_fn_name)(_update = True)

        if not disable_reverse_ids_fn:
            getattr(self, reverse_ids_fn_name)(user, _update = True)

    add_fn_name =  'add_' + name
    def userrel_add(self, user):
        fn = getattr(self, exists_fn_name)
        if not fn(user):
            s = relation(self, user, name)
            s._commit()

            #update caches
            getattr(self, update_caches_fn_name)(user)
            return s
    
    remove_fn_name = 'remove_' + name
    def userrel_remove(self, user):
        fn = getattr(self, exists_fn_name)
        s = fn(user)
        if s:
            s._delete()

            #update caches
            getattr(self, update_caches_fn_name)(user)
            return True

    ids_fn_name = name + '_ids'
    @memoize(ids_fn_name)
    def userrel_ids(self):
        q = relation._query(relation.c._thing1_id == self._id,
                            relation.c._name == name,
                            sort = "_date")
        #removed set() here, shouldn't be required
        return [r._thing2_id for r in q]

    reverse_ids_fn_name = 'reverse_' + name + '_ids'
    @staticmethod
    @memoize(reverse_ids_fn_name)
    def reverse_ids(user):
        q = relation._query(relation.c._thing2_id == user._id,
                            relation.c._name == name)
        return [r._thing1_id for r in q]

    class UR: pass

    setattr(UR, update_caches_fn_name, update_caches)
    setattr(UR, exists_fn_name, userrel_exists)
    setattr(UR, add_fn_name, userrel_add)
    setattr(UR, remove_fn_name, userrel_remove)
    if not disable_ids_fn:
        setattr(UR, ids_fn_name, userrel_ids)
    if not disable_reverse_ids_fn:
        setattr(UR, reverse_ids_fn_name, reverse_ids)

    return UR
        
