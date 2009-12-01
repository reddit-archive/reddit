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
from r2.models import Link, Subreddit
from r2.lib.db.operators import desc, timeago
from r2.lib import utils 
from r2.config import cache
from r2.lib.memoize import memoize
from r2.lib.db.thing import Query

from pylons import g

from datetime import datetime, timedelta
import random

expire_delta = timedelta(minutes = 2)
TOP_CACHE = 1800

def access_key(sr):
    return sr.name + '_access'

def expire_key(sr):
    return sr.name + '_expire'

def expire_hot(sr):
    """Called when a subreddit should be recomputed: after a vote (hence,
    submit) or deletion."""
    cache.set(expire_key(sr), True)

def cached_query(query, sr):
    """Returns the results from running query. The results are cached and
    only recomputed after 'expire_delta'"""
    query._limit = 150
    query._write_cache = True
    iden = query._iden()

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

    #set access time to the last time the query was actually run (now)
    if not read_cache:
        cache.set(access_key(sr), datetime.now())

    query._read_cache = read_cache
    res = list(query)

    return res

def get_hot(sr):
    """Get the hottest links for a subreddit. If g.use_query_cache is
    True, it'll use the query cache, otherwise it'll use cached_query()
    from above."""
    q = sr.get_links('hot', 'all')
    if isinstance(q, Query):
        return cached_query(q, sr)
    else:
        return Link._by_fullname(list(q)[:150], return_dict = False)

def only_recent(items):
    return filter(lambda l: l._date > utils.timeago('%d day' % g.HOT_PAGE_AGE),
                  items)

@memoize('normalize_hot', time = g.page_cache_time)
def normalized_hot_cached(sr_ids):
    """Fetches the hot lists for each subreddit, normalizes the scores,
    and interleaves the results."""
    results = []
    srs = Subreddit._byID(sr_ids, data = True, return_dict = False)
    for sr in srs:
        items = only_recent(get_hot(sr))

        if not items:
            continue

        top_score = max(max(x._hot for x in items), 1)
        if items:
            results.extend((l, l._hot / top_score) for l in items)

    results.sort(key = lambda x: (x[1], x[0]._hot), reverse = True)
    return [l[0]._fullname for l in results]

def normalized_hot(sr_ids):
    sr_ids = list(sr_ids)
    sr_ids.sort()
    return normalized_hot_cached(sr_ids) if sr_ids else ()
