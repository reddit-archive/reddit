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
# All portions of the code written by CondeNet are Copyright (c) 2006-2010
# CondeNet, Inc. All Rights Reserved.
################################################################################
"""
One-time use functions to migrate from one reddit-version to another
"""
from r2.lib.promote import *

def add_allow_top_to_srs():
    "Add the allow_top property to all stored subreddits"
    from r2.models import Subreddit
    from r2.lib.db.operators import desc
    from r2.lib.utils import fetch_things2

    q = Subreddit._query(Subreddit.c._spam == (True,False),
                         sort = desc('_date'))
    for sr in fetch_things2(q):
        sr.allow_top = True; sr._commit()

def convert_promoted():
    """
    should only need to be run once to update old style promoted links
    to the new style.
    """
    from r2.lib.utils import fetch_things2
    from r2.lib import authorize

    q = Link._query(Link.c.promoted == (True, False),
                    sort = desc("_date"))
    sr_id = PromoteSR._id
    bid = 100
    with g.make_lock(promoted_lock_key):
        promoted = {}
        set_promoted({})
        for l in fetch_things2(q):
            print "updating:", l
            try:
                if not l._loaded: l._load()
                # move the promotion into the promo subreddit
                l.sr_id = sr_id
                # set it to accepted (since some of the update functions
                # check that it is not already promoted)
                l.promote_status = STATUS.accepted
                author = Account._byID(l.author_id)
                l.promote_trans_id = authorize.auth_transaction(bid, author, -1, l)
                l.promote_bid = bid
                l.maximum_clicks = None
                l.maximum_views = None
                # set the dates
                start = getattr(l, "promoted_on", l._date)
                until = getattr(l, "promote_until", None) or \
                    (l._date + timedelta(1))
                l.promote_until = None
                update_promo_dates(l, start, until)
                # mark it as promoted if it was promoted when we got there
                if l.promoted and l.promote_until > datetime.now(g.tz):
                    l.promote_status = STATUS.pending
                else:
                    l.promote_status = STATUS.finished
    
                if not hasattr(l, "disable_comments"):
                    l.disable_comments = False
                # add it to the auction list
                if l.promote_status == STATUS.pending and l._fullname not in promoted:
                    promoted[l._fullname] = auction_weight(l)
                l._commit()
            except AttributeError:
                print "BAD THING:", l
        print promoted
        set_promoted(promoted)
    # run what is normally in a cron job to clear out finished promos
    #promote_promoted()

def store_market():

    """
    create index ix_promote_date_actual_end on promote_date(actual_end);
    create index ix_promote_date_actual_start on promote_date(actual_start);
    create index ix_promote_date_start_date on promote_date(start_date);
    create index ix_promote_date_end_date on promote_date(end_date);

    alter table promote_date add column account_id bigint;
    create index ix_promote_date_account_id on promote_date(account_id);
    alter table promote_date add column bid real;
    alter table promote_date add column refund real;

    """

    for p in PromoteDates.query().all():
        l = Link._by_fullname(p.thing_name, True)
        if hasattr(l, "promote_bid") and hasattr(l, "author_id"):
            p.account_id = l.author_id
            p._commit()
            PromoteDates.update(l, l._date, l.promote_until)
            PromoteDates.update_bid(l)

def subscribe_to_blog_and_annoucements(filename):
    import re
    from time import sleep
    from r2.models import Account, Subreddit

    r_blog = Subreddit._by_name("blog")
    r_announcements = Subreddit._by_name("announcements")

    contents = file(filename).read()
    numbers = [ int(s) for s in re.findall("\d+", contents) ]

#    d = Account._byID(numbers, data=True)

#   for i, account in enumerate(d.values()):
    for i, account_id in enumerate(numbers):
        account = Account._byID(account_id, data=True)

        for sr in r_blog, r_announcements:
            if sr.add_subscriber(account):
                sr._incr("_ups", 1)
                print ("%d: subscribed %s to %s" % (i, account.name, sr.name))
            else:
                print ("%d: didn't subscribe %s to %s" % (i, account.name, sr.name))


def upgrade_messages(update_comments = True, update_messages = True,
                     update_trees = True):
    from r2.lib.db import queries
    from r2.lib import comment_tree, cache
    from r2.models import Account
    from pylons import g
    accounts = set()

    def batch_fn(items):
        g.reset_caches()
        return items
    
    if update_messages or update_trees:
        q = Message._query(Message.c.new == True,
                           sort = desc("_date"),
                           data = True)
        for m in fetch_things2(q, batch_fn = batch_fn):
            print m,m._date
            if update_messages:
                accounts = accounts | queries.set_unread(m, m.new)
            else:
                accounts.add(m.to_id)
    if update_comments:
        q = Comment._query(Comment.c.new == True,
                           sort = desc("_date"))
        q._filter(Comment.c._id < 26152162676)

        for m in fetch_things2(q, batch_fn = batch_fn):
            print m,m._date
            queries.set_unread(m, True)

    print "Precomputing comment trees for %d accounts" % len(accounts)

    for i, a in enumerate(accounts):
        if not isinstance(a, Account):
            a = Account._byID(a)
        print i, a
        comment_tree.user_messages(a)

def recompute_unread(min_date = None):
    from r2.models import Inbox, Account, Comment, Message
    from r2.lib.db import queries

    def load_accounts(inbox_rel):
        accounts = set()
        q = inbox_rel._query(eager_load = False, data = False,
                             sort = desc("_date"))
        if min_date:
            q._filter(inbox_rel.c._date > min_date)

        for i in fetch_things2(q):
            accounts.add(i._thing1_id)

        return accounts

    accounts_m = load_accounts(Inbox.rel(Account, Message))
    for i, a in enumerate(accounts_m):
        a = Account._byID(a)
        print "%s / %s : %s" % (i, len(accounts_m), a)
        queries.get_unread_messages(a).update()
        queries.get_unread_comments(a).update()
        queries.get_unread_selfreply(a).update()

    accounts = load_accounts(Inbox.rel(Account, Comment)) - accounts_m
    for i, a in enumerate(accounts):
        a = Account._byID(a)
        print "%s / %s : %s" % (i, len(accounts), a)
        queries.get_unread_comments(a).update()
        queries.get_unread_selfreply(a).update()

def pushup_permacache(verbosity=1000):
    """When putting cassandra into the permacache chain, we need to
       push everything up into the rest of the chain, so this is
       everything that uses the permacache, as of that check-in."""
    from pylons import g
    from r2.models import Link, Subreddit, Account
    from r2.lib.db.operators import desc
    from r2.lib.comment_tree import comments_key, messages_key
    from r2.lib.utils import fetch_things2, in_chunks
    from r2.lib.utils import last_modified_key
    from r2.lib.promote import promoted_memo_key
    from r2.lib.subreddit_search import load_all_reddits
    from r2.lib.db import queries
    from r2.lib.cache import CassandraCacheChain

    authority = g.permacache.caches[-1]
    nonauthority = CassandraCacheChain(g.permacache.caches[1:-1])

    def populate(keys):
        vals = authority.simple_get_multi(keys)
        if vals:
            nonauthority.set_multi(vals)

    def gen_keys():
        yield promoted_memo_key

        # just let this one do its own writing
        load_all_reddits()

        yield queries.get_all_comments().iden

        l_q = Link._query(Link.c._spam == (True, False),
                          Link.c._deleted == (True, False),
                          sort=desc('_date'),
                          data=True,
                          )
        for link in fetch_things2(l_q, verbosity):
            yield comments_key(link._id)
            yield last_modified_key(link, 'comments')
            if not getattr(link, 'is_self', False) and hasattr(link, 'url'):
                yield Link.by_url_key(link.url)

        a_q = Account._query(Account.c._spam == (True, False),
                             sort=desc('_date'),
                             )
        for account in fetch_things2(a_q, verbosity):
            yield messages_key(account._id)
            yield last_modified_key(account, 'overview')
            yield last_modified_key(account, 'commented')
            yield last_modified_key(account, 'submitted')
            yield last_modified_key(account, 'liked')
            yield last_modified_key(account, 'disliked')
            yield queries.get_comments(account, 'new', 'all').iden
            yield queries.get_submitted(account, 'new', 'all').iden
            yield queries.get_liked(account).iden
            yield queries.get_disliked(account).iden
            yield queries.get_hidden(account).iden
            yield queries.get_saved(account).iden
            yield queries.get_inbox_messages(account).iden
            yield queries.get_unread_messages(account).iden
            yield queries.get_inbox_comments(account).iden
            yield queries.get_unread_comments(account).iden
            yield queries.get_inbox_selfreply(account).iden
            yield queries.get_unread_selfreply(account).iden
            yield queries.get_sent(account).iden

        sr_q = Subreddit._query(Subreddit.c._spam == (True, False),
                                sort=desc('_date'),
                                )
        for sr in fetch_things2(sr_q, verbosity):
            yield last_modified_key(sr, 'stylesheet_contents')
            yield queries.get_links(sr, 'hot', 'all').iden
            yield queries.get_links(sr, 'new', 'all').iden

            for sort in 'top', 'controversial':
                for time in 'hour', 'day', 'week', 'month', 'year', 'all':
                    yield queries.get_links(sr, sort, time,
                                            merge_batched=False).iden
            yield queries.get_spam_links(sr).iden
            yield queries.get_spam_comments(sr).iden
            yield queries.get_reported_links(sr).iden
            yield queries.get_reported_comments(sr).iden
            yield queries.get_subreddit_messages(sr).iden
            yield queries.get_unread_subreddit_messages(sr).iden

    done = 0
    for keys in in_chunks(gen_keys(), verbosity):
        g.reset_caches()
        done += len(keys)
        print 'Done %d: %r' % (done, keys[-1])
        populate(keys)

def add_byurl_prefix():
    """Run one before the byurl prefix is set, and once after (killing
       it after it gets when it started the first time"""

    from datetime import datetime
    from r2.models import Link
    from r2.lib.filters import _force_utf8
    from pylons import g
    from r2.lib.utils import fetch_things2
    from r2.lib.db.operators import desc
    from r2.lib.utils import base_url

    now = datetime.now(g.tz)
    print 'started at %s' % (now,)

    l_q = Link._query(
        Link.c._date < now,
        data=True,
        sort=desc('_date'))

    # from link.py
    def by_url_key(url, prefix=''):
        s = _force_utf8(base_url(url.lower()))
        return '%s%s' % (prefix, s)

    done = 0
    for links in fetch_things2(l_q, 1000, chunks=True):
        done += len(links)
        print 'Doing: %r, %s..%s' % (done, links[-1]._date, links[0]._date)

        # only links with actual URLs
        links = filter(lambda link: (not getattr(link, 'is_self', False)
                                     and getattr(link, 'url', '')),
                       links)

        # old key -> new key
        translate = dict((by_url_key(link.url),
                          by_url_key(link.url, prefix='byurl_'))
                         for link in links)

        old = g.permacache.get_multi(translate.keys())
        new = dict((translate[old_key], value)
                   for (old_key, value)
                   in old.iteritems())
        g.permacache.set_multi(new)

def _progress(it, verbosity=100, key=repr, estimate=None, persec=False):
    """An iterator that yields everything from `it', but prints progress
       information along the way, including time-estimates if
       possible"""
    from datetime import datetime
    import sys

    now = start = datetime.now()
    elapsed = start - start

    print 'Starting at %s' % (start,)

    seen = 0
    for item in it:
        seen += 1
        if seen % verbosity == 0:
            now = datetime.now()
            elapsed = now - start
            elapsed_seconds = elapsed.days * 86400 + elapsed.seconds

            if estimate:
                remaining = ((elapsed/seen)*estimate)-elapsed
                completion = now + remaining
                count_str = ('%d/%d %.2f%%'
                             % (seen, estimate, float(seen)/estimate*100))
                estimate_str = (' (%s remaining; completion %s)'
                                % (remaining, completion))
            else:
                count_str = '%d' % seen
                estimate_str = ''

            if key:
                key_str = ': %s' % key(item)
            else:
                key_str = ''

            if persec and elapsed_seconds > 0:
                persec_str = ' (%.2f/s)' % (seen/elapsed_seconds,)
            else:
                persec_str = ''
                
            sys.stdout.write('%s%s, %s%s%s\n'
                             % (count_str, persec_str,
                                elapsed, estimate_str, key_str))
            sys.stdout.flush()
            this_chunk = 0
        yield item

    now = datetime.now()
    elapsed = now - start
    print 'Processed %d items in %s..%s (%s)' % (seen, start, now, elapsed)

def shorten_byurl_keys():
    """We changed by_url keys from a format like
           byurl_google.com...
       to:
           byurl(1d5920f4b44b27a802bd77c4f0536f5a, google.com...)
       so that they would fit in memcache's 251-char limit
    """

    from datetime import datetime
    from hashlib import md5
    from r2.models import Link
    from r2.lib.filters import _force_utf8
    from pylons import g
    from r2.lib.utils import fetch_things2, in_chunks
    from r2.lib.db.operators import desc
    from r2.lib.utils import base_url

    # from link.py
    def old_by_url_key(url):
        prefix='byurl_'
        s = _force_utf8(base_url(url.lower()))
        return '%s%s' % (prefix, s)
    def new_by_url_key(url):
        maxlen = 250
        template = 'byurl(%s,%s)'
        keyurl = _force_utf8(base_url(url.lower()))
        hexdigest = md5(keyurl).hexdigest()
        usable_len = maxlen-len(template)-len(hexdigest)
        return template % (hexdigest, keyurl[:usable_len])

    verbosity = 1000

    l_q = Link._query(
        Link.c._spam == (True, False),
        data=True,
        sort=desc('_date'))
    for links in (
        in_chunks(
            _progress(
                fetch_things2(l_q, verbosity),
                key = lambda link: link._date,
                verbosity=verbosity,
                estimate=int(9.9e6),
                persec=True,
                ),
            verbosity)):
        # only links with actual URLs
        links = filter(lambda link: (not getattr(link, 'is_self', False)
                                     and getattr(link, 'url', '')),
                       links)

        # old key -> new key
        translate = dict((old_by_url_key(link.url),
                          new_by_url_key(link.url))
                         for link in links)

        old = g.permacache.get_multi(translate.keys())
        new = dict((translate[old_key], value)
                   for (old_key, value)
                   in old.iteritems())
        g.permacache.set_multi(new)
