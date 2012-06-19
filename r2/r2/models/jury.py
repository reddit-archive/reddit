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

from r2.lib.db.thing import DataThing, Thing, MultiRelation, Relation
from r2.lib.db.thing import NotFound, load_things
from r2.lib.db.userrel import UserRel
from r2.lib.db.operators import asc, desc, lower
from r2.lib.memoize import memoize
from r2.lib.utils import timeago
from r2.models import Account, Link
from pylons import c, g, request

class Jury(MultiRelation('jury',
                         Relation(Account, Link))):
    @classmethod
    def _new(cls, account, defendant):
        j = Jury(account, defendant, "0")

        j._commit()

        Jury.by_account(account, _update=True)
        Jury.by_defendant(defendant, _update=True)

        return j

    @classmethod
    @memoize('jury.by_account')
    def by_account_cache(cls, account_id):
        q = cls._query(cls.c._thing1_id == account_id)
        q._limit = 100
        return [ j._fullname for j in q ]

    @classmethod
    def by_account(cls, account, _update=False):
        rel_ids = cls.by_account_cache(account._id, _update=_update)
        juries = DataThing._by_fullname(rel_ids, data=True,
                                        return_dict = False)
        if juries:
            load_things(juries, load_data=True)
        return juries

    @classmethod
    @memoize('jury.by_defendant')
    def by_defendant_cache(cls, defendant_id):
        q = cls._query(cls.c._thing2_id == defendant_id)
        q._limit = 1000
        return [ j._fullname for j in q ]

    @classmethod
    def by_defendant(cls, defendant, _update=False):
        rel_ids = cls.by_defendant_cache(defendant._id, _update=_update)
        juries = DataThing._by_fullname(rel_ids, data=True,
                                        return_dict = False)
        if juries:
            load_things(juries, load_data=True)
        return juries

    @classmethod
    def by_account_and_defendant(cls, account, defendant):
        q = cls._fast_query(account, defendant, ("-1", "0", "1"))
        v = filter(None, q.values())
        if v:
            return v[0]

    @classmethod
    def delete_old(cls, age="3 days", limit=500, verbose=False):
        cutoff = timeago(age)
        q = cls._query(cls.c._date < cutoff)
        q._limit = limit

        accounts = set()
        defendants = set()
        for j in q:
            accounts.add(j._thing1)
            defendants.add(j._thing2)
            j._delete()

        for a in accounts:
            Jury.by_account(a, _update=True)

        for d in defendants:
            if verbose:
                print "Deleting juries for defendant %s" % d._fullname
            Jury.by_defendant(d, _update=True)
