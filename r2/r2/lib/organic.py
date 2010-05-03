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
from r2.models import *
from r2.lib.memoize import memoize
from r2.lib.normalized_hot import get_hot
from r2.lib import count
from r2.lib.utils import UniqueIterator, timeago
from r2.lib.promote import random_promoted

from pylons import c

import random
from time import time

organic_lifetime = 5*60
organic_length   = 30

# how many regular organic links should show between promoted ones
promoted_every_n = 5

def keep_link(link):
    return link.fresh

def insert_promoted(link_names, sr_ids, logged_in):
    """
    Inserts promoted links into an existing organic list. Destructive
    on `link_names'
    """
    promoted_items = random_promoted()

    if not promoted_items:
        return

    # no point in running the builder over more promoted links than
    # we'll even use
    max_promoted = max(1,len(link_names)/promoted_every_n)

    # remove any that the user has acted on
    def keep(item):
        if c.user_is_loggedin and c.user._id == item.author_id:
            return True
        else:
            return item.keep_item(item)

    builder = IDBuilder(promoted_items, keep_fn = keep, 
                        skip = True,  num = max_promoted)
    promoted_items = builder.get_items()[0]

    if not promoted_items:
        return
    # don't insert one at the head of the list 50% of the time for
    # logged in users, and 50% of the time for logged-off users when
    # the pool of promoted links is less than 3 (to avoid showing the
    # same promoted link to the same person too often)
    if (logged_in or len(promoted_items) < 3) and random.choice((True,False)):
        promoted_items.insert(0, None)

    # insert one promoted item for every N items
    for i, item in enumerate(promoted_items):
        pos = i * promoted_every_n + i
        if pos > len(link_names):
            break
        elif item is None:
            continue
        else:
            link_names.insert(pos, item._fullname)

@memoize('cached_organic_links2', time = organic_lifetime)
def cached_organic_links(user_id, langs):
    if user_id is None:
        sr_ids = Subreddit.default_subreddits()
    else:
        user = Account._byID(user_id, data=True)
        sr_ids = Subreddit.user_subreddits(user)

    sr_count = count.get_link_counts()
    #only use links from reddits that you're subscribed to
    link_names = filter(lambda n: sr_count[n][1] in sr_ids, sr_count.keys())
    link_names.sort(key = lambda n: sr_count[n][0])
    #potentially add a up and coming link
    if random.choice((True, False)) and sr_ids:
        sr = Subreddit._byID(random.choice(sr_ids))
        fnames = get_hot(sr, True)
        if fnames:
            if len(fnames) == 1:
                new_item = fnames[0]
            else:
                new_item = random.choice(fnames[1:4])
            link_names.insert(0, new_item)

    insert_promoted(link_names, sr_ids, user_id is not None)

    # remove any that the user has acted on
    builder = IDBuilder(link_names,
                        skip = True, keep_fn = keep_link,
                        num = organic_length)
    link_names = [ x._fullname for x in builder.get_items()[0] ]

    #if not logged in, don't reset the count. if we did that we might get in a
    #cycle where the cache will return the same link over and over
    if user_id:
        update_pos(0)

    # remove any duplicates caused by insert_promoted if the user is logged in
    if user_id:
        link_names = list(UniqueIterator(link_names))

    return link_names

def organic_links(user):
    from r2.controllers.reddit_base import organic_pos
    
    sr_ids = Subreddit.user_subreddits(user)
    # make sure that these are sorted so the cache keys are constant
    sr_ids.sort()

    if c.user_is_loggedin:
        links = cached_organic_links(user._id, None)
    else:
        links = cached_organic_links(None, c.content_langs)

    pos = organic_pos()
    # pos will be 0 if it wasn't specified
    if links and pos != 0:
        # make sure that we're not running off the end of the list
        pos = pos % len(links)

    return links, pos

def update_pos(pos):
    "Update the user's current position within the cached organic list."
    from r2.controllers import reddit_base

    reddit_base.set_organic_pos(pos)
