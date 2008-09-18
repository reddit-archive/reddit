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
# All portions of the code written by CondeNet are Copyright (c) 2006-2008
# CondeNet, Inc. All Rights Reserved.
################################################################################
from r2.models import *
from r2.lib.memoize import memoize, clear_memo
from r2.lib.normalized_hot import get_hot, only_recent
from r2.lib import count
from r2.lib.utils import UniqueIterator, timeago, timefromnow
from r2.lib.db.operators import desc

import random
from datetime import datetime

from pylons import g

# lifetime in seconds of organic listing in memcached
organic_lifetime = 5*60
promoted_memo_key = 'cached_promoted_links'

def keep_link(link):
    return not any((link.likes != None,
                    link.saved,
                    link.clicked,
                    link.hidden))

def promote(thing, subscribers_only = False):
    thing.promoted = True
    thing.promoted_on = datetime.now(g.tz)
    thing.promote_until = timefromnow("1 day")
    if subscribers_only:
        thing.promoted_subscribersonly = True
    thing._commit()
    clear_memo(promoted_memo_key)

def unpromote(thing):
    thing.promoted = False
    thing.unpromoted_on = datetime.now(g.tz)
    thing._commit()
    clear_memo(promoted_memo_key)

def clean_promoted():
    """
    Remove any stale promoted entries (should be run periodically to
    keep the list small)
    """
    p = get_promoted()
    for x in p:
        if datetime.now(g.tz) > x.promote_until:
            unpromote(x)
    clear_memo(promoted_memo_key)

@memoize(promoted_memo_key, time = organic_lifetime)
def get_promoted():
    return [ x for x in Link._query(Link.c.promoted == True,
                                    sort = desc('_date'),
                                    data = True)
             if  x.promote_until > datetime.now(g.tz) ]

def insert_promoted(link_names, subscribed_reddits):
    """
    The oldest promoted link that c.user hasn't seen yet, and sets the
    timestamp for their seen promotions in their cookie
    """
    promoted_items = get_promoted()

    if not promoted_items:
        return

    def my_keepfn(l):
        if l.promoted_subscribersonly and l.sr_id not in subscribed_reddits:
            return False
        else:
            return keep_link(l)

    # remove any that the user has acted on
    builder = IDBuilder([ x._fullname for x in promoted_items ],
                        skip = True, keep_fn = my_keepfn)
    promoted_items = builder.get_items()[0]

    # in the future, we may want to weight this sorting somehow
    random.shuffle(promoted_items)

    if not promoted_items:
        return

    every_n = 5

    # don't insert one at the head of the list 50% of the time for
    # logged in users, and 50% of the time for logged-off users when
    # the pool of promoted links is less than 3
    if c.user_is_loggedin or len(promoted_items) < 3:
        skip_first = random.choice((True,False))
    else:
        skip_first = False

    # insert one promoted item for every N items
    for i, item in enumerate(promoted_items):
        pos = i * every_n
        if pos > len(link_names):
            break
        elif pos == 0 and skip_first:
            # don't always show one for logged-in users
            continue
        else:
            link_names.insert(pos, promoted_items[i]._fullname)

@memoize('cached_organic_links_user', time = organic_lifetime)
def cached_organic_links(username):
    if username:
        user = Account._by_name(username)
    else:
        user = FakeAccount()

    sr_count = count.get_link_counts()
    srs = Subreddit.user_subreddits(user)

    #only use links from reddits that you're subscribed to
    link_names = filter(lambda n: sr_count[n][1] in srs, sr_count.keys())
    link_names.sort(key = lambda n: sr_count[n][0])

    #potentially add a up and coming link
    if random.choice((True, False)):
        sr = Subreddit._byID(random.choice(srs))
        items = only_recent(get_hot(sr))
        if items:
            if len(items) == 1:
                new_item = items[0]
            else:
                new_item = random.choice(items[1:4])
            link_names.insert(0, new_item._fullname)

    insert_promoted(link_names, srs)

    builder = IDBuilder(link_names, num = 30, skip = True, keep_fn = keep_link)
    links = builder.get_items()[0]

    calculation_key = str(datetime.now(g.tz))

    update_pos(0, calculation_key)

    ret = [l._fullname for l in UniqueIterator(links)]

    return (calculation_key, ret)

def organic_links(user):
    from r2.controllers.reddit_base import organic_pos

    username = user.name if c.user_is_loggedin else None
    cached_key, links = cached_organic_links(username)

    cookie_key, pos = organic_pos()
    # pos will be 0 if it wasn't specified
    if links and (cookie_key == cached_key):
        # make sure that we're not running off the end of the list
        pos = pos % len(links)

    return links, pos, cached_key

def update_pos(pos, key):
    "Update the user's current position within the cached organic list."
    from r2.controllers import reddit_base

    reddit_base.set_organic_pos(key, pos)
