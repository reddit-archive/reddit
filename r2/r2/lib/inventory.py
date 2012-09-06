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

import re

from collections import OrderedDict
from datetime import datetime, timedelta
from r2.models import traffic
from r2.models.promo_metrics import PromoMetrics
from pylons import g
from sqlalchemy import func

NDAYS_TO_QUERY = 14  # how much history to use in the estimate


class CassKeys:
    MIN_DAILY = 'min_daily_pageviews.GET_listing'


def get_predicted_by_date(sr_name, start, stop=None):
    '''
    For now, use lowest pageviews in the subreddit any day the last two weeks
    as a simple heuristic.
    '''
    # lowest pageviews any day the last 2 weeks
    min_daily = PromoMetrics.get(CassKeys.MIN_DAILY, sr_name).get(sr_name, 0)
    # expand out to the requested range of dates
    ndays = (stop - start).days if stop else 1  # default is one day
    predicted = OrderedDict()
    for i in range(ndays):
        date = start + timedelta(i)
        predicted[date] = min_daily
    return predicted


def update_prediction_data():
    '''
    Fetches prediction data and writes it to cassandra.
    '''
    min_daily_by_sr = _min_daily_pageviews_by_sr(NDAYS_TO_QUERY)
    PromoMetrics.set(CassKeys.MIN_DAILY, min_daily_by_sr)


def _min_daily_pageviews_by_sr(ndays=NDAYS_TO_QUERY, end_date=None):
    '''Returns a dict mapping sr_name to min_pageviews over the last ndays'''
    if not end_date:
        end_date = datetime.now()
    stop = end_date.date()
    start = stop - timedelta(ndays)
    cls = traffic.PageviewsBySubredditAndPath
    q = (traffic.Session.query(cls.srpath, func.min(cls.pageview_count))
                               .filter(cls.interval == 'day')
                               .filter(cls.date >= start)
                               .filter(cls.date < stop)
                               .filter(cls.srpath.like('%-GET_listing'))
                               .group_by(cls.srpath))

    # row looks like: ('lightpainting-GET_listing', 16)
    retval = {}
    for row in q:
        m = re.search('(.*)-GET_listing', row[0])
        if m:
            retval[m.group(1)] = row[1]
    return retval
