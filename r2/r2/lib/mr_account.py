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
export LINKDBHOST=prec01
export USER=ri
export INI=production.ini

export TIMES='("hour",)'
export INTERVAL=hour

export KIND=link
export THING=/scratch/thing-$KIND.$INTERVAL.dump
export DTHING=/scratch/data-$KIND.$INTERVAL.dump
export GOLD=/scratch/profile-$KIND.$INTERVAL.dump


cd $HOME/reddit/r2


time psql -F"\t" -A -t -d newreddit -U $USER -h $LINKDBHOST \
     -c "\\copy (select t.thing_id, 'thing', '$KIND',
                        t.ups, t.downs, t.deleted, t.spam, extract(epoch from t.date)
                   from reddit_thing_$KIND t
                  where not t.deleted
                     and t.date > now() - interval '1 $INTERVAL'
                  )
                  to '$THING'"

time psql -F"\t" -A -t -d newreddit -U $USER -h $LINKDBHOST \
     -c "\\copy (select d.value, d.thing_id, 'data', '$KIND',
                        d.key
                   from reddit_data_$KIND d, reddit_thing_$KIND t
                  where t.thing_id = d.thing_id
                    and not t.deleted
                    and (d.key = 'author_id')
                    and t.date > now() - interval '1 $INTERVAL'
                  )
                  to '$DTHING'"

time psql -F"\t" -A -t -d newreddit -U $USER -h $LINKDBHOST \
     -c "\\copy (select a.thing_id, 'data', 'account',
                        a.key, a.value
                   from reddit_data_account a
                  where a.key = 'gold' and substring(a.value, 1, 1000) = 't')
                  to '$GOLD'"
cat $GOLD $DTHING | sort -T. -S200m | paster --plugin=r2 run $INI r2/lib/mr_account.py -c "join_authors()" >> $THING
cat $THING |  sort -T. -S200m | paster --plugin=r2 run $INI r2/lib/mr_account.py -c "join_links()" | paster --plugin=r2 run $INI r2/lib/mr_account.py -c "time_listings($TIMES)" | sort -T. -S200m | paster --plugin=r2 run $INI r2/lib/mr_account.py -c "write_permacache()"

"""
import sys

from r2.models import Account, Subreddit, Link, Comment, NotFound
from r2.lib.db.sorts import epoch_seconds, score, controversy, _hot
from r2.lib.db import queries
from r2.lib import mr_tools
from r2.lib.utils import timeago, UrlParser
from r2.lib.jsontemplates import make_fullname # what a strange place
                                               # for this function
import datetime

def join_links():
    mr_tools.join_things(('author_id',))

def year_listings():
    """
    With an 'all' dump, generate the top and controversial per user per year
    """
    @mr_tools.dataspec_m_thing(('author_id', int),)
    def process(link):
        if not link.deleted:
            author_id = link.author_id
            ups = link.ups
            downs = link.downs
            sc = score(ups, downs)
            contr = controversy(ups, downs)
            if link.thing_type == 'link':
                fname = make_fullname(Link, link.thing_id)
            else:
                fname = make_fullname(Comment, link.thing_id)
            timestamp = link.timestamp
            date = datetime.datetime.utcfromtimestamp(timestamp)
            yield ('user-top-%s-%d' % (date.year, author_id),
                   sc, timestamp, fname)
            yield ('user-controversial-%s-%d' % (date.year, author_id),
                   contr, timestamp, fname)

    mr_tools.mr_map(process)



def time_listings(times = ('year','month','week','day','hour', 'all')):
    oldests = dict((t, epoch_seconds(timeago('1 %s' % t)))
                   for t in times if t != 'all')
    if 'all' in times:
        oldests['all'] = 0

    @mr_tools.dataspec_m_thing(('author_id', int),)
    def process(link):

        timestamp = link.timestamp
        if link.thing_type == 'link':
            fname = make_fullname(Link, link.thing_id)
        else:
            fname = make_fullname(Comment, link.thing_id)

        if not link.spam and not link.deleted:
            author_id = link.author_id
            ups, downs = link.ups, link.downs

            sc = score(ups, downs)
            contr = controversy(ups, downs)
            h = _hot(ups, downs, timestamp)

            for tkey, oldest in oldests.iteritems():
                if timestamp > oldest:
                    yield ('%s-top-%s-%d' % (link.thing_type, tkey, author_id),
                           sc, timestamp, fname)
                    yield ('%s-controversial-%s-%d' % (link.thing_type, tkey, author_id),
                           contr, timestamp, fname)
                    if tkey == 'all':
                        #yield ('%s-new-%s-%d' % (link.thing_type, tkey, author_id),
                        #       timestamp, timestamp, fname)
                        yield ('%s-hot-%s-%d' % (link.thing_type, tkey, author_id),
                               h, timestamp, fname)


    mr_tools.mr_map(process)

def store_keys(key, maxes):
    # we're building queries using queries.py, but we could make the
    # queries ourselves if we wanted to avoid the individual lookups
    # for accounts and subreddits.

    # Note that we're only generating the 'sr-' type queries here, but
    # we're also able to process the other listings generated by the
    # old migrate.mr_permacache for convenience

    acc_str, sort, time, account_id = key.split('-')
    account_id = int(account_id)
    fn = queries._get_submitted if key.startswith('link-') else queries._get_comments

    q = fn(account_id, sort, time)
    if time == 'all':
        if sort == 'new':
            q._insert_tuples([(item[-1], float(item[0]))
                              for item in maxes])
        else:
            q._insert_tuples([tuple([item[-1]] + map(float, item[:-1]))
                              for item in maxes])
    else:    
        q._replace([tuple([item[-1]] + map(float, item[:-1]))
                    for item in maxes])

def write_permacache(fd = sys.stdin):
    mr_tools.mr_reduce_max_per_key(lambda x: map(float, x[:-1]), num=1000,
                                   post=store_keys,
                                   fd = fd)

