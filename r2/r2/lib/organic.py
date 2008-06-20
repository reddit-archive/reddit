# "The contents of this file are subject to the Common Public Attribution
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
from r2.lib.normalized_hot import is_top_link
from r2.lib import count

from pylons import g
cache = g.cache

def pos_key(user):
    return 'organic_pos_' + user.name
    
def keep_link(link):
    return not any((link.likes != None,
                    link.saved,
                    link.clicked,
                    link.hidden))
     

@memoize('cached_organic_links', time = 300)
def cached_organic_links(username):
    user = Account._by_name(username)

    sr_count = count.get_link_counts()
    srs = Subreddit.user_subreddits(user)
    link_names = filter(lambda n: sr_count[n][1] in srs, sr_count.keys())
    link_names.sort(key = lambda n: sr_count[n][0])

    builder = IDBuilder(link_names, num = 30, skip = True, keep_fn = keep_link)
    links = builder.get_items()[0]
    cache.set(pos_key(user), 0)
    return [l._fullname for l in links]

def organic_links(user):
    links = cached_organic_links(user.name)
    pos = cache.get(pos_key(user)) or 0
    return (links, pos)

def update_pos(user, pos):
    cache.set(pos_key(user), pos)
    
