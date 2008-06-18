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
cache_key = 'popular_queries'
reset_num = 100
min_run = 2
cache_time = 70
max_queries = 50

class QueryStats(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.query_count = {}
        self.total_count = 0
        self.queries = {}

    def add(self, query):
        iden = query._iden()
        if self.query_count.has_key(iden):
            self.query_count[iden] += 1
        else:
            self.queries[iden] = query
            self.query_count[iden] = 1
        self.total_count += 1

        #update every reset_num queries
        if self.total_count > reset_num:
            self.update_cache()
            self.reset()
        
    def update_cache(self):
        #sort count
        idens = self.query_count.keys()
        idens.sort(key = lambda x: self.query_count[x], reverse = True)
        idens = idens[:max_queries]
        
        #cache queries with min occurances
        queries = [self.queries[i]
                   for i in idens if self.query_count[i] > min_run]
        from pylons import g
        cache = g.cache
        cache.set(cache_key, queries)

def default_queries():
    from r2.models import Link, Subreddit
    from r2.lib.db.operators import desc
    from copy import deepcopy
    queries = []

    q = Link._query(Link.c.sr_id == Subreddit.user_subreddits(None),
                    sort = desc('_hot'),
                    limit = 37)

    queries.append(q)
    #add a higher limit one too
    q = deepcopy(q)
    q._limit = 75
    queries.append(q)

    return queries

def run_queries():
    from r2.models import subreddit
    from pylons import g
    cache = g.cache
    queries = cache.get(cache_key) or default_queries()
    
    for q in queries:
        q._read_cache = False
        q._write_cache = True
        q._cache_time = cache_time
        q._list()

    #find top
    q = default_queries()[0]
    q._limit = 1
    top_link = list(q)[0]
    if top_link:
        top_link._load()
        top_link.top_link = True
        top_link._commit()
