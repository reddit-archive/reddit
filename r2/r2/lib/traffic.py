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

from httplib import HTTPConnection
from urlparse import urlparse
from cPickle import loads
from utils import query_string
import os, socket, time, datetime
from pylons import g
from r2.lib.memoize import memoize

def load_traffic_uncached(interval, what, iden, 
                          start_time = None, stop_time = None,
                          npoints = None):
    """
    Fetches pickled traffic from the traffic server and returns it as a list.
    On connection failure (or no data) returns an empy list. 
    """
    from r2.lib import promote
    def format_date(d):
        if hasattr(d, "tzinfo"):
            if d.tzinfo is None:
                d = d.replace(tzinfo = g.tz)
            else:
                d = d.astimezone(g.tz)
        return ":".join(map(str, d.timetuple()[:6]))
    
    traffic_url = os.path.join(g.traffic_url, interval, what, iden)
    args = {}
    if what == 'thing' and interval == 'hour':
        if start_time:
            if not isinstance(start_time, datetime.datetime):
                start_time = datetime.datetime(*start_time.timetuple()[:3])
            start_time -= promote.timezone_offset
        if stop_time:
            if not isinstance(stop_time, datetime.datetime):
                stop_time = datetime.datetime(*stop_time.timetuple()[:3])
            stop_time -= promote.timezone_offset
    if start_time:
        args['start_time'] = format_date(start_time)
            
    if stop_time:
        args['stop_time'] = format_date(stop_time)
    if npoints:
        args['n'] = npoints
    u = urlparse(traffic_url)
    try:
        conn = HTTPConnection(u.hostname, u.port)
        conn.request("GET", u.path + query_string(args))
        res = conn.getresponse()
        res = loads(res.read()) if res.status == 200 else []
        conn.close()
        return res
    except socket.error:
        return []

#@memoize("cached_traffic", time = 60)
def load_traffic(interval, what, iden = '', 
                 start_time = None, stop_time = None,
                 npoints = None):
    """
     interval = (hour, day, month)
     
     what = (reddit, lang, thing, promos)
     
     iden is the specific thing (reddit name, language name, thing
     fullname) that one is seeking traffic for.
    """
    res = load_traffic_uncached(interval, what, iden, 
                                start_time = start_time, stop_time = stop_time,
                                npoints = npoints)

    if res and isinstance(res[0][0], datetime.datetime):
        dates, data = zip(*res)
        if interval == 'hour':
            # shift hourly totals into local time zone.
            dates = [x.replace(tzinfo=None) -
                     datetime.timedelta(0, time.timezone) for x in dates]
        else:
            # we don't care about the hours
            dates = [x.date() for x in dates]
        res = zip(dates, data)
    return res
    

def load_summary(what, interval = "month", npoints = 50):
    return load_traffic(interval, "summary", what, npoints = npoints)
