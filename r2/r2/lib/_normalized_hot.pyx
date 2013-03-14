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
# All portions of the code written by reddit are Copyright (c) 2006-2013 reddit
# Inc. All Rights Reserved.
###############################################################################

from r2.models import Subreddit, Link
from r2.lib.db.sorts import epoch_seconds
from r2.lib.db.thing import Query
from r2.lib.db.queries import CachedResults
from r2.lib.db.operators import timeago

from pylons import g
from time import time

max_items = 150 # the number of links to request from the hot page
                # query when the precomputer is disabled

cpdef list get_hot(list srs, only_fullnames=True, obey_age_limit=True):
    """Get the fullnames for the hottest normalised hottest links in a
       subreddit. Use the query-cache to avoid some lookups if we
       can."""
    cdef double oldest
    cdef int hot_page_age = 0
    if obey_age_limit:
        hot_page_age = g.HOT_PAGE_AGE
    cdef int i
    cdef double hot
    cdef double thot # the top hotness on a given subreddit
    cdef double ehot # the effective normalised hotness of a given link
    cdef double es

    cdef list links
    cdef list queries
    cdef list cachedresults

    links = []
    queries = []
    cachedresults = []

    for sr in srs:
        q = sr.get_links('hot', 'all')
        if isinstance(q, CachedResults):
            cachedresults.append(q)
        queries.append(q)

    # fetch these all in one go
    CachedResults.fetch_multi(cachedresults)

    if hot_page_age:
        oldest = time() - 60*60*24*hot_page_age

    for q in queries:

        if isinstance(q, Query):
            if hot_page_age:
                q._filter(Link.c._date > timeago('%d days' % hot_page_age))
            q._limit = max_items
            for i, link in enumerate(q):
                if i == 0:
                    hot = link._hot
                    thot = max(hot, 1.0)
                es = epoch_seconds(link._date)
                if not hot_page_age or es > oldest:
                    if i == 0:
                        ehot = 1.0
                    else:
                        hot = link._hot
                        ehot = hot/thot
                    links.append((ehot, hot, link._fullname))

        elif isinstance(q, CachedResults):
            # we're relying on an implementation detail of
            # CachedResults here, where it's storing tuples that look
            # exactly like the return-type we want, to make our
            # sorting a bit cheaper

            for i, (fname, hot, es) in enumerate(q.data[:max_items]):
                if i == 0:
                    thot = max(hot, 1.0)
                if not hot_page_age or es > oldest:
                    if i == 0:
                        ehot = 1.0
                    else:
                        ehot = hot/thot
                    links.append((ehot, hot, fname))

    links.sort(reverse=True)

    if only_fullnames:
        return map(_second, links)
    else:
        return links

cpdef _second(tuple x):
    return x[2]

# memoized by our caller in normalized_hot.py
cpdef list normalized_hot_cached(sr_ids, obey_age_limit=True):
    """Fetches the hot lists for each subreddit, normalizes the
       scores, and interleaves the results."""
    srs = Subreddit._byID(sr_ids, return_dict=False)
    return get_hot(srs, True, obey_age_limit)
