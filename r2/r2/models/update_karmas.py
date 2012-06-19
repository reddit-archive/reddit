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
# All portions of the code written by reddit are Copyright (c) 2006-2012 reddit
# Inc. All Rights Reserved.
###############################################################################

from r2.models import Link, Account, Subreddit
from r2.lib.db.operators import desc, or_
from r2.lib.utils import timeago

def all_comments():
    q = Comment._query(Comment.c._score > 2,
                       Comment.c.sr_id != 6,
                       Comment.c._date > timeago('1 weeks'),
                       sort = desc('_date'),
                       limit = 200,
                       data = True)
    comments = list(q)
    while comments:
        for l in comments:
            yield l
        comments = list(q._after(l))

def to_update():
    user_sr = set()
    for l in all_comments():
        user_sr.add((l.author_id, l.sr_id))
    return user_sr

def update_karmas():
    for pair in to_update():
        user = Account._byID(pair[0], True)
        sr = Subreddit._byID(pair[1], True)

        print user.name, sr.name
        user.incr_karma('comment', sr, 20)

def all_users():
    q = Account._query(or_(Account.c.link_karma != 0,
                           Account.c.comment_karma != 0),
                       Account.c._spam == (True, False),
                       Account.c._deleted == (True, False),
                       sort = desc('_date'),
                       limit = 200,
                       data = True)
    users = list(q)
    while users:
        for l in users:
            yield l
        users = list(q._after(l))


def copy_karmas():
    reddit = Subreddit._by_name('reddit.com')
    for user in all_users():
        print user.name, user.link_karma, user.comment_karma
        user.incr_karma('link', reddit, user.link_karma)
        user.incr_karma('comment', reddit, user.comment_karma)
        
