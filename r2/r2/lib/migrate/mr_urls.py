"""
export LINKDBHOST=prec01
export USER=ri
export INI=production.ini
cd ~/reddit/r2
time psql -F"\t" -A -t -d newreddit -U $USER -h $LINKDBHOST \
     -c "\\copy (select t.thing_id, 'thing', 'link',
                        t.ups, t.downs, t.deleted, t.spam, extract(epoch from t.date)
                   from reddit_thing_link t
                  where not t.spam and not t.deleted
                  )
                  to '/scratch/reddit_thing_link.dump'"
time psql -F"\t" -A -t -d newreddit -U $USER -h $LINKDBHOST \
     -c "\\copy (select d.thing_id, 'data', 'link',
                        d.key, d.value
                   from reddit_data_link d
                  where d.key = 'url' ) to '/scratch/reddit_data_link.dump'"
cat /scratch/reddit_data_link.dump /scratch/reddit_thing_link.dump | sort -T. -S200m | paster --plugin=r2 run $INI r2/lib/migrate/mr_urls.py -c "join_links()" > /scratch/links.joined
cat /scratch/links.joined | paster --plugin=r2 run $INI r2/lib/migrate/mr_urls.py -c "time_listings()" | sort -T. -S200m | paster --plugin=r2 run $INI r2/lib/migrate/mr_urls.py -c "write_permacache()"
"""

import sys
from pylons import g

from r2.models import Account, Subreddit, Link
from r2.lib import mr_tools

def join_links():
    mr_tools.join_things(('url',))

def listings():
    @mr_tools.dataspec_m_thing(("url", str),)
    def process(link):
        if link.url:
            yield (Link.by_url_key_new(link.url), link.timestamp,
                   link.thing_id)

    mr_tools.mr_map(process)


def store_keys(key, maxes):
    if key.startswith('byurl'):
        r = set(g.urlcache_new.get(key) or [])
        new = set(int(x[-1]) for x in maxes)
        r.update(new)
        g.urlcache_new.set(key, list(sorted(r)))

def write_permacache(fd = sys.stdin):
    mr_tools.mr_reduce_max_per_key(lambda x: map(float, x[:-1]), num=1000,
                                   post=store_keys,
                                   fd = fd)
