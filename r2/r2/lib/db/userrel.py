# "The contents of this file are subject to the Common Public Attribution
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
# The Original Code is Reddit.
# 
# The Original Developer is the Initial Developer.  The Initial Developer of the
# Original Code is CondeNet, Inc.
# 
# All portions of the code written by CondeNet are Copyright (c) 2006-2008
# CondeNet, Inc. All Rights Reserved.
################################################################################
from r2.lib.memoize import memoize, clear_memo

def UserRel(name, relation):
    all_memo_str = name + '.all_ids'
    reverse_memo_str = name + 'reverse'
    exists_name = 'is_' + name

    def userrel_exists(self, user):
        if not user:
            return False

        r = relation._fast_query([self], [user], name)
        r = r.get((self, user, name))
        if r:
            return r

    def userrel_add(self, user):
        fn = getattr(self, exists_name)
        if not fn(user):
            s = relation(self, user, name)
            s._commit()
            clear_memo(all_memo_str, self)
            clear_memo(reverse_memo_str, user)
            return s
    
    def userrel_remove(self, user):
        fn = getattr(self, exists_name)
        s = fn(user)
        if s:
            s._delete()
            clear_memo(all_memo_str, self)
            clear_memo(reverse_memo_str, user)
            return True

    @memoize(all_memo_str)
    def userrel_ids(self):
        q = relation._query(relation.c._thing1_id == self._id,
                            relation.c._name == name)
        #removed set() here, shouldn't be required
        return [r._thing2_id for r in q]

    @staticmethod
    @memoize(reverse_memo_str)
    def reverse_ids(user):
        q = relation._query(relation.c._thing2_id == user._id,
                            relation.c._name == name)
        return [r._thing1_id for r in q]

    class UR: pass

    setattr(UR, 'is_' + name, userrel_exists)
    setattr(UR, 'add_' + name, userrel_add)
    setattr(UR, 'remove_' + name, userrel_remove)
    setattr(UR, name + '_ids', userrel_ids)
    setattr(UR, 'reverse_' + name + '_ids', reverse_ids)

    return UR
        
