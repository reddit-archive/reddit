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

from r2.lib.db import tdb_cassandra
from r2.lib.utils import tup
from r2.models.subreddit import DefaultSR


class PromoMetrics(tdb_cassandra.View):
    '''
    Cassandra data store for promotion metrics. Used for inventory prediction.

    Usage:
      # set metric value for many subreddits at once
      > PromoMetrics.set('min_daily_pageviews.GET_listing',
                          {'funny': 63432, 'pics': 48829, 'books': 4})

      # get metric value for one subreddit
      > res = PromoMetrics.get('min_daily_pageviews.GET_listing', 'funny')
      {'funny': 1234}

      # get metric value for many subreddits
      > res = PromoMetrics.get('min_daily_pageviews.GET_listing',
                               ['funny', 'pics'])
      {'funny':1234, 'pics':4321}

      # get metric values for all subreddits
      > res = PromoMetrics.get('min_daily_pageviews.GET_listing')
    '''
    _use_db = True
    _value_type = 'int'
    _fetch_all_columns = True

    @classmethod
    def get(cls, metric_name, sr_names=None):
        sr_names = tup(sr_names)
        metric = cls._byID(metric_name, properties=sr_names)
        return metric._values()  # might have additional values

    @classmethod
    def set(cls, metric_name, values_by_sr):
        if '' in values_by_sr:  # combine front page values
            fp = DefaultSR.name.lower()
            values_by_sr[fp] = values_by_sr.get(fp, 0) + values_by_sr['']
            del(values_by_sr[''])
        cls._set_values(metric_name, values_by_sr)
