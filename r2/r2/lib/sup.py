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
from itertools import ifilter
import time
import hashlib

import simplejson

from r2.lib.utils import rfc3339_date_str, http_date_str, to36
from r2.lib.memoize import memoize
from r2.lib.template_helpers import get_domain
from pylons import g, c, response

PERIODS = [600, 300, 60]
MIN_PERIOD = min(PERIODS)
MAX_PERIOD = max(PERIODS)

def sup_url():
    return 'http://%s/sup.json' % get_domain(subreddit = False)

def period_urls():
    return dict((p, sup_url() + "?seconds=" + str(p)) for p in PERIODS)

def cache_key(ts):
    return 'sup_' + str(ts)

def make_cur_time(period):
    t = int(time.time())
    return t - t % period

def make_last_time(period):
    return make_cur_time(period) - period

def make_sup_id(user, action):
    sup_id = hashlib.md5(user.name + action).hexdigest()
    #cause cool kids only use part of the hash
    return sup_id[:10]

def add_update(user, action):
    update_time = int(time.time())
    sup_id = make_sup_id(user, action)
    supdate = ',%s:%s' % (sup_id, update_time)

    key = cache_key(make_cur_time(MIN_PERIOD))
    g.cache.add(key, '')
    g.cache.append(key, supdate)

@memoize('set_json', time = MAX_PERIOD)
def sup_json_cached(period, last_time):
    #we need to re-add MIN_PERIOD because we moved back that far with
    #the call to make_last_time
    target_time = last_time + MIN_PERIOD - period

    updates = ''
    #loop backwards adding MIN_PERIOD chunks until last_time is as old
    #as target time
    while last_time >= target_time:
        updates += g.cache.get(cache_key(last_time)) or ''
        last_time -= MIN_PERIOD

    supdates = []
    if updates:
        for u in ifilter(None, updates.split(',')):
            sup_id, time = u.split(':')
            time = int(time)
            if time >= target_time:
                supdates.append([sup_id, to36(time)])

    update_time = datetime.utcnow()
    since_time = datetime.utcfromtimestamp(target_time)
    json = simplejson.dumps({'updated_time' : rfc3339_date_str(update_time),
                             'since_time' : rfc3339_date_str(since_time),
                             'period' : period,
                             'available_periods' : period_urls(),
                             'updates' : supdates})

    #undo json escaping
    json = json.replace('\/', '/')
    return json

def sup_json(period):
    return sup_json_cached(period, make_last_time(MIN_PERIOD))

def set_sup_header(user, action):
    sup_id = make_sup_id(user, action)
    response.headers['x-sup-id'] = sup_url() + '#' + sup_id

def set_expires_header():
    seconds = make_cur_time(MIN_PERIOD) + MIN_PERIOD
    expire_time = datetime.fromtimestamp(seconds, g.tz)
    response.headers['expires'] = http_date_str(expire_time)

