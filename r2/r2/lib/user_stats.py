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
import sqlalchemy as sa
from r2.models import Account, Vote, Link
from r2.lib.db import tdb_sql as tdb
from r2.lib import utils

from pylons import g 
cache = g.cache

def top_users():
    type = tdb.types_id[Account._type_id]
    tt, dt = type.thing_table, type.data_table[0]

    karma = dt.alias()

    s = sa.select([tt.c.thing_id],
                  sa.and_(tt.c.spam == False,
                          tt.c.deleted == False,
                          karma.c.thing_id == tt.c.thing_id,
                          karma.c.key == 'link_karma'),
                  order_by = sa.desc(sa.cast(karma.c.value, sa.Integer)),
                  limit = 10)
    rows = s.execute().fetchall()
    return [r.thing_id for r in rows]

def top_user_change(period = '1 day'):
    rel = Vote.rel(Account, Link)
    type = tdb.rel_types_id[rel._type_id]
    rt, account, link, dt = type.rel_table

    author = dt.alias()

    date = utils.timeago(period)
    
    s = sa.select([author.c.value, sa.func.sum(sa.cast(rt.c.name, sa.Integer))],
                  sa.and_(rt.c.date > date,
                          author.c.thing_id == rt.c.rel_id,
                          author.c.key == 'author_id'),
                  group_by = author.c.value,
                  order_by = sa.desc(sa.func.sum(sa.cast(rt.c.name, sa.Integer))),
                  limit = 10)

    rows = s.execute().fetchall()
    
    return [(int(r.value), r.sum) for r in rows]

def calc_stats():
    top = top_users()
    top_day = top_user_change('1 day')
    top_week = top_user_change('1 week')
    return (top, top_day, top_week)

def set_stats():
    cache.set('stats', calc_stats())
