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
