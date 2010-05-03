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
# The Original Code is Reddit.
# 
# The Original Developer is the Initial Developer.  The Initial Developer of the
# Original Code is CondeNet, Inc.
# 
# All portions of the code written by CondeNet are Copyright (c) 2006-2009
# CondeNet, Inc. All Rights Reserved.
################################################################################

from pylons import g
from datetime import timedelta as timedelta
from datetime import datetime
import sqlalchemy as sa
from r2.lib.db.tdb_lite import tdb_lite

class HardCacheBackend(object):
    def __init__(self, gc):
        self.tdb = tdb_lite(gc)
        metadata = self.tdb.make_metadata(gc.dbm.hardcache_db)

        self.table = sa.Table(gc.db_app_name + '_hardcache', metadata,
                         sa.Column('category', sa.String, nullable = False,
                                   primary_key = True),
                         sa.Column('ids', sa.String, nullable = False,
                                   primary_key = True),
                         sa.Column('value', sa.String, nullable = False),
                         sa.Column('kind', sa.String, nullable = False),
                         sa.Column('expiration',
                                   sa.DateTime(timezone = True),
                                   nullable = False)
                         )

        indstr = self.tdb.index_str(self.table, 'expiration', 'expiration')
        self.tdb.create_table(self.table, [ indstr ])

    def set(self, category, ids, val, time):

        self.delete(category, ids) # delete it if it already exists

        expiration = datetime.now(g.tz) + timedelta(0, time)

        value, kind = self.tdb.py2db(val, True)

        self.table.insert().execute(
            category=category,
            ids=ids,
            value=value,
            kind=kind,
            expiration=expiration
            )

    def get(self, category, ids):
        s = sa.select([self.table.c.value,
                       self.table.c.kind,
                       self.table.c.expiration],
                      sa.and_(self.table.c.category==category,
                              self.table.c.ids==ids),
                      limit = 1)
        rows = s.execute().fetchall()
        if len(rows) < 1:
            return None
        elif rows[0].expiration < datetime.now(g.tz):
            return None
        else:
            return self.tdb.db2py(rows[0].value, rows[0].kind)

    def delete(self, category, ids):
        self.table.delete(
            sa.and_(self.table.c.category==category,
                    self.table.c.ids==ids)).execute()

    def ids_by_category(self, category, limit=1000):
        s = sa.select([self.table.c.ids],
                      self.table.c.category==category,
                      limit = limit)
        rows = s.execute().fetchall()
        return [ r.ids for r in rows ]

    def clause_from_expiration(self, expiration):
        if expiration is None:
            return True
        elif expiration == "now":
            return self.table.c.expiration < datetime.now(g.tz)
        else:
            return self.table.c.expiration < expiration

    def expired(self, expiration_clause, limit=1000):
        s = sa.select([self.table.c.category,
                       self.table.c.ids,
                       self.table.c.expiration],
                      expiration_clause,
                      limit = limit,
                      order_by = self.table.c.expiration
                      )
        rows = s.execute().fetchall()
        return [ (r.expiration, r.category, r.ids) for r in rows ]

def delete_expired(expiration="now", limit=5000):
    hcb = HardCacheBackend(g)

    expiration_clause = hcb.clause_from_expiration(expiration)

    # Get all the expired keys
    rows = hcb.expired(expiration_clause, limit)

    if len(rows) == 0:
        return

    # Delete them from memcache
    mc_keys = [ "%s-%s" % (c, i) for e, c, i in rows ]
    g.memcache.delete_multi(mc_keys)

    # Now delete them from the backend.
    hcb.table.delete(expiration_clause).execute()

    # Note: In between the previous two steps, a key with a
    # near-instantaneous expiration could have been added and expired, and
    # thus it'll be deleted from the backend but not memcache. But that's
    # okay, because it should be expired from memcache anyway by now.
