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

from datetime import timedelta

from r2.models import Subreddit
from r2.lib.db import tdb_cassandra
from r2.lib.memoize import memoize

def get_recommendations(srs):
    """
    Return the subreddits recommended if you like the given subreddit
    """

    # for now, but keep the API open for multireddits later
    assert len(srs) == 1 and srs[0].__class__ == Subreddit

    sr = srs[0]
    recs = _get_recommendations(sr._id36)
    if not recs:
        return []

    srs = Subreddit._byID36(recs, return_dict=True, data=True)

    return srs

@memoize('_get_recommendations', stale=True)
def _get_recommendations(srid36):
    return SRRecommendation.for_sr(srid36)

class SRRecommendation(tdb_cassandra.View):
    _use_db = True

    _compare_with = tdb_cassandra.LongType()

    # don't keep these around if a run hasn't happened lately, or if the last
    # N runs didn't generate recommendations for a given subreddit
    _ttl = timedelta(days=2)

    # we know that we mess with these but it's okay
    _warn_on_partial_ttl = False

    @classmethod
    def for_sr(cls, srid36, count=5):
        """
        Return the subreddits ID36s recommended by the sr whose id36 is passed
        """

        cq = tdb_cassandra.ColumnQuery(cls, [srid36],
                                       column_count = count+1,
                                       column_reversed = True)

        recs = [ r.values()[0] for r in cq if r.values()[0] != srid36 ][:count]

        return recs

    def _to_recs(self):
        recs = self._values() # [ {rank, srid} ]
        recs = sorted(recs.items(), key=lambda x: int(x[0]))
        recs = [x[1] for x in recs]
        return recs

