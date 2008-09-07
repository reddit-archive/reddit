from r2.models import Account, Link, Comment, Vote, SaveHide
from r2.models import Message, Inbox, Subreddit
from r2.lib.db.thing import Thing
from r2.lib.db.operators import asc, desc, timeago
from r2.lib.db import query_queue
from r2.lib.db.sorts import epoch_seconds
from r2.lib.utils import fetch_things2, worker

from datetime import datetime

from pylons import g
query_cache = g.query_cache

precompute_limit = 1000

db_sorts = dict(hot = (desc, '_hot'),
                new = (desc, '_date'),
                top = (desc, '_score'),
                controversial = (desc, '_controversy'),
                old = (asc, '_date'))

def db_sort(sort):
    cls, col = db_sorts[sort]
    return cls(col)

db_times = dict(all = None,
                hour = Thing.c._date >= timeago('1 hour'),
                day = Thing.c._date >= timeago('1 day'),
                week = Thing.c._date >= timeago('1 week'),
                month = Thing.c._date >= timeago('1 month'),
                year = Thing.c._date >= timeago('1 year'))

#we need to define the filter functions here so cachedresults can be pickled
def filter_identity(x):
    return x

def filter_thing2(x):
    """A filter to apply to the results of a relationship query returns
    the object of the relationship."""
    return x._thing2

class CachedResults(object):
    """Given a query returns a list-like object that will lazily look up
    the query from the persistent cache. """
    def __init__(self, query, filter = filter_identity):
        self.query = query
        self.query._limit = precompute_limit
        self.filter = filter
        self.iden = self.query._iden()
        self.data = []
        self._fetched = False

    def fetch(self):
        """Loads the query from the cache."""
        if not self._fetched:
            self._fetched = True
            self.data = query_cache.get(self.iden) or []
        return list(self)

    def update(self):
        """Runs the query and stores the result in the cache. It also stores
        the columns relevant to the sort to make merging with other
        results faster."""
        self.data = []
        sort_cols = [s.col for s in self.query._sort]
        for i in self.query:
            item = self.filter(i)
            l = [item._fullname]
            for col in sort_cols:
                #take the property of the original 
                attr = getattr(i, col)
                #convert dates to epochs to take less space
                if isinstance(attr, datetime):
                    attr = epoch_seconds(attr)
                l.append(attr)

            self.data.append(tuple(l))
        
        self._fetched = True
        query_cache.set(self.iden, self.data)

    def __repr__(self):
        return '<CachedResults %s %s>' % (self.query._rules, self.query._sort)

    def __iter__(self):
        if not self._fetched:
            self.fetch()

        for x in self.data:
            yield x[0]

def merge_results(*results):
    """Given two CachedResults, mergers their lists based on the sorts of
    their queries."""
    if len(results) == 1:
        return list(results[0])

    #make sure the sorts match
    sort = results[0].query._sort
    assert(all(r.query._sort == sort for r in results[1:]))

    def thing_cmp(t1, t2):
        for i, s in enumerate(sort):
            #t1 and t2 are tuples of (fullname, *sort_cols), so we can
            #get the value to compare right out of the tuple
            v1, v2 = t1[i + 1], t2[i + 1]
            if v1 != v2:
                return cmp(v1, v2) if isinstance(s, asc) else cmp(v2, v1)
        #they're equal
        return 0

    all_items = []
    for r in results:
        r.fetch()
        all_items.extend(r.data)

    #all_items = Thing._by_fullname(all_items, return_dict = False)
    return [i[0] for i in sorted(all_items, cmp = thing_cmp)]

def get_links(sr, sort, time):
    """General link query for a subreddit."""
    q = Link._query(Link.c.sr_id == sr._id,
                    sort = db_sort(sort))
    if time != 'all':
        q._filter(db_times[time])
    return CachedResults(q)

def user_query(kind, user, sort, time):
    """General profile-page query."""
    q = kind._query(kind.c.author_id == user._id,
                    kind.c._spam == (True, False),
                    sort = db_sort(sort))
    if time != 'all':
        q._filter(db_times[time])
    return CachedResults(q)

def get_comments(user, sort, time):
    return user_query(Comment, user, sort, time)

def get_submitted(user, sort, time):
    return user_query(Link, user, sort, time)

def get_overview(user, sort, time):
    return merge_results(get_comments(user, sort, time),
                         get_submitted(user, sort, time))

def user_rel_query(rel, user, name):
    """General user relationship query."""
    q = rel._query(rel.c._thing1_id == user._id,
                   rel.c._t2_deleted == False,
                   rel.c._name == name,
                   sort = desc('_date'),
                   eager_load = True,
                   #thing_data = True
                   )
       
    return CachedResults(q, filter_thing2)

vote_rel = Vote.rel(Account, Link)

def get_liked(user):
    return user_rel_query(vote_rel, user, '1')

def get_disliked(user):
    return user_rel_query(vote_rel, user, '-1')

def get_hidden(user):
    return user_rel_query(SaveHide, user, 'hide')

def get_saved(user):
    return user_rel_query(SaveHide, user, 'save')

inbox_message_rel = Inbox.rel(Account, Message)
def get_inbox_messages(user):
    return user_rel_query(inbox_message_rel, user, 'inbox')

inbox_comment_rel = Inbox.rel(Account, Comment)
def get_inbox_comments(user):
    return user_rel_query(inbox_comment_rel, user, 'inbox')

def get_inbox(user):
    return merge_results(get_inbox_comments(user),
                         get_inbox_messages(user))

def get_sent(user):
    q = Message._query(Message.c.author_id == user._id,
                       Message.c._spam == (True, False),
                       sort = desc('_date'))
    return CachedResults(q)

#can be rewritten to be more efficient
def all_queries(fn, obj, *param_lists):
    """Given a fn and a first argument 'obj', calls the fn(obj, *params)
    for every permutation of the parameters in param_lists"""
    results = []
    params = [[obj]]
    for pl in param_lists:
        new_params = []
        for p in pl:
            for c in params:
                new_param = list(c)
                new_param.append(p)
                new_params.append(new_param)
        params = new_params

    results = [fn(*p) for p in params]
    return results

def display_jobs(jobs):
    for r in jobs:
        print r
    print len(jobs)

def add_queries(queries):
    """Adds multiple queries to the query queue"""
    def _add_queries():
        for q in queries:
            query_queue.add_query(q)
    worker.do(_add_queries)

## The following functions should be called after their respective
## actions to update the correct listings.
def new_link(link):
    sr = Subreddit._byID(link.sr_id)
    author = Account._byID(link.author_id)

    results = all_queries(get_links, sr, ('hot', 'new', 'old'), ['all'])
    results.extend(all_queries(get_links, sr, ('top', 'controversial'), db_times.keys()))
    results.append(get_submitted(author, 'new', 'all'))

    add_queries(results)

def new_comment(comment):
    author = Account._byID(comment.author_id)
    results = [get_comments(author, 'new', 'all')]
    
    if hasattr(comment, 'parent_id'):
        parent = Comment._byID(comment.parent_id, data = True)
        parent_author = Account._byID(parent.author_id)
        results.append(get_inbox_comments(parent_author))

    add_queries(results)
    
def new_vote(vote):
    user = vote._thing1
    item = vote._thing2

    if not isinstance(item, Link):
        return

    sr = item.subreddit_slow
    results = all_queries(get_links, sr, ('hot', 'new', 'old'), ['all'])
    results.extend(all_queries(get_links, sr, ('top', 'controversial'), db_times.keys()))
    
    #must update both because we don't know if it's a changed vote
    results.append(get_liked(user))
    results.append(get_disliked(user))

    add_queries(results)
    
def new_message(message):
    from_user = Account._byID(message.author_id)
    to_user = Account._byID(message.to_id)

    results = [get_sent(from_user)]
    results.append(get_inbox_messages(to_user))

    add_queries(results)

def new_savehide(user, action):
    if action == 'save':
        results = [get_saved(user)]
    elif action == 'hide':
        results = [get_hidden(user)]
        
    add_queries(results)

def add_all_srs():
    """Adds every listing query for every subreddit to the queue."""
    q = Subreddit._query(sort = asc('_date'))
    for sr in fetch_things2(q):
        add_queries(all_queries(get_links, sr, ('hot', 'new', 'old'), ['all']))
        add_queries(all_queries(get_links, sr, ('top', 'controversial'), db_times.keys()))

def add_all_users():
    q = Account._query(sort = asc('_date'))
    for user in fetch_things2(q):
        results = [get_inbox_messages(user),
                   get_inbox_comments(user),
                   get_sent(user),
                   get_liked(user),
                   get_disliked(user),
                   get_saved(user),
                   get_hidden(user),
                   get_submitted(user, 'new', 'all'),
                   get_comments(user, 'new', 'all')]
        add_queries(results)

def compute_all_inboxes():
    q = Account._query(sort = asc('_date'))
    for user in fetch_things2(q):
        get_inbox_messages(user).update()
        get_inbox_comments(user).update()
        get_sent(user).update()

def compute_all_liked():
    q = Account._query(sort = asc('_date'))
    for user in fetch_things2(q):
        get_liked(user).update()
        get_disliked(user).update()

def compute_all_saved():
    q = Account._query(sort = asc('_date'))
    for user in fetch_things2(q):
        get_saved(user).update()
        get_hidden(user).update()

def compute_all_user_pages():
    q = Account._query(sort = asc('_date'))
    for user in fetch_things2(q):
        get_submitted(user, 'new', 'all').update()
        get_comments(user, 'new', 'all').update()
