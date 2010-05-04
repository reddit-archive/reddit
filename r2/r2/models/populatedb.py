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
from r2.lib.utils import fetch_things2

import string
import random

def populate(sr_name = 'reddit.com', sr_title = "reddit.com: what's new online",
             num = 100):
    create_accounts(num)

    a = list(Account._query(limit = 1))[0]

    try:
        sr = Subreddit._new(name = sr_name, title = sr_title,
                            ip = '0.0.0.0', author_id = a._id)
        sr._commit()
    except SubredditExists:
        pass

    create_links(num)
    
def create_accounts(num):
    for i in range(num):
        name_ext = ''.join([ random.choice(string.letters)
                             for x
                             in range(int(random.uniform(1, 10))) ])
        name = 'test_' + name_ext
        try:
            register(name, name)
        except AccountExists:
            pass

def create_links(num):
    from r2.lib.db import queries

    accounts = list(Account._query(limit = num, data = True))
    subreddits = list(Subreddit._query(limit = num, data = True))
    for i in range(num):
        id = random.uniform(1,100)
        title = url = 'http://google.com/?q=' + str(id)
        user = random.choice(accounts)
        sr = random.choice(subreddits)
        l = Link._submit(title, url, user, sr, '127.0.0.1')
        queries.new_link(l)

    queries.worker.join()
        


def by_url_cache():
    q = Link._query(Link.c._spam == (True,False),
                    data = True,
                    sort = desc('_date'))
    for i, link in enumerate(fetch_things2(q)):
        if i % 100 == 0:
            print "%s..." % i
        link.set_url_cache()
