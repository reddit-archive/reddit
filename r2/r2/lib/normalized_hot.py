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
from r2.models import Link, Subreddit
from r2.lib.db.operators import desc, timeago
from r2.lib import utils 
from r2.config import cache
from r2.lib.memoize import memoize

from pylons import g

from datetime import datetime, timedelta
import random

expire_delta = timedelta(seconds = g.page_cache_time)
TOP_CACHE = 1800

def access_key(sr):
    return sr.name + '_access'

def expire_key(sr):
    return sr.name + '_expire'

def top_key(sr):
    return sr.name + '_top'

def expire_hot(sr):
    cache.set(expire_key(sr), True)

def is_top_link(sr, link):
    return cache.get(top_key(sr)) == link._fullname

def get_hot(sr):
    q = Link._query(Link.c.sr_id == sr._id,
                    sort = desc('_hot'),
                    write_cache = True,
                    limit = 150)

    iden = q._iden()

    read_cache = True
    #if query is in the cache, the expire flag is true, and the access
    #time is old, set read_cache = False
    if cache.get(iden) is not None:
        if cache.get(expire_key(sr)):
            access_time = cache.get(access_key(sr))
            if not access_time or datetime.now() > access_time + expire_delta:
                cache.delete(expire_key(sr))
                read_cache = False
    #if the query isn't in the cache, set read_cache to false so we
    #record the access time
    else:
        read_cache = False

    if not read_cache:
        cache.set(access_key(sr), datetime.now())
    
    q._read_cache = read_cache
    res = list(q)
    
    #set the #1 link so we can ignore it later. expire after TOP_CACHE
    #just in case something happens and that sr doesn't update
    if res:
        cache.set(top_key(sr), res[0]._fullname, TOP_CACHE)

    return res

@memoize('normalize_hot', time = g.page_cache_time)
def normalized_hot_cached(sr_ids):
    results = []
    srs = Subreddit._byID(sr_ids, data = True, return_dict = False)
    for sr in srs:
        #items = get_hot(sr)
        items = filter(lambda l: l._date > utils.timeago('%d day' % g.HOT_PAGE_AGE),
                       get_hot(sr))

        if not items:
            continue

        top_score = max(items[0]._hot, 1)
        
        top, rest = items[:2], items[2:]

        if top:
            normals = [l._hot / top_score for l in top]
            results.extend((l, random.choice(normals)) for l in top)
            #random.shuffle(normals)
            #results.extend((l, normals.pop()) for l in top)
        
        if rest:
            results.extend((l, l._hot / top_score) for l in rest)

    results.sort(key = lambda x: (x[1], x[0]._hot), reverse = True)
    return [l[0]._fullname for l in results]

def normalized_hot(sr_ids):
    sr_ids = list(sr_ids)
    sr_ids.sort()
    return normalized_hot_cached(sr_ids) if sr_ids else ()
