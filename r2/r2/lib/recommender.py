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

import itertools
import math
from collections import defaultdict
from datetime import timedelta
from operator import itemgetter

from r2.models import Subreddit
from r2.lib.sgm import sgm
from r2.lib.db import tdb_cassandra
from r2.lib.utils import tup

from pylons import g

SRC_LINKVOTES = 'lv'
SRC_MULTIREDDITS = 'mr'


def get_recommendations(srs, count=10, source=SRC_MULTIREDDITS, to_omit=None):
    """Return subreddits recommended if you like the given subreddits.

    Args:
    - srs is one Subreddit object or a list of Subreddits
    - count is total number of results to return
    - source is a prefix telling which set of recommendations to use
    - to_omit is one Subreddit object or a list of Subreddits that should not
        be included. (Useful for omitting recs that were already rejected.)

    """
    srs = tup(srs)
    to_omit = tup(to_omit) if to_omit else []
    
    # fetch more recs than requested because some might get filtered out
    rec_id36s = SRRecommendation.for_srs([sr._id36 for sr in srs],
                                         [o._id36 for o in to_omit],
                                          count * 2,
                                          source)

    # always check for private subreddits at runtime since type might change
    rec_srs = Subreddit._byID36(rec_id36s, return_dict=False)
    filtered = [sr for sr in rec_srs if sr.type != 'private']

    # don't recommend adult srs unless one of the originals was over_18
    if not any(sr.over_18 for sr in srs):
        filtered = [sr for sr in filtered if not sr.over_18]

    return filtered[:count]


class SRRecommendation(tdb_cassandra.View):
    _use_db = True

    _compare_with = tdb_cassandra.LongType()

    # don't keep these around if a run hasn't happened lately, or if the last
    # N runs didn't generate recommendations for a given subreddit
    _ttl = timedelta(days=7, hours=12)

    # we know that we mess with these but it's okay
    _warn_on_partial_ttl = False

    @classmethod
    def for_srs(cls, srid36, to_omit, count=10, source=SRC_MULTIREDDITS):
        # It's usually better to use get_recommendations() than to call this
        # function directly because it does privacy filtering.

        srid36s = tup(srid36)
        to_omit = set(to_omit)
        to_omit.update(srid36s)  # don't show the originals
        rowkeys = ['%s.%s' % (source, srid36) for srid36 in srid36s]

        # fetch multiple sets of recommendations, one for each input srid36
        d = sgm(g.cache, rowkeys, SRRecommendation._byID, prefix='srr.')
        rows = d.values()

        sorted_recs = SRRecommendation._merge_and_sort_by_count(rows)
        
        # heuristic: if the input set is large, rec should match more than one
        min_count = math.floor(.1 * len(srid36s))
        sorted_recs = (rec[0] for rec in sorted_recs if rec[1] > min_count)

        # remove duplicates and ids listed in to_omit
        filtered = []
        for r in sorted_recs:
            if r not in to_omit:
                filtered.append(r)
                to_omit.add(r)
        return filtered[:count]

    @classmethod
    def _merge_and_sort_by_count(cls, rows):
        """Combine and sort multiple sets of recs.

        Combines multiple sets of recs and sorts by number of times each rec
        appears, the reasoning being that an item recommended for several of
        the original srs is more likely to match the "theme" of the set.

        """
        # combine recs from all input srs
        rank_id36_pairs = itertools.chain(*[row._values().iteritems()
                                            for row in rows])
        ranks = defaultdict(list)
        for rank, id36 in rank_id36_pairs:
            ranks[id36].append(rank)
        recs = [(id36, len(ranks), max(ranks)) for id36, ranks in ranks.iteritems()]
        # first, sort ascending by rank
        recs = sorted(recs, key=itemgetter(2))
        # next, sort descending by number of times the rec appeared. since
        # python sort is stable, tied items will still be ordered by rank
        return sorted(recs, key=itemgetter(1), reverse=True)

    def _to_recs(self):
        recs = self._values() # [ {rank, srid} ]
        recs = sorted(recs.items(), key=lambda x: int(x[0]))
        recs = [x[1] for x in recs]
        return recs
