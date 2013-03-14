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

from r2.models import *
from r2.lib.utils import fetch_things2
from pylons import g
from r2.lib.db import queries


import string
import random

def random_word(min, max):
    return ''.join([ random.choice(string.letters)
                         for x
                         in range(random.randint(min, max)) ])

def populate(num_srs = 10, num_users = 1000, num_links = 100, num_comments = 20, num_votes = 50):
    try:
        a = Account._by_name(g.system_user)
    except NotFound:
        a = register(g.system_user, "password", "127.0.0.1")

    srs = []
    for i in range(num_srs):
        name = "reddit_test%d" % i
        try:
            sr = Subreddit._new(name = name, title = "everything about #%d"%i,
                                ip = '0.0.0.0', author_id = a._id)
            sr._downs = 10
            sr.lang = "en"
            sr._commit()
        except SubredditExists:
            sr = Subreddit._by_name(name)
        srs.append(sr)

    accounts = []
    for i in range(num_users):
        name_ext = ''.join([ random.choice(string.letters)
                             for x
                             in range(int(random.uniform(1, 10))) ])
        name = 'test_' + name_ext
        try:
            a = register(name, name, "127.0.0.1")
        except AccountExists:
            a = Account._by_name(name)
        accounts.append(a)

    for i in range(num_links):
        id = random.uniform(1,100)
        title = url = 'http://google.com/?q=' + str(id)
        user = random.choice(accounts)
        sr = random.choice(srs)
        l = Link._submit(title, url, user, sr, '127.0.0.1')
        queries.new_link(l)

        comments = [ None ]
        for i in range(int(random.betavariate(2, 8) * 5 * num_comments)):
            user = random.choice(accounts)
            body = ' '.join([ random_word(1, 10)
                              for x
                              in range(int(200 * random.betavariate(2, 6))) ])
            parent = random.choice(comments)
            (c, inbox_rel) = Comment._new(user, l, parent, body, '127.0.0.1')
            queries.new_comment(c, inbox_rel)
            comments.append(c)
            for i in range(int(random.betavariate(2, 8) * 10)):
                another_user = random.choice(accounts)
                v = Vote.vote(another_user, c, True, '127.0.0.1')
                queries.new_vote(v)

        like = random.randint(50,100)
        for i in range(int(random.betavariate(2, 8) * 5 * num_votes)):
           user = random.choice(accounts)
           v = Vote.vote(user, l, random.randint(0, 100) <= like, '127.0.0.1')
           queries.new_vote(v)

    queries.worker.join()


def by_url_cache():
    q = Link._query(Link.c._spam == (True,False),
                    data = True,
                    sort = desc('_date'))
    for i, link in enumerate(fetch_things2(q)):
        if i % 100 == 0:
            print "%s..." % i
        link.set_url_cache()
