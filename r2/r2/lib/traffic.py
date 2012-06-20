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

import time
import datetime

from r2.lib import promote
from r2.models import traffic


def force_datetime(dt):
    if isinstance(dt, datetime.datetime):
        return dt
    elif isinstance(dt, datetime.date):
        return datetime.datetime.combine(dt, datetime.time())
    else:
        raise NotImplementedError()


def load_traffic(interval, what, iden="",
                 start_time=None, stop_time=None,
                 npoints=None):
    if what == "reddit":
        sr_traffic = traffic.PageviewsBySubreddit.history(interval, iden)

        # add in null values for cname stuff
        res = [(t, v + (0, 0)) for (t, v) in sr_traffic]

        # day interval needs subscription numbers
        if interval == "day":
            subscriptions = traffic.SubscriptionsBySubreddit.history(interval,
                                                                     iden)
            res = traffic.zip_timeseries(res, subscriptions)
    elif what == "total":
        res = traffic.SitewidePageviews.history(interval)
    elif what == "summary" and iden == "reddit" and interval == "month":
        sr_traffic = traffic.PageviewsBySubreddit.top_last_month()
        # add in null values for cname stuff
        # return directly because this doesn't have a date parameter first
        return [(t, v + (0, 0)) for (t, v) in sr_traffic]
    elif what == "promos" and interval == "day":
        pageviews = traffic.AdImpressionsByCodename.historical_totals(interval)
        clicks = traffic.ClickthroughsByCodename.historical_totals(interval)
        res = traffic.zip_timeseries(pageviews, clicks)
    elif what == "thing" and interval == "hour" and start_time:
        start_time = force_datetime(start_time) - promote.timezone_offset
        stop_time = force_datetime(stop_time) - promote.timezone_offset
        pageviews = traffic.AdImpressionsByCodename.promotion_history(iden,
                                                                      start_time,
                                                                      stop_time)
        clicks = traffic.ClickthroughsByCodename.promotion_history(iden,
                                                                   start_time,
                                                                   stop_time)
        res = traffic.zip_timeseries(pageviews, clicks)
    elif what == "thing" and not start_time:
        pageviews = traffic.AdImpressionsByCodename.history(interval, iden)
        clicks = traffic.ClickthroughsByCodename.history(interval, iden)
        res = traffic.zip_timeseries(pageviews, clicks)
    else:
        raise NotImplementedError()

    if interval == "hour":
        # convert to local time
        tzoffset = datetime.timedelta(0, time.timezone)
        res = [(d - tzoffset, v) for d, v in res]
    else:
        res = [(d.date(), v) for d, v in res]

    return res


def load_summary(what, interval = "month", npoints = 50):
    return load_traffic(interval, "summary", what, npoints = npoints)
