from r2.models import Account, Link, Comment, Vote, SaveHide
from r2.models import Message, Inbox, Subreddit
from r2.lib.db.thing import Thing, Merge
from r2.lib.db.operators import asc, desc, timeago
from r2.lib.db import query_queue
from r2.lib.db.sorts import epoch_seconds
from r2.lib.utils import fetch_things2, worker, tup, UniqueIterator
from r2.lib.solrsearch import DomainSearchQuery

from datetime import datetime
import itertools

from pylons import g
query_cache = g.permacache

precompute_limit = 1000

db_sorts = dict(hot = (desc, '_hot'),
                new = (desc, '_date'),
                top = (desc, '_score'),
                controversial = (desc, '_controversy'),
                old = (asc, '_date'),
                toplinks = (desc, '_hot'))

def db_sort(sort):
    cls, col = db_sorts[sort]
    return cls(col)

search_sort = dict(hot = 'hot desc',
                   new = 'date desc',
                   top = 'points desc',
                   controversial = 'controversy desc',
                   old = 'date asc')

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
    def __init__(self, query, filter):
        self.query = query
        self.query._limit = precompute_limit
        self.filter = filter
        self.iden = self.query._iden()
        self.sort_cols = [s.col for s in self.query._sort]
        self.data = []
        self._fetched = False

    def fetch(self):
        """Loads the query from the cache."""
        if not self._fetched:
            self._fetched = True
            self.data = query_cache.get(self.iden) or []

    def make_item_tuple(self, item):
        """Given a single 'item' from the result of a query build the tuple
        that will be stored in the query cache. It is effectively the
        fullname of the item after passing through the filter plus the
        columns of the unfiltered item to sort by."""
        filtered_item = self.filter(item)
        lst = [filtered_item._fullname]
        for col in self.sort_cols:
            #take the property of the original 
            attr = getattr(item, col)
            #convert dates to epochs to take less space
            if isinstance(attr, datetime):
                attr = epoch_seconds(attr)
            lst.append(attr)
        return tuple(lst)

    def can_insert(self):
        """True if a new item can just be inserted rather than
           rerunning the query. This is only true in some
           circumstances, which includes having no time rules, and
           being sorted descending"""
        if self.query._sort in ([desc('_date')],
                                [desc('_hot'), desc('_date')],
                                [desc('_score'), desc('_date')],
                                [desc('_controversy'), desc('_date')]):
            if not any(r.lval.name == '_date'
                       for r in self.query._rules):
                # if no time-rule is specified, then it's 'all'
                return True
        return False

    def can_delete(self):
        """True if a item can be removed from the listing, always true for now."""
        return True

    def insert(self, items):
        """Inserts the item into the cached data. This only works
           under certain criteria, see can_insert."""
        self.fetch()
        t = [ self.make_item_tuple(item) for item in tup(items) ]

        # insert the new items, remove the duplicates (keeping the one
        # being inserted over the stored value if applicable), and
        # sort the result
        data = itertools.chain(t, self.data)
        data = UniqueIterator(data, key = lambda x: x[0])
        data = sorted(data, key=lambda x: x[1:], reverse=True)
        data = list(data)
        self.data = data

        query_cache.set(self.iden, self.data[:precompute_limit])

    def delete(self, items):
        """Deletes an item from the cached data."""
        self.fetch()
        changed = False

        for item in tup(items):
            t = self.make_item_tuple(item)
            while t in self.data:
                self.data.remove(t)
                changed = True
            
        if changed:
            query_cache.set(self.iden, self.data)
        
    def update(self):
        """Runs the query and stores the result in the cache. It also stores
        the columns relevant to the sort to make merging with other
        results faster."""
        self.data = [self.make_item_tuple(i) for i in self.query]
        self._fetched = True
        query_cache.set(self.iden, self.data)

    def __repr__(self):
        return '<CachedResults %s %s>' % (self.query._rules, self.query._sort)

    def __iter__(self):
        self.fetch()

        for x in self.data:
            yield x[0]

def merge_cached_results(*results):
    """Given two CachedResults, merges their lists based on the sorts of
    their queries."""
    if len(results) == 1:
        return list(results[0])

    #make sure the sorts match
    sort = results[0].query._sort
    assert all(r.query._sort == sort for r in results[1:])

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

def make_results(query, filter = filter_identity):
    if g.use_query_cache:
        return CachedResults(query, filter)
    else:
        query.prewrap_fn = filter
        return query

def merge_results(*results):
    if g.use_query_cache:
        return merge_cached_results(*results)
    else:
        m = Merge(results, sort = results[0]._sort)
        #assume the prewrap_fn's all match
        m.prewrap_fn = results[0].prewrap_fn
        return m

def get_links(sr, sort, time):
    """General link query for a subreddit."""
    q = Link._query(Link.c.sr_id == sr._id,
                    sort = db_sort(sort))

    if sort == 'toplinks':
        q._filter(Link.c.top_link == True)

    if time != 'all':
        q._filter(db_times[time])
    return make_results(q)

def get_spam_links(sr):
    q_l = Link._query(Link.c.sr_id == sr._id,
                      Link.c._spam == True,
                      sort = db_sort('new'))
    return make_results(q_l)

def get_spam_comments(sr):
    q_c = Comment._query(Comment.c.sr_id == sr._id,
                         Comment.c._spam == True,
                         sort = db_sort('new'))
    return make_results(q_c)

def get_spam(sr):
    return get_spam_links(sr)
    #return merge_results(get_spam_links(sr),
    #                     get_spam_comments(sr))

def get_reported_links(sr):
    q_l = Link._query(Link.c.reported != 0,
                      Link.c.sr_id == sr._id,
                      Link.c._spam == False,
                      sort = db_sort('new'))
    return make_results(q_l)

def get_reported_comments(sr):
    q_c = Comment._query(Comment.c.reported != 0,
                         Comment.c.sr_id == sr._id,
                         Comment.c._spam == False,
                         sort = db_sort('new'))
    return make_results(q_c)

def get_reported(sr):
    return get_reported_links(sr)
    #return merge_results(get_reported_links(sr),
    #                     get_reported_comments(sr))

def get_domain_links(domain, sort, time):
    return DomainSearchQuery(domain, sort=search_sort[sort], timerange=time)

def user_query(kind, user, sort, time):
    """General profile-page query."""
    q = kind._query(kind.c.author_id == user._id,
                    kind.c._spam == (True, False),
                    sort = db_sort(sort))
    if time != 'all':
        q._filter(db_times[time])
    return make_results(q)

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
                   thing_data = not g.use_query_cache
                   )
       
    return make_results(q, filter_thing2)

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
    return make_results(q)

def add_queries(queries, insert_items = None, delete_items = None):
    """Adds multiple queries to the query queue. If insert_items or
    delete_items is specified, the query may not need to be recomputed at
    all."""
    log = g.log.debug
    make_lock = g.make_lock
    def _add_queries():
        for q in queries:
            if not isinstance(q, CachedResults):
                continue

            with make_lock("add_query(%s)" % q.iden):
                if insert_items and q.can_insert():
                    log("Inserting %s into query %s" % (insert_items, q))
                    q.insert(insert_items)
                elif delete_items and q.can_delete():
                    log("Deleting %s from query %s" % (delete_items, q))
                    q.delete(delete_items)
                else:
                    log('Adding precomputed query %s' % q)
                    query_queue.add_query(q)
    worker.do(_add_queries)
    

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

## The following functions should be called after their respective
## actions to update the correct listings.
def new_link(link):
    sr = Subreddit._byID(link.sr_id)
    author = Account._byID(link.author_id)

    results = all_queries(get_links, sr, ('hot', 'new', 'old'), ['all'])
    results.extend(all_queries(get_links, sr, ('top', 'controversial'), db_times.keys()))
    results.append(get_submitted(author, 'new', 'all'))
    #results.append(get_links(sr, 'toplinks', 'all'))
    if link._spam:
        results.append(get_spam_links(sr))
    
    if link._deleted:
        add_queries(results, delete_items = link)
    else:
        add_queries(results, insert_items = link)

def new_comment(comment, inbox_rel):
    author = Account._byID(comment.author_id)
    job = [get_comments(author, 'new', 'all')]
    if comment._deleted:
        add_queries(job, delete_items = comment)
    else:
        #if comment._spam:
        #    sr = Subreddit._byID(comment.sr_id)
        #    job.append(get_spam_comments(sr))
        add_queries(job, insert_items = comment)

    if inbox_rel:
        inbox_owner = inbox_rel._thing1
        add_queries([get_inbox_comments(inbox_owner)],
                    insert_items = inbox_rel)

def new_vote(vote):
    user = vote._thing1
    item = vote._thing2

    if not isinstance(item, Link):
        return

    if vote.valid_thing and not item._spam and not item._deleted:
        sr = item.subreddit_slow
        results = [get_links(sr, 'hot', 'all')]
        results.extend(all_queries(get_links, sr, ('top', 'controversial'), db_times.keys()))
        #results.append(get_links(sr, 'toplinks', 'all'))
        add_queries(results, insert_items = item)
    
    #must update both because we don't know if it's a changed vote
    if vote._name == '1':
        add_queries([get_liked(user)], insert_items = vote)
        add_queries([get_disliked(user)], delete_items = vote)
    elif vote._name == '-1':
        add_queries([get_liked(user)], delete_items = vote)
        add_queries([get_disliked(user)], insert_items = vote)
    else:
        add_queries([get_liked(user)], delete_items = vote)
        add_queries([get_disliked(user)], delete_items = vote)
    
def new_message(message, inbox_rel):
    from_user = Account._byID(message.author_id)
    to_user = Account._byID(message.to_id)

    add_queries([get_sent(from_user)], insert_items = message)
    add_queries([get_inbox_messages(to_user)], insert_items = inbox_rel)

def new_savehide(rel):
    user = rel._thing1
    name = rel._name
    if name == 'save':
        add_queries([get_saved(user)], insert_items = rel)
    elif name == 'unsave':
        add_queries([get_saved(user)], delete_items = rel)
    elif name == 'hide':
        add_queries([get_hidden(user)], insert_items = rel)
    elif name == 'unhide':
        add_queries([get_hidden(user)], delete_items = rel)

def _by_srid(things):
    """Takes a list of things and returns them in a dict separated by
       sr_id, in addition to the looked-up subreddits"""
    ret = {}

    for thing in things:
        if hasattr(thing, 'sr_id'):
            ret.setdefault(thing.sr_id, []).append(thing)

    srs = Subreddit._byID(ret.keys(), return_dict=True) if ret else {}

    return ret, srs

def ban(things):
    by_srid, srs = _by_srid(things)
    if not by_srid:
        return

    for sr_id, things in by_srid.iteritems():
        sr = srs[sr_id]
        links = [ x for x in things if isinstance(x, Link) ]
        #comments = [ x for x in things if isinstance(x, Comment) ]

        if links:
            add_queries([get_spam_links(sr)], insert_items = links)
            # rip it out of the listings. bam!
            results = [get_links(sr, 'hot', 'all'),
                       get_links(sr, 'new', 'all'),
                       get_links(sr, 'top', 'all'),
                       get_links(sr, 'controversial', 'all')]
            results.extend(all_queries(get_links, sr, ('top', 'controversial'), db_times.keys()))
            add_queries(results, delete_items = links)

        #if comments:
        #    add_queries([get_spam_comments(sr)], insert_items = comments)

def unban(things):
    by_srid, srs = _by_srid(things)
    if not by_srid:
        return

    for sr_id, things in by_srid.iteritems():
        sr = srs[sr_id]
        links = [ x for x in things if isinstance(x, Link) ]
        #comments = [ x for x in things if isinstance(x, Comment) ]

        if links:
            add_queries([get_spam_links(sr)], delete_items = links)
            # put it back in the listings
            results = [get_links(sr, 'hot', 'all'),
                       get_links(sr, 'new', 'all'),
                       get_links(sr, 'top', 'all'),
                       get_links(sr, 'controversial', 'all')]
            results.extend(all_queries(get_links, sr, ('top', 'controversial'), db_times.keys()))
            add_queries(results, insert_items = links)

        #if comments:
        #    add_queries([get_spam_comments(sr)], delete_items = comments)

def new_report(thing):
    if isinstance(thing, Link):
        sr = Subreddit._byID(thing.sr_id)
        add_queries([get_reported_links(sr)], insert_items = thing)
    #elif isinstance(thing, Comment):
    #    sr = Subreddit._byID(thing.sr_id)
    #    add_queries([get_reported_comments(sr)], insert_items = thing)

def clear_reports(things):
    by_srid, srs = _by_srid(things)
    if not by_srid:
        return

    for sr_id, sr_things in by_srid.iteritems():
        sr = srs[sr_id]

        links = [ x for x in sr_things if isinstance(x, Link) ]
        #comments = [ x for x in sr_things if isinstance(x, Comment) ]

        if links:
            add_queries([get_reported_links(sr)], delete_items = links)
        #if comments:
        #    add_queries([get_reported_comments(sr)], delete_items = comments)

def add_all_ban_report_srs():
    """Adds the initial spam/reported pages to the report queue"""
    q = Subreddit._query(sort = asc('_date'))
    for sr in fetch_things2(q):
        add_queries([get_spam_links(sr),
                     #get_spam_comments(sr),
                     get_reported_links(sr),
                     #get_reported_comments(sr),
                     ])
        
def add_all_srs():
    """Adds every listing query for every subreddit to the queue."""
    q = Subreddit._query(sort = asc('_date'))
    for sr in fetch_things2(q):
        add_queries(all_queries(get_links, sr, ('hot', 'new', 'old'), ['all']))
        add_queries(all_queries(get_links, sr, ('top', 'controversial'), db_times.keys()))
        add_queries([get_links(sr, 'toplinks', 'all'),
                     get_spam_links(sr),
                     #get_spam_comments(sr),
                     get_reported_links(sr),
                     #get_reported_comments(sr),
                     ])

def update_user(user):
    if isinstance(user, str):
        user = Account._by_name(user)
    elif isinstance(user, int):
        user = Account._byID(user)

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

def add_all_users():
    q = Account._query(sort = asc('_date'))
    for user in fetch_things2(q):
        update_user(user)
