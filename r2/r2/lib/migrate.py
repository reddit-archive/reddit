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
