"""
Try to regenerate the permacache items devoted to listings after a
storage failure in Cassandra
"""

"""
cat > mr_permacache <<HERE
#!/bin/sh
cd ~/reddit/r2
paster run staging.ini ./mr_permacache.py -c "\$1"
HERE
chmod u+x mr_permacache

LINKDBHOST=prec01
COMMENTDBHOST=db02s1
VOTEDBHOST=db03s1
SAVEHIDEDBHOST=db01s1

## links
time psql -F"\t" -A -t -d newreddit -U ri -h $LINKDBHOST \
     -c "\\copy (select t.thing_id, 'thing', 'link',
                        t.ups, t.downs, t.deleted, t.spam, extract(epoch from t.date)
                   from reddit_thing_link t) to 'reddit_thing_link.dump'"
time psql -F"\t" -A -t -d newreddit -U ri -h $LINKDBHOST \
     -c "\\copy (select d.thing_id, 'data', 'link',
                        d.key, d.value
                   from reddit_data_link d
                  where d.key = 'author_id' or d.key = 'sr_id') to 'reddit_data_link.dump'"
pv reddit_data_link.dump reddit_thing_link.dump | sort -T. -S200m | ./mr_permacache "join_links()" > links.joined
pv links.joined | ./mr_permacache "link_listings()" | sort -T. -S200m > links.listings

## comments
psql -F"\t" -A -t -d newreddit -U ri -h $COMMENTDBHOST \
     -c "\\copy (select t.thing_id, 'thing', 'comment',
                        t.ups, t.downs, t.deleted, t.spam, extract(epoch from t.date)
                   from reddit_thing_comment t) to 'reddit_thing_comment.dump'"
psql -F"\t" -A -t -d newreddit -U ri -h $COMMENTDBHOST \
     -c "\\copy (select d.thing_id, 'data', 'comment',
                        d.key, d.value
                   from reddit_data_comment d
                  where d.key = 'author_id') to 'reddit_data_comment.dump'"
cat reddit_data_comment.dump reddit_thing_comment.dump | sort -T. -S200m | ./mr_permacache "join_comments()" > comments.joined
cat links.joined | ./mr_permacache "comment_listings()" | sort -T. -S200m > comments.listings

## linkvotes
psql -F"\t" -A -t -d newreddit -U ri -h $VOTEDBHOST \
     -c "\\copy (select r.rel_id, 'vote_account_link',
                        r.thing1_id, r.thing2_id, r.name, extract(epoch from r.date)
                   from reddit_rel_vote_account_link r) to 'reddit_linkvote.dump'"
pv reddit_linkvote.dump | ./mr_permacache "linkvote_listings()" | sort -T. -S200m > linkvotes.listings

#savehide
psql -F"\t" -A -t -d newreddit -U ri -h $VOTEDBHOST \
     -c "\\copy (select r.rel_id, 'savehide',
                        r.thing1_id, r.thing2_id, r.name, extract(epoch from r.date)
                   from reddit_rel_savehide r) to 'reddit_savehide.dump'"
pv reddit_savehide.dump | ./mr_permacache "savehide_listings()" | sort -T. -S200m > savehide.listings

## load them up
# the individual .listings files are sorted so even if it's not sorted
# overall we don't need to re-sort them
mkdir listings
pv *.listings | ./mr_permacache "top1k_writefiles('listings')"
./mr_permacache "write_permacache_from_dir('$PWD/listings')"

"""

import os
import sys
import itertools

from r2.lib import mr_tools
from r2.lib.mr_tools import dataspec_m_thing, dataspec_m_rel, join_things


from dateutil.parser import parse as parse_timestamp

from r2.models import *
from r2.lib.db.sorts import epoch_seconds, score, controversy, _hot
from r2.lib.utils import fetch_things2, in_chunks, progress, UniqueIterator
from r2.lib import comment_tree
from r2.lib.db import queries

from r2.lib.jsontemplates import make_fullname # what a strange place
                                               # for this function

def join_links():
    join_things(('author_id', 'sr_id'))

def link_listings():
    @dataspec_m_thing(('author_id', int),
                      ('sr_id', int))
    def process(link):
        assert link.thing_type == 'link'

        author_id = link.author_id
        timestamp = link.timestamp
        fname = make_fullname(Link, link.thing_id)

        yield 'user-submitted-%d' % author_id, timestamp, fname
        if not link.spam:
            sr_id = link.sr_id
            ups, downs = link.ups, link.downs

            yield ('sr-hot-all-%d' % sr_id, _hot(ups, downs, timestamp),
                   timestamp, fname)
            yield 'sr-new-all-%d' % sr_id, timestamp, fname
            yield 'sr-top-all-%d' % sr_id, score(ups, downs), timestamp, fname
            yield ('sr-controversial-all-%d' % sr_id,
                   controversy(ups, downs), timestamp, fname)
            for time in '1 year', '1 month', '1 week', '1 day', '1 hour':
                if timestamp > epoch_seconds(timeago(time)):
                    tkey = time.split(' ')[1]
                    yield ('sr-top-%s-%d' % (tkey, sr_id),
                           score(ups, downs), timestamp, fname)
                    yield ('sr-controversial-%s-%d' % (tkey, sr_id),
                           controversy(ups, downs),
                           timestamp, fname)

    mr_tools.mr_map(process)

def join_comments():
    join_things(('author_id',))

def comment_listings():
    @dataspec_m_thing(('author_id', int),)
    def process(comment):
        assert comment.thing_type == 'comment'

        yield ('user-commented-%d' % comment.author_id,
               comment.timestamp, make_fullname(Comment, comment.thing_id))

    mr_tools.mr_map(process)

def rel_listings(names, thing2_cls = Link):
    # names examples: {'1': 'liked',
    #                  '-1': 'disliked'}
    @dataspec_m_rel()
    def process(rel):
        if rel.name in names:
            yield ('%s-%s' % (names[rel.name], rel.thing1_id), rel.timestamp,
                   make_fullname(thing2_cls, rel.thing2_id))
    mr_tools.mr_map(process)

def linkvote_listings():
    rel_listings({'1': 'liked',
                  '-1': 'disliked'})

def savehide_listings():
    rel_listings({'save': 'saved',
                  'hide': 'hidden'})

def insert_to_query(q, items):
    q._insert_tuples(items)

def store_keys(key, maxes):
    # we're building queries from queries.py, but we could avoid this
    # by making the queries ourselves if we wanted to avoid the
    # individual lookups for accounts and subreddits
    userrel_fns = dict(liked = queries.get_liked,
                       disliked = queries.get_disliked,
                       saved = queries.get_saved,
                       hidden = queries.get_hidden)
    if key.startswith('user-'):
        acc_str, keytype, account_id = key.split('-')
        account_id = int(account_id)
        fn = queries.get_submitted if keytype == 'submitted' else queries.get_comments
        q = fn(Account._byID(account_id), 'new', 'all')
        insert_to_query(q, [(fname, float(timestamp))
                            for (timestamp, fname)
                            in maxes ])
    elif key.startswith('sr-'):
        sr_str, sort, time, sr_id = key.split('-')
        sr_id = int(sr_id)

        if sort == 'controversy':
            # I screwed this up in the mapper and it's too late to fix
            # it
            sort = 'controversial'

        q = queries.get_links(Subreddit._byID(sr_id), sort, time)
        insert_to_query(q, [tuple([item[-1]] + map(float, item[:-1]))
                            for item in maxes])

    elif key.split('-')[0] in userrel_fns:
        key_type, account_id = key.split('-')
        account_id = int(account_id)
        fn = userrel_fns[key_type]
        q = fn(Account._byID(account_id))
        insert_to_query(q, [tuple([item[-1]] + map(float, item[:-1]))
                            for item in maxes])

def top1k_writefiles(dirname):
    """Divide up the top 1k of each key into its own file to make
       restarting after a failure much easier"""
    def post(key, maxes):
        with open(os.path.join(dirname, key), 'w') as f:
            for item in maxes:
                f.write('%s\t' % key)
                f.write('\t'.join(item))
                f.write('\n')
        
    mr_tools.mr_reduce_max_per_key(lambda x: map(float, x[:-1]), num=1000,
                                   post=post)

def top1k_writepermacache(fd = sys.stdin):
    mr_tools.mr_reduce_max_per_key(lambda x: map(float, x[:-1]), num=1000,
                                   post=store_keys,
                                   fd = fd)

def write_permacache_from_dir(dirname):
    for fname in progress(os.listdir(dirname), persec=True):
        try:
            fpath = os.path.join(dirname, fname)
            write_permacache_from_file(fpath)
            os.unlink(fpath)
        except:
            mr_tools.status('failed on %r' % fname)
            raise

def write_permacache_from_file(fname):
    with open(fname) as fd:
        top1k_writepermacache(fd = fd)
