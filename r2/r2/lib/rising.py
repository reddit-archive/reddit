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

from datetime import datetime

from pylons import g

from r2.lib import count
from r2.models.link import Link


CACHE_KEY = "rising"


def calc_rising():
    sr_count = count.get_link_counts()
    link_count = dict((k, v[0]) for k,v in sr_count.iteritems())
    link_names = Link._by_fullname(sr_count.keys(), data=True)

    #max is half the average of the top 10 counts
    counts = link_count.values()
    counts.sort(reverse=True)
    maxcount = sum(counts[:10]) / 20

    #prune the list
    rising = [(n, link_names[n].sr_id)
              for n in link_names.keys() if link_count[n] < maxcount]

    cur_time = datetime.now(g.tz)

    def score(pair):
        name = pair[0]
        link = link_names[name]
        hours = (cur_time - link._date).seconds / 3600 + 1
        return float(link._ups) / (max(link_count[name], 1) * hours)

    def r(x):
        return 1 if x > 0 else -1 if x < 0 else 0

    rising.sort(lambda x, y: r(score(y) - score(x)))
    return rising


def set_rising():
    g.cache.set(CACHE_KEY, calc_rising())


def get_rising(sr):
    rising = g.cache.get(CACHE_KEY, [])
    return [link for link, sr_id in rising if sr.keep_for_rising(sr_id)]
