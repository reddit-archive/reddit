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
# All portions of the code written by CondeNet are Copyright (c) 2006-2008
# CondeNet, Inc. All Rights Reserved.
################################################################################

from datetime import datetime
import time, md5

import simplejson

from r2.lib.utils import rfc3339_date_str, http_date_str, to36
from r2.lib.memoize import memoize
from pylons import g, c

SUP_PERIOD = 60

def cur_time(period):
    t = int(time.time())
    return t - t % period

def last_time(period):
    return cur_time(period) - period

def make_sup_id(user, action):
    sup_id = md5.new(user.name + action).hexdigest()
    #cause cool kids only use part of the hash
    return sup_id[:10]

def add_update(user, action):
    update_time = to36(int(time.time()))
    sup_id = make_sup_id(user, action)
    sup_update = ',%s:%s' % (sup_id, update_time)

    key = str(cur_time(SUP_PERIOD))
    g.cache.add(key, '', time = SUP_PERIOD * 3)
    g.cache.append(key, sup_update)

@memoize('set_sup_header', time = SUP_PERIOD)
def sup_json_cached(lt):
    update_time = datetime.utcnow()
    since_time = datetime.utcfromtimestamp(lt)

    updates = g.cache.get(str(lt))
    sup_updates = []
    if updates:
        sup_updates = [u.split(':') for u in updates.split(',') if u]

    json = simplejson.dumps({'updated_time' : rfc3339_date_str(update_time),
                             'since_time' : rfc3339_date_str(since_time),
                             'period' : SUP_PERIOD,
                             'updates' : sup_updates})
    return json

def sup_json():
    return sup_json_cached(last_time(SUP_PERIOD))

def set_sup_header(user, action):
    sup_id = make_sup_id(user, action)

    if g.domain_prefix:
        domain = g.domain_prefix + '.' + g.domain
    else:
        domain = g.domain

    c.response.headers['x-sup-id'] = 'http://%s/sup.json#%s' % (domain, sup_id)

def set_expires_header():
    seconds = cur_time(SUP_PERIOD) + SUP_PERIOD
    expire_time = datetime.fromtimestamp(seconds, g.tz)
    c.response.headers['expires'] = http_date_str(expire_time)
