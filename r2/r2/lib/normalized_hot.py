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

from pylons import g

from r2.lib.memoize import memoize
from r2.lib import _normalized_hot

from r2.lib._normalized_hot import get_hot # pull this into our namespace

@memoize('normalize_hot', time = g.page_cache_time)
def normalized_hot_cached(sr_ids, obey_age_limit=True):
    return _normalized_hot.normalized_hot_cached(sr_ids, obey_age_limit)

def l(li):
    if isinstance(li, list):
        return li
    else:
        return list(li)

def normalized_hot(sr_ids, obey_age_limit=True):
    sr_ids = l(sorted(sr_ids))
    return normalized_hot_cached(sr_ids, obey_age_limit) if sr_ids else ()
