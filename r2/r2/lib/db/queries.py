from r2.models import Account, Link, Comment, Vote, SaveHide
from r2.models import Message, Inbox, Subreddit, ModeratorInbox
from r2.lib.db.thing import Thing, Merge
from r2.lib.db.operators import asc, desc, timeago
from r2.lib.db import query_queue
from r2.lib.normalized_hot import expire_hot
from r2.lib.db.sorts import epoch_seconds
from r2.lib.utils import fetch_things2, tup, UniqueIterator, set_last_modified
from r2.lib import utils
from r2.lib.solrsearch import DomainSearchQuery
from r2.lib import amqp, sup
from r2.lib.comment_tree import add_comment, link_comments

import cPickle as pickle

from datetime import datetime
import itertools

from pylons import g
query_cache = g.permacache
log = g.log
make_lock = g.make_lock
worker = amqp.worker

precompute_limit = 1000

db_sorts = dict(hot = (desc, '_hot'),
                new = (desc, '_date'),
                top = (desc, '_score'),
                controversial = (desc, '_controversy'))

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

# batched_time_sorts/batched_time_times: top and controversial
# listings with a time-component are really expensive, and for the
# ones that span more than a day they don't change much (if at all)
# within that time. So we have some hacks to avoid re-running these
# queries against the precomputer except up to once per day
# * To get the results of the queries, we return the results of the
#   (potentially stale) query, merged with the query by 'day' (see
#   get_links)
# * When we are adding the special queries to the queue, we add them
#   with a preflight check to determine if they are runnable and a
#   postflight action to make them not runnable again for 24 hours
#   (see new_vote)
# * We have a task called catch_up_batch_queries to be run at least
#   once per day (ideally about once per hour) to find subreddits
#   where these queries haven't been run in the last 24 hours but that
#   have had at least one vote in that time
# TODO:
# * Do we need a filter on merged time-queries to keep items that are
#   barely too old from making it into the listing? This probably only
#   matters for 'week'
batched_time_times = set(('year', 'month', 'week'))
batched_time_sorts = set(('top', 'controversial'))

#we need to define the filter functions here so cachedresults can be pickled
def filter_identity(x):
    return x

def filter_thing2(x):
    """A filter to apply to the results of a relationship query returns
    the object of the relationship."""
    return x._thing2

def make_batched_time_query(sr, sort, time, preflight_check = True):
    q = get_links(sr, sort, time, merge_batched=False)

    if (g.use_query_cache
        and sort in batched_time_sorts
        and time in batched_time_times):

        if not preflight_check:
            q.force_run = True

        q.batched_time_srid = sr._id

    return q

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

        self.batched_time_srid = None

    @property
    def sort(self):
        return self.query._sort

    def preflight_check(self):
        if getattr(self, 'force_run', False):
            return True

        sr_id = getattr(self, 'batched_time_srid', None)
        if not sr_id:
            return True

        # this is a special query that tries to run less often, see
        # the discussion about batched_time_times
        sr = Subreddit._byID(sr_id, data=True)

        if (self.iden in getattr(sr, 'last_batch_query', {}) 
            and sr.last_batch_query[self.iden] > utils.timeago('1 day')):
            # this has been done in the last 24 hours, so we should skip it
            return False

        return True

    def postflight(self):
        sr_id = getattr(self, 'batched_time_srid', None)
        if not sr_id:
            return True

        with make_lock('modify_sr_last_batch_query(%s)' % sr_id):
            sr = Subreddit._byID(sr_id, data=True)
            last_batch_query = getattr(sr, 'last_batch_query', {}).copy()
            last_batch_query[self.iden] = datetime.now(g.tz)
            sr.last_batch_query = last_batch_query
            sr._commit()

    def fetch(self, force=False):
        """Loads the query from the cache."""
        self.fetch_multi([self], force=force)

    @classmethod
    def fetch_multi(cls, crs, force=False):
        unfetched = [cr for cr in crs if not cr._fetched or force]
        if not unfetched:
            return

        cached = query_cache.get_multi([cr.iden for cr in unfetched],
                                       allow_local = not force)
        for cr in unfetched:
            cr.data = cached.get(cr.iden) or []
            cr._fetched = True

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
           rerunning the query."""
         # This is only true in some circumstances: queries where
         # eligibility in the list is determined only by its sort
         # value (e.g. hot) and where addition/removal from the list
         # incurs an insertion/deletion event called on the query. So
         # the top hottest items in X some subreddit where the query
         # is notified on every submission/banning/unbanning/deleting
         # will work, but for queries with a time-component or some
         # other eligibility factor, it cannot be inserted this way.
        if self.query._sort in ([desc('_date')],
                                [desc('_hot'), desc('_date')],
                                [desc('_score'), desc('_date')],
                                [desc('_controversy'), desc('_date')]):
            if not any(r for r in self.query._rules
                       if r.lval.name == '_date'):
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
        data = data[:precompute_limit]

        self.data = data

        query_cache.set(self.iden, self.data)

    def delete(self, items):
        """Deletes an item from the cached data."""
        self.fetch()
        fnames = set(self.filter(x)._fullname for x in tup(items))

        data = filter(lambda x: x[0] not in fnames,
                      self.data)

        if data != self.data:
            self.data = data
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

class MergedCachedResults(object):
    """Given two CachedResults, merges their lists based on the sorts
       of their queries."""
    # normally we'd do this by having a superclass of CachedResults,
    # but we have legacy pickled CachedResults that we don't want to
    # break

    def __init__(self, results):
        self.cached_results = results
        CachedResults.fetch_multi([r for r in results
                                   if isinstance(r, CachedResults)])
        self._fetched = True

        self.sort = results[0].sort
        # make sure they're all the same
        assert all(r.sort == self.sort for r in results[1:])

        # if something is 'top' for the year *and* for today, it would
        # appear in both listings, so we need to filter duplicates
        all_items = UniqueIterator((item for cr in results
                                    for item in cr.data),
                                   key = lambda x: x[0])
        all_items = sorted(all_items, cmp=self._thing_cmp)
        self.data = list(all_items)

    def _thing_cmp(self, t1, t2):
        for i, s in enumerate(self.sort):
            # t1 and t2 are tuples of (fullname, *sort_cols), so we
            # can get the value to compare right out of the tuple
            v1, v2 = t1[i + 1], t2[i + 1]
            if v1 != v2:
                return cmp(v1, v2) if isinstance(s, asc) else cmp(v2, v1)
        #they're equal
        return 0

    def __repr__(self):
        return '<MergedCachedResults %r>' % (self.cached_results,)

    def __iter__(self):
        for x in self.data:
            yield x[0]

def make_results(query, filter = filter_identity):
    if g.use_query_cache:
        return CachedResults(query, filter)
    else:
        query.prewrap_fn = filter
        return query

def merge_results(*results):
    if g.use_query_cache:
        return MergedCachedResults(results)
    else:
        m = Merge(results, sort = results[0]._sort)
        #assume the prewrap_fn's all match
        m.prewrap_fn = results[0].prewrap_fn
        return m

def get_links(sr, sort, time, merge_batched=True):
    """General link query for a subreddit."""
    q = Link._query(Link.c.sr_id == sr._id,
                    sort = db_sort(sort))

    if time != 'all':
        q._filter(db_times[time])

    res = make_results(q)

    # see the discussion above batched_time_times
    if (merge_batched
        and g.use_query_cache
        and sort in batched_time_sorts
        and time in batched_time_times):

        byday = Link._query(Link.c.sr_id == sr._id,
                            sort = db_sort(sort))
        byday._filter(db_times['day'])

        res = merge_results(res,
                            make_results(byday))

    return res

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

def get_all_comments():
    """the master /comments page"""
    q = Comment._query(sort = desc('_date'))
    return make_results(q)

def get_comments(user, sort, time):
    return user_query(Comment, user, sort, time)

def get_submitted(user, sort, time):
    return user_query(Link, user, sort, time)

def get_overview(user, sort, time):
    return merge_results(get_comments(user, sort, time),
                         get_submitted(user, sort, time))

def user_rel_query(rel, user, name, filters = []):
    """General user relationship query."""
    q = rel._query(rel.c._thing1_id == user._id,
                   rel.c._t2_deleted == False,
                   rel.c._name == name,
                   sort = desc('_date'),
                   eager_load = True,
                   thing_data = not g.use_query_cache
                   )
    if filters:
        q._filter(*filters)

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

def get_subreddit_messages(sr):
    return user_rel_query(ModeratorInbox, sr, 'inbox')

def get_unread_subreddit_messages(sr):
    return user_rel_query(ModeratorInbox, sr, 'inbox',
                          filters = [ModeratorInbox.c.new == True])

inbox_message_rel = Inbox.rel(Account, Message)
def get_inbox_messages(user):
    return user_rel_query(inbox_message_rel, user, 'inbox')

def get_unread_messages(user):
    return user_rel_query(inbox_message_rel, user, 'inbox', 
                          filters = [inbox_message_rel.c.new == True])

inbox_comment_rel = Inbox.rel(Account, Comment)
def get_inbox_comments(user):
    return user_rel_query(inbox_comment_rel, user, 'inbox')

def get_unread_comments(user):
    return user_rel_query(inbox_comment_rel, user, 'inbox', 
                          filters = [inbox_comment_rel.c.new == True])

def get_inbox_selfreply(user):
    return user_rel_query(inbox_comment_rel, user, 'selfreply')

def get_unread_selfreply(user):
    return user_rel_query(inbox_comment_rel, user, 'selfreply', 
                          filters = [inbox_comment_rel.c.new == True])

def get_inbox(user):
    return merge_results(get_inbox_comments(user),
                         get_inbox_messages(user),
                         get_inbox_selfreply(user))

def get_sent(user):
    q = Message._query(Message.c.author_id == user._id,
                       Message.c._spam == (True, False),
                       sort = desc('_date'))
    return make_results(q)

def get_unread_inbox(user):
    return merge_results(get_unread_comments(user),
                         get_unread_messages(user),
                         get_unread_selfreply(user))

def add_queries(queries, insert_items = None, delete_items = None):
    """Adds multiple queries to the query queue. If insert_items or
       delete_items is specified, the query may not need to be
       recomputed against the database."""
    if not g.write_query_queue:
        return

    def _add_queries():
        for q in queries:
            query_cache.reset()
            if not isinstance(q, CachedResults):
                continue

            with make_lock("add_query(%s)" % q.iden):
                if insert_items and q.can_insert():
                    q.fetch(force=True)
                    log.debug("Inserting %s into query %s" % (insert_items, q))
                    q.insert(insert_items)
                elif delete_items and q.can_delete():
                    q.fetch(force=True)
                    log.debug("Deleting %s from query %s" % (delete_items, q))
                    q.delete(delete_items)
                else:
                    log.debug('Adding precomputed query %s' % q)
                    query_queue.add_query(q)
    # let the amqp worker handle this
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
    "Called on the submission and deletion of links"
    sr = Subreddit._byID(link.sr_id)
    author = Account._byID(link.author_id)

    results = [get_links(sr, 'new', 'all')]
    # we don't have to do hot/top/controversy because new_vote will do
    # that

    results.append(get_submitted(author, 'new', 'all'))
    if link._spam:
        results.append(get_spam_links(sr))

    # only 'new' qualifies for insertion, which will be done in
    # run_new_links
    add_queries(results, insert_items = link)

    amqp.add_item('new_link', link._fullname)


def new_comment(comment, inbox_rels):
    author = Account._byID(comment.author_id)
    job = [get_comments(author, 'new', 'all')]
    if comment._deleted:
        job.append(get_all_comments())
        add_queries(job, delete_items = comment)
    else:
        #if comment._spam:
        #    sr = Subreddit._byID(comment.sr_id)
        #    job.append(get_spam_comments(sr))
        add_queries(job, insert_items = comment)
        amqp.add_item('new_comment', comment._fullname)
        if not g.amqp_host:
            l = Link._byID(comment.link_id,data=True)
            add_comment_tree(comment, l)

    # note that get_all_comments() is updated by the amqp process
    # r2.lib.db.queries.run_new_comments

    if inbox_rels:
        for inbox_rel in tup(inbox_rels):
            inbox_owner = inbox_rel._thing1
            if inbox_rel._name == "inbox":
                add_queries([get_inbox_comments(inbox_owner)],
                            insert_items = inbox_rel)
            else:
                add_queries([get_inbox_selfreply(inbox_owner)],
                            insert_items = inbox_rel)
            set_unread(comment, inbox_owner, True)



def new_subreddit(sr):
    "no precomputed queries here yet"
    amqp.add_item('new_subreddit', sr._fullname)


def new_vote(vote):
    user = vote._thing1
    item = vote._thing2

    if not isinstance(item, Link):
        return

    if vote.valid_thing and not item._spam and not item._deleted:
        sr = item.subreddit_slow
        # don't do 'new', because that was done by new_link
        results = [get_links(sr, 'hot', 'all')]

        # for top and controversial we do some magic to recompute
        # these less often; see the discussion above
        # batched_time_times
        for sort in batched_time_sorts:
            for time in (set(db_times.keys()) - batched_time_times):
                q = make_batched_time_query(sr, sort, time)
                results.append(q)

        add_queries(results, insert_items = item)

        sr.last_valid_vote = datetime.now(g.tz)
        sr._commit()
    
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

def new_message(message, inbox_rels):
    from r2.lib.comment_tree import add_message

    from_user = Account._byID(message.author_id)
    for inbox_rel in tup(inbox_rels):
        to = inbox_rel._thing1
        # moderator message
        if isinstance(inbox_rel, ModeratorInbox):
            add_queries([get_subreddit_messages(to)],
                        insert_items = inbox_rel)
        # personal message
        else:
            add_queries([get_sent(from_user)], insert_items = message)
            add_queries([get_inbox_messages(to)],
                        insert_items = inbox_rel)
        set_unread(message, to, True)

    add_message(message)

def set_unread(message, to, unread):
    if isinstance(to, Subreddit):
        for i in ModeratorInbox.set_unread(message, unread):
            kw = dict(insert_items = i) if unread else dict(delete_items = i)
            add_queries([get_unread_subreddit_messages(i._thing1)], **kw)
    else:
        for i in Inbox.set_unread(message, unread):
            kw = dict(insert_items = i) if unread else dict(delete_items = i)
            if i._name == 'selfreply':
                add_queries([get_unread_selfreply(i._thing1)], **kw)
            elif isinstance(message, Comment):
                add_queries([get_unread_comments(i._thing1)], **kw)
            else:
                add_queries([get_unread_messages(i._thing1)], **kw)

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

def changed(things):
    """Indicate to solrsearch that a given item should be updated"""
    things = tup(things)
    for thing in things:
        amqp.add_item('searchchanges_q', thing._fullname,
                      message_id = thing._fullname)

def _by_srid(things):
    """Takes a list of things and returns them in a dict separated by
       sr_id, in addition to the looked-up subreddits"""
    ret = {}

    for thing in tup(things):
        if getattr(thing, 'sr_id', None) is not None:
            ret.setdefault(thing.sr_id, []).append(thing)

    srs = Subreddit._byID(ret.keys(), return_dict=True) if ret else {}

    return ret, srs

def ban(things):
    del_or_ban(things, "ban")

def delete_links(links):
    del_or_ban(links, "del")

def del_or_ban(things, why):
    by_srid, srs = _by_srid(things)
    if not by_srid:
        return

    for sr_id, things in by_srid.iteritems():
        sr = srs[sr_id]
        links = [x for x in things if isinstance(x, Link)]
        comments = [x for x in things if isinstance(x, Comment)]

        if links:
            if why == "ban":
                add_queries([get_spam_links(sr)], insert_items = links)
            # rip it out of the listings. bam!
            results = [get_links(sr, 'hot', 'all'),
                       get_links(sr, 'new', 'all')]

            for sort in batched_time_sorts:
                for time in db_times.keys():
                    # this will go through delete_items, so handling
                    # of batched_time_times isn't necessary and is
                    # included only for consistancy
                    q = make_batched_time_query(sr, sort, time)

            add_queries(results, delete_items = links)

        if comments:
            # add_queries([get_spam_comments(sr)], insert_items = comments)
            add_queries([get_all_comments()], delete_items = comments)

    changed(things)

def unban(things):
    by_srid, srs = _by_srid(things)
    if not by_srid:
        return

    for sr_id, things in by_srid.iteritems():
        sr = srs[sr_id]
        links = [x for x in things if isinstance(x, Link)]
        comments = [x for x in things if isinstance(x, Comment)]

        if links:
            add_queries([get_spam_links(sr)], delete_items = links)
            # put it back in the listings
            results = [get_links(sr, 'hot', 'all'),
                       get_links(sr, 'new', 'all')]
            for sort in batched_time_sorts:
                for time in db_times.keys():
                    # skip the preflight check because we need to redo
                    # this query regardless
                    q = make_batched_time_query(sr, sort, time,
                                                preflight_check=False)
                    results.append(q)

            add_queries(results, insert_items = links)

        if comments:
            #add_queries([get_spam_comments(sr)], delete_items = comments)
            add_queries([get_all_comments()], insert_items = comments)

    changed(things)

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
        add_queries(all_queries(get_links, sr, ('hot', 'new'), ['all']))
        add_queries(all_queries(get_links, sr, ('top', 'controversial'), db_times.keys()))
        add_queries([get_spam_links(sr),
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
               get_inbox_selfreply(user),
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

def add_comment_tree(comment, link):
    #update the comment cache
    add_comment(comment)
    #update last modified
    set_last_modified(link, 'comments')

# amqp queue processing functions

def run_new_comments():
    """Add new incoming comments to the /comments page"""
    # this is done as a queue because otherwise the contention for the
    # lock on the query would be very high

    def _run_new_comments(msgs, chan):
        fnames = [msg.body for msg in msgs]
        comments = Comment._by_fullname(fnames, data=True, return_dict=False)

        add_queries([get_all_comments()],
                    insert_items = comments)

    amqp.handle_items('newcomments_q', _run_new_comments, limit=100)

def run_commentstree():
    """Add new incoming comments to their respective comments trees"""

    def _run_commentstree(msgs, chan):
        fnames = [msg.body for msg in msgs]
        comments = Comment._by_fullname(fnames, data=True, return_dict=False)

        links = Link._byID(set(cm.link_id for cm in comments),
                           data=True,
                           return_dict=True)

        # add the comment to the comments-tree
        for comment in comments:
            l = links[comment.link_id]
            try:
                add_comment_tree(comment, l)
            except KeyError:
                # Hackity hack. Try to recover from a corrupted
                # comment tree
                print "Trying to fix broken comments-tree."
                link_comments(l._id, _update=True)
                add_comment_tree(comment, l)

    amqp.handle_items('commentstree_q', _run_commentstree, limit=1)


#def run_new_links():
#    """queue to add new links to the 'new' page. note that this isn't
#       in use until the spam_q plumbing is"""
#
#    def _run_new_links(msgs, chan):
#        fnames = [ msg.body for msg in msgs ]
#        links = Link._by_fullname(fnames, data=True, return_dict=False)
#
#        srs = Subreddit._byID([l.sr_id for l in links], return_dict=True)
#
#        results = []
#
#        _sr = lambda l: l.sr_id
#        for sr_id, sr_links in itertools.groupby(sorted(links, key=_sr),
#                                                 key=_sr):
#            sr = srs[sr_id]
#            results = [get_links(sr, 'new', 'all')]
#            add_queries(results, insert_items = sr_links)
#
#    amqp.handle_items('newpage_q', _run_new_links, limit=100)


def queue_vote(user, thing, dir, ip, organic = False,
               cheater = False, store = True):
    # set the vote in memcached so the UI gets updated immediately
    key = "registered_vote_%s_%s" % (user._id, thing._fullname)
    g.cache.set(key, '1' if dir is True else '0' if dir is None else '-1')
    # queue the vote to be stored unless told not to
    if store:
        if g.amqp_host:
            amqp.add_item('register_vote_q',
                          pickle.dumps((user._id, thing._fullname,
                                        dir, ip, organic, cheater)))
        else:
            handle_vote(user, thing, dir, ip, organic)

def get_likes(user, items):
    if not user or not items:
        return {}
    keys = {}
    res = {}
    for i in items:
        keys['registered_vote_%s_%s' % (user._id, i._fullname)] = (user, i)
    r = g.cache.get_multi(keys.keys())

    # populate the result set based on what we fetched from the cache first
    for k, v in r.iteritems():
        res[keys[k]] = v

    # now hit the vote db with the remainder
    likes = Vote.likes(user, [i for i in items if (user, i) not in res])

    for k, v in likes.iteritems():
        res[k] = v._name

    # lastly, translate into boolean:
    for k in res.keys():
        res[k] = (True if res[k] == '1'
                  else False if res[k] == '-1' else None)

    return res

def handle_vote(user, thing, dir, ip, organic, cheater = False):
    from r2.lib.db import tdb_sql
    from sqlalchemy.exc import IntegrityError
    try:
        v = Vote.vote(user, thing, dir, ip, organic, cheater = cheater)
    except (tdb_sql.CreationError, IntegrityError):
        g.log.error("duplicate vote for: %s" % str((user, thing, dir)))
        return

    # keep track of upvotes in the hard cache by subreddit
    sr_id = getattr(thing, "sr_id", None)
    if (sr_id and dir > 0 and getattr(thing, "author_id", None) != user._id
        and v.valid_thing):
        now = datetime.now(g.tz).strftime("%Y/%m/%d")
        g.hardcache.add("subreddit_vote-%s_%s_%s" % (now, sr_id, user._id),
                        sr_id, time = 86400 * 7) # 1 week for now

    if isinstance(thing, Link):
        new_vote(v)
        if v.valid_thing:
            expire_hot(thing.subreddit_slow)

        #update the modified flags
        set_last_modified(user, 'liked')
        if user._id == thing.author_id:
            set_last_modified(user, 'overview')
            set_last_modified(user, 'submitted')
            #update sup listings
            sup.add_update(user, 'submitted')

            #update sup listings
            if dir:
                sup.add_update(user, 'liked')
            elif dir is False:
                sup.add_update(user, 'disliked')

    elif isinstance(thing, Comment):
        #update last modified
        if user._id == thing.author_id:
            set_last_modified(user, 'overview')
            set_last_modified(user, 'commented')
            #update sup listings
            sup.add_update(user, 'commented')


def process_votes(drain = False, limit = 100):

    def _handle_votes(msgs, chan):
        to_do = []
        uids = set()
        tids = set()
        for x in msgs:
            r = pickle.loads(x.body)
            uid, tid, dir, ip, organic, cheater = r

            print (uid, tid, dir, ip, organic, cheater)

            uids.add(uid)
            tids.add(tid)
            to_do.append((uid, tid, dir, ip, organic, cheater))

        users = Account._byID(uids, data = True, return_dict = True)
        things = Thing._by_fullname(tids, data = True, return_dict = True)

        for uid, tid, dir, ip, organic, cheater in to_do:
            handle_vote(users[uid], things[tid], dir, ip, organic,
                        cheater = cheater)

    amqp.handle_items('register_vote_q', _handle_votes, limit = limit,
                      drain = drain)

def catch_up_batch_queries():
    # catch up on batched_time_times queries that haven't been run
    # that should be, This should be cronned to run about once an
    # hour. The more often, the more the work of rerunning the actual
    # queries is spread out, but every run has a fixed-cost of looking
    # at every single subreddit
    sr_q = Subreddit._query(sort=desc('_downs'),
                            data=True)
    dayago = utils.timeago('1 day')
    for sr in fetch_things2(sr_q):
        if hasattr(sr, 'last_valid_vote') and sr.last_valid_vote > dayago:
            # if we don't know when the last vote was, it couldn't
            # have been today
            for sort in batched_time_sorts:
                for time in batched_time_times:
                    q = make_batched_time_query(sr, sort, time)
                    if q.preflight_check():
                        # we haven't run the batched_time_times in the
                        # last day
                        add_queries([q])

    # make sure that all of the jobs have been completed or processed
    # by the time we return
    worker.join()

try:
    from r2admin.lib.admin_queries import *
except ImportError:
    pass
