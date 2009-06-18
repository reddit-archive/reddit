from r2.models import *
from r2.lib import utils

from pylons import g

sr_prefix = 'sr_search_'


def load_all_reddits():
    query_cache = {}

    q = Subreddit._query(Subreddit.c.type == 'public',
                         Subreddit.c._downs > 1,
                         sort = (desc('_downs'), desc('_ups')),
                         data = True)
    for sr in utils.fetch_things2(q):
        name = sr.name.lower()
        for i in xrange(len(name)):
            prefix = name[:i + 1]
            names = query_cache.setdefault(prefix, [])
            if len(names) < 10:
                names.append(sr.name)

    g.rendercache.set_multi(query_cache, prefix = sr_prefix)

def search_reddits_cached(query):
    return g.rendercache.get(sr_prefix + query) or []

def search_reddits(query):
    return search_reddits_cached(str(query.lower()))

@memoize('popular_searches', time = 3600)
def popular_searches():
    top_reddits = Subreddit._query(Subreddit.c.type == 'public',
                                   sort = desc('_downs'),
                                   limit = 100,
                                   data = True)
    top_searches = {}
    for sr in top_reddits:
        name = sr.name.lower()
        for i in xrange(min(len(name), 3)):
            query = name[:i + 1]
            r = search_reddits(query)
            top_searches[query] = r
    return top_searches

