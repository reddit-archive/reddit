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
from r2.lib.memoize import memoize
from r2.lib.normalized_hot import get_hot, only_recent
from r2.lib import count
from r2.lib.utils import UniqueIterator, timeago
from r2.lib.promote import get_promoted

from pylons import c

import random
from time import time

organic_lifetime = 5*60

# how many regular organic links should show between promoted ones
promoted_every_n = 5

def keep_link(link):
    return not any((link.likes != None,
                    link.saved,
                    link.clicked,
                    link.hidden))

def insert_promoted(link_names, sr_ids, logged_in):
    """
    Inserts promoted links into an existing organic list. Destructive
    on `link_names'
    """
    promoted_items = get_promoted()

    if not promoted_items:
        return

    def my_keepfn(l):
        if l.promoted_subscribersonly and l.sr_id not in sr_ids:
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

    # don't insert one at the head of the list 50% of the time for
    # logged in users, and 50% of the time for logged-off users when
    # the pool of promoted links is less than 3 (to avoid showing the
    # same promoted link to the same person too often)
    if c.user_is_loggedin or len(promoted_items) < 3:
        skip_first = random.choice((True,False))
    else:
        skip_first = False

    # insert one promoted item for every N items
    for i, item in enumerate(promoted_items):
        pos = i * promoted_every_n
        if pos > len(link_names):
            break
        elif pos == 0 and skip_first:
            continue
        else:
            link_names.insert(pos, promoted_items[i]._fullname)

@memoize('cached_organic_links', time = organic_lifetime)
def cached_organic_links(sr_ids, logged_in):
    sr_count = count.get_link_counts()

    #only use links from reddits that you're subscribed to
    link_names = filter(lambda n: sr_count[n][1] in sr_ids, sr_count.keys())
    link_names.sort(key = lambda n: sr_count[n][0])

    #potentially add a up and coming link
    if random.choice((True, False)):
        sr = Subreddit._byID(random.choice(sr_ids))
        items = only_recent(get_hot(sr))
        if items:
            if len(items) == 1:
                new_item = items[0]
            else:
                new_item = random.choice(items[1:4])
            link_names.insert(0, new_item._fullname)

    insert_promoted(link_names, sr_ids, logged_in)

    builder = IDBuilder(link_names, num = 30, skip = True, keep_fn = keep_link)
    links = builder.get_items()[0]

    calculation_key = str(time())

    update_pos(0, calculation_key)

    # in case of duplicates (inserted by the random up-and-coming link
    # or a promoted link), return only the first
    ret = [l._fullname for l in UniqueIterator(links)]

    return (calculation_key, ret)

def organic_links(user):
    from r2.controllers.reddit_base import organic_pos

    sr_ids = Subreddit.user_subreddits(user)
    cached_key, links = cached_organic_links(sr_ids, c.user_is_loggedin)

    cookie_key, pos = organic_pos()
    # pos will be 0 if it wasn't specified
    if links and pos != 0:
        # make sure that we're not running off the end of the list
        pos = pos % len(links)

    return links, pos, cached_key

def update_pos(pos, key):
    "Update the user's current position within the cached organic list."
    from r2.controllers import reddit_base

    reddit_base.set_organic_pos(key, pos)
