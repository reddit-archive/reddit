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
from pylons import g, c
from r2.models import *
from r2.lib.utils import to36
from datetime import datetime, timedelta

from r2.lib.db import tdb_sql as tdb
import sqlalchemy as sa


def sgn(x):
    return 1 if x > 0 else 0 if x == 0 else -1

def get_recommended(userid, age = 2, sort='relevance', num_users=10):
    u = get_users_for_user(userid)[:num_users]
    if not u: return []

    voter = Vote.rels[(Account, Link)]

    votertable = tdb.rel_types_id[voter._type_id].rel_table[0]
    acct_col = votertable.c.thing1_id
    link_col = votertable.c.thing2_id
    date_col = votertable.c.date
    count = sa.func.count(acct_col)

    linktable = tdb.rel_types_id[voter._type_id].rel_table[2]
#    dlinktable, linktable = tdb.types_id[Link._type_id].data_table
    link_id_col = linktable.c.thing_id

    query = [sa.or_(*[acct_col == x for x in u]),
             date_col > datetime.now(g.tz)-timedelta(age)]
    cols = [link_col, count]

    if sort == 'new':
        sort = 'date'
    elif sort == 'top':
        sort = 'score'

    if sort and sort != 'relevance':
        query.append(link_id_col == link_col)
        s = tdb.translate_sort(linktable, sort)
        order = [sa.desc(s), sa.desc(link_id_col)]
        cols = [link_id_col, count]
        group_by = [link_id_col, s]
    else:
        order = [sa.desc(count), sa.desc(link_col)]
        group_by = link_col

#    #TODO: wish I could just use query_rules
#    if c.user and c.user.subreddits:
#        query.append(dlinktable.c.thing_id == linktable.c.thing_id)
#        q = sa.and_(dlinktable.c.key == 'sr_id',
#                    sa.or_(*[dlinktable.c.value == x
#                             for x in c.user.subreddits]))
#        query.append(q)

    res = sa.select(cols, sa.and_(*query),
                    group_by=group_by,
                    order_by=order).execute()


    prefix = "t%s" % to36(Link._type_id)
    return ["%s_%s" % (prefix, to36(x)) for x, y in res.fetchall()]
    


def get_users_for_user(userid, dateWeight = 0.1):
    e = load_from_mc(userid, True, dateWeight)
    u = []
    if e:
        users = dict((e[i], e[i+1]) for i in range(0, len(e), 2))
        u = users.keys()
        u.sort(lambda x, y: sgn(users[y] - users[x]))
    return u

def grab_int(str, start, end):
    rval = 0;
    entry = str[start:end]
    for x in entry[::-1]:
        rval = (rval << 8) | (ord(x) & 255)
    return rval;

def load_from_mc(userid, positiveOnly = True, dateWeight = 0):
   cachedEntry = g.rec_cache.get("recommend_" + str(userid))
   rval = []
   resortingHash = {}
   min_id = None;
   max_id = None

   if cachedEntry:
       record_size = ord(cachedEntry[0])
       num_records = grab_int(cachedEntry, 1, record_size)
       offset = record_size;
       for i in range(0, num_records):
           key = grab_int(cachedEntry, 
                          i*record_size + offset,
                          (i+1)*record_size + offset-1)
           value = float(ord(cachedEntry[(i+1)*record_size + offset-1]))/128.

           if not min_id or key < min_id:
               min_id = key
           if not max_id or key > max_id:
               max_id = key

           if value > 1: value -= 2
           if value < 0 and positiveOnly: continue
           rval += [key, value]
           resortingHash[key] = value
       
       if dateWeight > 0 and min_id != max_id:
           arts = resortingHash.keys()
           def sortingFunc(x, y):
               qx = ( dateWeight * float(x - min_id) / (max_id - min_id) +
                      (1-dateWeight) * resortingHash[x])
               qy = ( dateWeight * float(y - min_id) / (max_id - min_id) +
                      (1-dateWeight) * resortingHash[y])
               return cmp(qy, qx)
           arts.sort(sortingFunc)
           rval = []
           for x in arts:
               rval += [x, resortingHash[x]]

   return rval

def getQualityForUser(userid, min = 0, max = 100):
    cachedEntry = load_from_mc(userid, False)
    rhash = {}
    for i in range(0,len(cachedEntry)/2):
        rhash[cachedEntry[2*i]] = (max - min)*cachedEntry[2*i+1] + min
    return rhash
