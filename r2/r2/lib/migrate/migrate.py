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

# alter table bids DROP constraint bids_pkey;
# alter table bids add column campaign integer;
# update bids set campaign = 0;
# alter table bids ADD primary key (transaction, campaign);
def promote_v2():
    # alter table bids add column campaign integer;
    # update bids set campaign = 0; 
    from r2.models import Link, NotFound, PromoteDates, Bid
    from datetime import datetime
    from pylons import g
    for p in PromoteDates.query():
        try:
            l = Link._by_fullname(p.thing_name,
                                  data = True, return_dict = False)
            if not l:
                raise NotFound, p.thing_name

            # update the promote status
            l.promoted = True
            l.promote_status = getattr(l, "promote_status", STATUS.unseen)
            l._date = datetime(*(list(p.start_date.timetuple()[:7]) + [g.tz]))
            set_status(l, l.promote_status)

            # add new campaign
            print (l, (p.start_date, p.end_date), p.bid, None)
            if not p.bid:
                print "no bid? ", l
                p.bid = 20
            new_campaign(l, (p.start_date, p.end_date), p.bid, None)
            print "updated: %s (%s)" % (l, l._date)

        except NotFound:
            print "NotFound: %s" % p.thing_name

    print "updating campaigns"
    for b in Bid.query():
        l = Link._byID(int(b.thing_id))
        print "updating: ", l
        campaigns = getattr(l, "campaigns", {}).copy()
        indx = b.campaign
        if indx in campaigns:
            sd, ed, bid, sr, trans_id = campaigns[indx]
            campaigns[indx] = sd, ed, bid, sr, b.transaction
            l.campaigns = campaigns
            l._commit()
        else:
            print "no campaign information: ", l


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
    from r2.lib.utils import base_url, progress

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
            progress(
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

def prime_url_cache(f, verbosity = 10000):
    import gzip, time
    from pylons import g
    handle = gzip.open(f, 'rb')
    counter = 0
    start_time = time.time()
    for line in handle:
        try:
            tid, key, url, kind = line.split('|')
            tid = int(tid)
            if url.lower() != "self":
                key = Link.by_url_key_new(url)
                link_ids = g.urlcache.get(key) or []
                if tid not in link_ids:
                    link_ids.append(tid)
                    g.urlcache.set(key, link_ids)
        except ValueError:
            print "FAIL: %s" % line
        counter += 1
        if counter % verbosity == 0:
            print "%6d: %s" % (counter, line)
            print "--> doing %5.2f / s" % (float(counter) / (time.time() - start_time))
