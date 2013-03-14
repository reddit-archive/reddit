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

"""
Generate the data for the listings for the time-based Subreddit
queries. The format is eventually that of the CachedResults objects
used by r2.lib.db.queries (with some intermediate steps), so changes
there may warrant changes here
"""

# to run:
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
                     and t.date > now() - interval '1 year'
                  )
                  to 'reddit_thing_link.dump'"
time psql -F"\t" -A -t -d newreddit -U $USER -h $LINKDBHOST \
     -c "\\copy (select d.thing_id, 'data', 'link',
                        d.key, d.value
                   from reddit_data_link d, reddit_thing_link t
                  where t.thing_id = d.thing_id
                    and not t.spam and not t.deleted
                    and (d.key = 'url' or d.key = 'sr_id')
                    and t.date > now() - interval '1 year'
                  )
                  to 'reddit_data_link.dump'"
cat reddit_data_link.dump reddit_thing_link.dump | sort -T. -S200m | paster --plugin=r2 run $INI r2/lib/mr_top.py -c "join_links()" > links.joined
cat links.joined | paster --plugin=r2 run $INI r2/lib/mr_top.py -c "time_listings()" | sort -T. -S200m | paster --plugin=r2 run $INI r2/lib/mr_top.py -c "write_permacache()"
"""
## """
## psql -F"\t" -A -t -d newreddit -U ri -h $LINKDBHOST \
##     -c "\\copy (select t.thing_id,
##                        'link',
##                        t.ups,
##                        t.downs,
##                        t.deleted,
##                        t.spam,
##                        extract(epoch from t.date),
##                        d.value
##                   from reddit_thing_link t,
##                        reddit_data_link d
##                  where t.thing_id = d.thing_id
##                    and not t.spam and not t.deleted
##                    and d.key = 'sr_id'
##                    and t.date > now() - interval '1 year'
##                ) to 'links.year.joined'"
## cat links.year.joined | paster --plugin=r2 run production.ini r2/lib/mr_top.py -c "time_listings()" \
##  | sort -T. -S200mW \
##  | paster --plugin=r2 run production.ini r2/lib/mr_top.py -c "write_permacache()"
## """

# that can be run with s/year/hour/g and
# s/time_listings/time_listings(('hour',))/ for a much faster version
# that just does the hour listings. Usually these jobs dump the thing
# and data tables separately and join them with mr_tools.join_things,
# but some quick profiling shows that getting postgres to do the
# joining is ever-so-slightly-faster, so we have the above dump make
# it in the same format the join_things would normally produce

# Known bug: if a given listing hasn't had a submission in the
# allotted time (e.g. the year listing in a subreddit that hasn't had
# a submission in the last year), we won't write out an empty
# list. I'll call it a feature.

import sys

from r2.models import Account, Subreddit, Link
from r2.lib.db.sorts import epoch_seconds, score, controversy
from r2.lib.db import queries
from r2.lib import mr_tools
from r2.lib.utils import timeago, UrlParser
from r2.lib.jsontemplates import make_fullname # what a strange place
                                               # for this function

def join_links():
    mr_tools.join_things(('url', 'sr_id'))


def time_listings(times = ('year','month','week','day','hour')):
    oldests = dict((t, epoch_seconds(timeago('1 %s' % t)))
                   for t in times)

    @mr_tools.dataspec_m_thing(("url", str),('sr_id', int),)
    def process(link):
        assert link.thing_type == 'link'

        timestamp = link.timestamp
        fname = make_fullname(Link, link.thing_id)

        if not link.spam and not link.deleted:
            sr_id = link.sr_id
            if link.url:
                domains = UrlParser(link.url).domain_permutations()
            else:
                domains = []
            ups, downs = link.ups, link.downs

            for tkey, oldest in oldests.iteritems():
                if timestamp > oldest:
                    sc = score(ups, downs)
                    contr = controversy(ups, downs)
                    yield ('sr-top-%s-%d' % (tkey, sr_id),
                           sc, timestamp, fname)
                    yield ('sr-controversial-%s-%d' % (tkey, sr_id),
                           contr, timestamp, fname)
                    for domain in domains:
                        yield ('domain/top/%s/%s' % (tkey, domain),
                               sc, timestamp, fname)
                        yield ('domain/controversial/%s/%s' % (tkey, domain),
                               contr, timestamp, fname)

    mr_tools.mr_map(process)

def store_keys(key, maxes):
    # we're building queries using queries.py, but we could make the
    # queries ourselves if we wanted to avoid the individual lookups
    # for accounts and subreddits.

    # Note that we're only generating the 'sr-' type queries here, but
    # we're also able to process the other listings generated by the
    # old migrate.mr_permacache for convenience

    userrel_fns = dict(liked = queries.get_liked,
                       disliked = queries.get_disliked,
                       saved = queries.get_saved,
                       hidden = queries.get_hidden)

    if key.startswith('user-'):
        acc_str, keytype, account_id = key.split('-')
        account_id = int(account_id)
        fn = queries._get_submitted if keytype == 'submitted' else queries._get_comments
        q = fn(account_id, 'new', 'all')
        q._replace([(fname, float(timestamp))
                    for (timestamp, fname)
                    in maxes])

    elif key.startswith('sr-'):
        sr_str, sort, time, sr_id = key.split('-')
        sr_id = int(sr_id)

        if sort == 'controversy':
            # I screwed this up in the mapper and it's too late to fix
            # it
            sort = 'controversial'

        q = queries._get_links(sr_id, sort, time)
        q._replace([tuple([item[-1]] + map(float, item[:-1]))
                    for item in maxes])
    elif key.startswith('domain/'):
        d_str, sort, time, domain = key.split('/')
        q = queries.get_domain_links(domain, sort, time)
        q._replace([tuple([item[-1]] + map(float, item[:-1]))
                    for item in maxes])


    elif key.split('-')[0] in userrel_fns:
        key_type, account_id = key.split('-')
        account_id = int(account_id)
        fn = userrel_fns[key_type]
        q = fn(Account._byID(account_id))
        q._replace([tuple([item[-1]] + map(float, item[:-1]))
                    for item in maxes])

def write_permacache(fd = sys.stdin):
    mr_tools.mr_reduce_max_per_key(lambda x: map(float, x[:-1]), num=1000,
                                   post=store_keys,
                                   fd = fd)
