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
# All portions of the code written by CondeNet are Copyright (c) 2006-2010
# CondeNet, Inc. All Rights Reserved.
################################################################################
from r2.models import Link, Subreddit
from r2.lib.db.operators import desc, timeago
from r2.lib.db.sorts import epoch_seconds

from r2.lib import utils 
from r2.config import cache
from r2.lib.memoize import memoize

from pylons import g

from datetime import datetime, timedelta
import random

expire_delta = timedelta(minutes = 2)
max_items = 150

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
    query._limit = max_items
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

def get_hot(srs, only_fullnames = False):
    """Get the (fullname, hotness, epoch_seconds) for the hottest
       links in a subreddit. Use the query-cache to avoid some lookups
       if we can."""
    from r2.lib.db.thing import Query
    from r2.lib.db.queries import CachedResults

    ret = []
    queries = [sr.get_links('hot', 'all') for sr in srs]

    # fetch these all in one go
    cachedresults = filter(lambda q: isinstance(q, CachedResults), queries)
    CachedResults.fetch_multi(cachedresults)

    for q in queries:
        if isinstance(q, Query):
            links = cached_query(q, sr)
            res = [(link._fullname, link._hot, epoch_seconds(link._date))
                   for link in links]
        elif isinstance(q, CachedResults):
            # we're relying on an implementation detail of
            # CachedResults here, where it's storing tuples that look
            # exactly like the return-type we want, to make our
            # sorting a bit cheaper
            res = list(q.data)

        # remove any that are too old
        age_limit = epoch_seconds(utils.timeago('%d days' % g.HOT_PAGE_AGE))
        res = [(fname if only_fullnames else (fname, hot, date))
               for (fname, hot, date) in res
               if date > age_limit]
        ret.append(res)

    return ret

@memoize('normalize_hot', time = g.page_cache_time)
def normalized_hot_cached(sr_ids):
    """Fetches the hot lists for each subreddit, normalizes the
       scores, and interleaves the results."""
    results = []
    srs = Subreddit._byID(sr_ids, return_dict = False)
    hots = get_hot(srs)
    for items in hots:
        if not items:
            continue

        # items =:= (fname, hot, epoch_seconds), ordered desc('_hot')
        items = items[:max_items]

        # the hotness of the hottest item in this subreddit
        top_score = max(items[0][1], 1)

        results.extend((fname, hot/top_score, hot, date)
                       for (fname, hot, date) in items)

    # sort by (normalized_hot, hot, date)
    results.sort(key = lambda x: x[1:], reverse = True)

    # and return the fullnames
    return [l[0] for l in results]

def normalized_hot(sr_ids):
    sr_ids = list(sorted(sr_ids))
    return normalized_hot_cached(sr_ids) if sr_ids else ()
