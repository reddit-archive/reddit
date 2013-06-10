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

from r2.models import Account, Link, Comment, Vote, Report
from r2.models import Message, Inbox, Subreddit, ModContribSR, ModeratorInbox, MultiReddit
from r2.lib.db.thing import Thing, Merge
from r2.lib.db.operators import asc, desc, timeago
from r2.lib.db.sorts import epoch_seconds
from r2.lib.utils import fetch_things2, tup, UniqueIterator, set_last_modified
from r2.lib import utils
from r2.lib import amqp, sup, filters
from r2.lib.comment_tree import add_comments, update_comment_votes
from r2.models.promo import PROMOTE_STATUS, get_promote_srid
from r2.models.query_cache import (
    cached_query,
    CachedQuery,
    CachedQueryMutator,
    filter_thing,
    merged_cached_query,
    MergedCachedQuery,
    SubredditQueryCache,
    ThingTupleComparator,
    UserQueryCache,
)
from r2.models.last_modified import LastModified
from r2.lib.utils import SimpleSillyStub

import cPickle as pickle

from datetime import datetime
from time import mktime
import pytz
import itertools
import collections
from copy import deepcopy
from r2.lib.db.operators import and_, or_

from pylons import g
query_cache = g.permacache
log = g.log
make_lock = g.make_lock
worker = amqp.worker
stats = g.stats

precompute_limit = 1000

db_sorts = dict(hot = (desc, '_hot'),
                new = (desc, '_date'),
                top = (desc, '_score'),
                controversial = (desc, '_controversy'))

def db_sort(sort):
    cls, col = db_sorts[sort]
    return cls(col)

db_times = dict(all = None,
                hour = Thing.c._date >= timeago('1 hour'),
                day = Thing.c._date >= timeago('1 day'),
                week = Thing.c._date >= timeago('1 week'),
                month = Thing.c._date >= timeago('1 month'),
                year = Thing.c._date >= timeago('1 year'))

# sorts for which there can be a time filter (by day, by week,
# etc). All of these but 'all' are done in mr_top, who knows about the
# structure of the stored CachedResults (so changes here may warrant
# changes there)
time_filtered_sorts = set(('top', 'controversial'))

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

    @property
    def sort(self):
        return self.query._sort

    def fetch(self, force=False):
        """Loads the query from the cache."""
        self.fetch_multi([self], force=force)

    @classmethod
    def fetch_multi(cls, crs, force=False):
        unfetched = filter(lambda cr: force or not cr._fetched, crs)
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
        "True if a item can be removed from the listing, always true for now."
        return True

    def _mutate(self, fn, willread=True):
        self.data = query_cache.mutate(self.iden, fn, default=[], willread=willread)
        self._fetched=True

    def insert(self, items):
        """Inserts the item into the cached data. This only works
           under certain criteria, see can_insert."""
        self._insert_tuples([self.make_item_tuple(item) for item in tup(items)])

    def _insert_tuples(self, t):
        def _mutate(data):
            data = data or []

            # short-circuit if we already know that no item to be
            # added qualifies to be stored. Since we know that this is
            # sorted descending by datum[1:], we can just check the
            # last item and see if we're smaller than it is
            if (len(data) >= precompute_limit
                and all(x[1:] < data[-1][1:]
                        for x in t)):
                return data

            # insert the new items, remove the duplicates (keeping the
            # one being inserted over the stored value if applicable),
            # and sort the result
            newfnames = set(x[0] for x in t)
            data = filter(lambda x: x[0] not in newfnames, data)
            data.extend(t)
            data.sort(reverse=True, key=lambda x: x[1:])
            if len(t) + len(data) > precompute_limit:
                data = data[:precompute_limit]
            return data

        self._mutate(_mutate)

    def delete(self, items):
        """Deletes an item from the cached data."""
        fnames = set(self.filter(x)._fullname for x in tup(items))

        def _mutate(data):
            data = data or []
            return filter(lambda x: x[0] not in fnames,
                          data)

        self._mutate(_mutate)

    def _replace(self, tuples):
        """Take pre-rendered tuples from mr_top and replace the
           contents of the query outright. This should be considered a
           private API"""
        def _mutate(data):
            return tuples
        self._mutate(_mutate, willread=False)

    def update(self):
        """Runs the query and stores the result in the cache. This is
           only run by hand."""
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
        CachedQuery._fetch_multi([r for r in results
                                   if isinstance(r, CachedQuery)])
        self._fetched = True

        self.sort = results[0].sort
        comparator = ThingTupleComparator(self.sort)
        # make sure they're all the same
        assert all(r.sort == self.sort for r in results[1:])

        all_items = []
        for cr in results:
            all_items.extend(cr.data)
        all_items.sort(cmp=comparator)
        self.data = all_items


    def __repr__(self):
        return '<MergedCachedResults %r>' % (self.cached_results,)

    def __iter__(self):
        for x in self.data:
            yield x[0]

    def update(self):
        for x in self.cached_results:
            x.update()

def make_results(query, filter = filter_identity):
    return CachedResults(query, filter)

def merge_results(*results):
    if not results:
        return []
    return MergedCachedResults(results)

def migrating_cached_query(model, filter_fn=filter_identity):
    """Returns a CachedResults object that has a new-style cached query
    attached as "new_query". This way, reads will happen from the old
    query cache while writes can be made to go to both caches until a
    backfill migration is complete."""

    decorator = cached_query(model, filter_fn)
    def migrating_cached_query_decorator(fn):
        wrapped = decorator(fn)
        def migrating_cached_query_wrapper(*args):
            new_query = wrapped(*args)
            old_query = make_results(new_query.query, filter_fn)
            old_query.new_query = new_query
            return old_query
        return migrating_cached_query_wrapper
    return migrating_cached_query_decorator


@cached_query(UserQueryCache)
def get_deleted_links(user_id):
    return Link._query(Link.c.author_id == user_id,
                       Link.c._deleted == True,
                       Link.c._spam == (True, False),
                       sort=db_sort('new'))


@cached_query(UserQueryCache)
def get_deleted_comments(user_id):
    return Comment._query(Comment.c.author_id == user_id,
                          Comment.c._deleted == True,
                          Comment.c._spam == (True, False),
                          sort=db_sort('new'))


@merged_cached_query
def get_deleted(user):
    return [get_deleted_links(user),
            get_deleted_comments(user)]


def get_links(sr, sort, time):
    return _get_links(sr._id, sort, time)

def _get_links(sr_id, sort, time):
    """General link query for a subreddit."""
    q = Link._query(Link.c.sr_id == sr_id,
                    sort = db_sort(sort),
                    data = True)

    if time != 'all':
        q._filter(db_times[time])

    res = make_results(q)

    return res

@cached_query(SubredditQueryCache)
def get_spam_links(sr_id):
    return Link._query(Link.c.sr_id == sr_id,
                       Link.c._spam == True,
                       sort = db_sort('new'))

@cached_query(SubredditQueryCache)
def get_spam_comments(sr_id):
    return Comment._query(Comment.c.sr_id == sr_id,
                          Comment.c._spam == True,
                          sort = db_sort('new'))

def moderated_srids(sr, user):
    if isinstance(sr, (ModContribSR, MultiReddit)):
        srs = Subreddit._byID(sr.sr_ids, return_dict=False)
        if user:
            srs = [sr for sr in srs
                   if sr.is_moderator_with_perms(user, 'posts')]
        return [sr._id for sr in srs]
    else:
        return [sr._id]

@merged_cached_query
def get_spam(sr, user=None, include_links=True, include_comments=True):
    sr_ids = moderated_srids(sr, user)
    queries = []

    if include_links:
        queries.append(get_spam_links)
    if include_comments:
        queries.append(get_spam_comments)
    return [query(sr_id) for sr_id, query in itertools.product(sr_ids, queries)]

@cached_query(SubredditQueryCache)
def get_spam_filtered_links(sr_id):
    """ NOTE: This query will never run unless someone does an "update" on it,
        but that will probably timeout. Use insert_spam_filtered_links."""
    return Link._query(Link.c.sr_id == sr_id,
                       Link.c._spam == True,
                       Link.c.verdict != 'mod-removed',
                       sort = db_sort('new'))

@cached_query(SubredditQueryCache)
def get_spam_filtered_comments(sr_id):
    return Comment._query(Comment.c.sr_id == sr_id,
                          Comment.c._spam == True,
                          Comment.c.verdict != 'mod-removed',
                          sort = db_sort('new'))

@merged_cached_query
def get_spam_filtered(sr):
    return [get_spam_filtered_links(sr),
            get_spam_filtered_comments(sr)]

@cached_query(SubredditQueryCache)
def get_reported_links(sr_id):
    return Link._query(Link.c.reported != 0,
                       Link.c.sr_id == sr_id,
                       Link.c._spam == False,
                       sort = db_sort('new'))

@cached_query(SubredditQueryCache)
def get_reported_comments(sr_id):
    return Comment._query(Comment.c.reported != 0,
                          Comment.c.sr_id == sr_id,
                          Comment.c._spam == False,
                          sort = db_sort('new'))

@merged_cached_query
def get_reported(sr, user=None, include_links=True, include_comments=True):
    sr_ids = moderated_srids(sr, user)
    queries = []

    if include_links:
        queries.append(get_reported_links)
    if include_comments:
        queries.append(get_reported_comments)
    return [query(sr_id) for sr_id, query in itertools.product(sr_ids, queries)]

@cached_query(SubredditQueryCache)
def get_unmoderated_links(sr_id):
    q = Link._query(Link.c.sr_id == sr_id,
                    Link.c._spam == (True, False),
                    sort = db_sort('new'))

    # Doesn't really work because will not return Links with no verdict
    q._filter(or_(and_(Link.c._spam == True, Link.c.verdict != 'mod-removed'),
                  and_(Link.c._spam == False, Link.c.verdict != 'mod-approved')))
    return q

@merged_cached_query
def get_modqueue(sr, user=None, include_links=True, include_comments=True):
    sr_ids = moderated_srids(sr, user)
    queries = []

    if include_links:
        queries.append(get_reported_links)
        queries.append(get_spam_filtered_links)
    if include_comments:
        queries.append(get_reported_comments)
        queries.append(get_spam_filtered_comments)
    return [query(sr_id) for sr_id, query in itertools.product(sr_ids, queries)]

@merged_cached_query
def get_unmoderated(sr, user=None):
    sr_ids = moderated_srids(sr, user)
    queries = [get_unmoderated_links]
    return [query(sr_id) for sr_id, query in itertools.product(sr_ids, queries)]

def get_domain_links(domain, sort, time):
    from r2.lib.db import operators
    q = Link._query(operators.domain(Link.c.url) == filters._force_utf8(domain),
                    sort = db_sort(sort),
                    data = True)
    if time != "all":
        q._filter(db_times[time])

    return make_results(q)

def user_query(kind, user_id, sort, time):
    """General profile-page query."""
    q = kind._query(kind.c.author_id == user_id,
                    kind.c._spam == (True, False),
                    sort = db_sort(sort))
    if time != 'all':
        q._filter(db_times[time])
    return make_results(q)

def get_all_comments():
    """the master /comments page"""
    q = Comment._query(sort = desc('_date'))
    return make_results(q)

def get_sr_comments(sr):
    return _get_sr_comments(sr._id)

def _get_sr_comments(sr_id):
    """the subreddit /r/foo/comments page"""
    q = Comment._query(Comment.c.sr_id == sr_id,
                       sort = desc('_date'))
    return make_results(q)

def _get_comments(user_id, sort, time):
    return user_query(Comment, user_id, sort, time)

def get_comments(user, sort, time):
    return _get_comments(user._id, sort, time)

def _get_submitted(user_id, sort, time):
    return user_query(Link, user_id, sort, time)

def get_submitted(user, sort, time):
    return _get_submitted(user._id, sort, time)

def get_overview(user, sort, time):
    return merge_results(get_comments(user, sort, time),
                         get_submitted(user, sort, time))

def rel_query(rel, thing_id, name, filters = []):
    """General relationship query."""

    q = rel._query(rel.c._thing1_id == thing_id,
                   rel.c._t2_deleted == False,
                   rel.c._name == name,
                   sort = desc('_date'),
                   eager_load = True,
                   )
    if filters:
        q._filter(*filters)

    return q

vote_rel = Vote.rel(Account, Link)

cached_userrel_query = cached_query(UserQueryCache, filter_thing2)
cached_srrel_query = cached_query(SubredditQueryCache, filter_thing2)

@cached_userrel_query
def get_liked(user):
    return rel_query(vote_rel, user, '1')

@cached_userrel_query
def get_disliked(user):
    return rel_query(vote_rel, user, '-1')

@cached_query(UserQueryCache, sort=[desc('action_date')])
def get_hidden_links(user_id):
    return

def get_hidden(user):
    return get_hidden_links(user)

@cached_query(UserQueryCache, sort=[desc('action_date')])
def get_saved_links(user_id, sr_id):
    return

@cached_query(UserQueryCache, sort=[desc('action_date')])
def get_saved_comments(user_id, sr_id):
    return

def get_saved(user, sr_id=None):
    sr_id = sr_id or 'none'
    queries = [get_saved_links(user, sr_id), get_saved_comments(user, sr_id)]
    return MergedCachedQuery(queries)

@cached_srrel_query
def get_subreddit_messages(sr):
    return rel_query(ModeratorInbox, sr, 'inbox')

@cached_srrel_query
def get_unread_subreddit_messages(sr):
    return rel_query(ModeratorInbox, sr, 'inbox',
                          filters = [ModeratorInbox.c.new == True])

def get_unread_subreddit_messages_multi(srs):
    if not srs:
        return []
    queries = [get_unread_subreddit_messages(sr) for sr in srs]
    return MergedCachedQuery(queries)

inbox_message_rel = Inbox.rel(Account, Message)
@cached_userrel_query
def get_inbox_messages(user):
    return rel_query(inbox_message_rel, user, 'inbox')

@cached_userrel_query
def get_unread_messages(user):
    return rel_query(inbox_message_rel, user, 'inbox',
                          filters = [inbox_message_rel.c.new == True])

inbox_comment_rel = Inbox.rel(Account, Comment)
@cached_userrel_query
def get_inbox_comments(user):
    return rel_query(inbox_comment_rel, user, 'inbox')

@cached_userrel_query
def get_unread_comments(user):
    return rel_query(inbox_comment_rel, user, 'inbox',
                          filters = [inbox_comment_rel.c.new == True])

@cached_userrel_query
def get_inbox_selfreply(user):
    return rel_query(inbox_comment_rel, user, 'selfreply')

@cached_userrel_query
def get_unread_selfreply(user):
    return rel_query(inbox_comment_rel, user, 'selfreply',
                          filters = [inbox_comment_rel.c.new == True])


@cached_userrel_query
def get_inbox_comment_mentions(user):
    return rel_query(inbox_comment_rel, user, "mention")


@cached_userrel_query
def get_unread_comment_mentions(user):
    return rel_query(inbox_comment_rel, user, "mention",
                     filters=[inbox_comment_rel.c.new == True])


def get_inbox(user):
    return merge_results(get_inbox_comments(user),
                         get_inbox_messages(user),
                         get_inbox_comment_mentions(user),
                         get_inbox_selfreply(user))

@cached_query(UserQueryCache)
def get_sent(user_id):
    return Message._query(Message.c.author_id == user_id,
                          Message.c._spam == (True, False),
                          sort = desc('_date'))

def get_unread_inbox(user):
    return merge_results(get_unread_comments(user),
                         get_unread_messages(user),
                         get_unread_comment_mentions(user),
                         get_unread_selfreply(user))

def _user_reported_query(user_id, thing_cls):
    rel_cls = Report.rel(Account, thing_cls)
    return rel_query(rel_cls, user_id, ('-1', '0', '1'))
    # -1: rejected report
    # 0: unactioned report
    # 1: accepted report

@cached_userrel_query
def get_user_reported_links(user_id):
    return _user_reported_query(user_id, Link)

@cached_userrel_query
def get_user_reported_comments(user_id):
    return _user_reported_query(user_id, Comment)

@cached_userrel_query
def get_user_reported_messages(user_id):
    return _user_reported_query(user_id, Message)

@merged_cached_query
def get_user_reported(user_id):
    return [get_user_reported_links(user_id),
            get_user_reported_comments(user_id),
            get_user_reported_messages(user_id)]


def set_promote_status(link, promote_status):
    all_queries = [promote_query(link.author_id) for promote_query in 
                   (get_unpaid_links, get_unapproved_links, 
                    get_rejected_links, get_live_links, get_accepted_links)]
    all_queries.extend([get_all_unpaid_links(), get_all_unapproved_links(),
                        get_all_rejected_links(), get_all_live_links(),
                        get_all_accepted_links()])

    if promote_status == PROMOTE_STATUS.unpaid:
        inserts = [get_unpaid_links(link.author_id), get_all_unpaid_links()]
    elif promote_status == PROMOTE_STATUS.unseen:
        inserts = [get_unapproved_links(link.author_id),
                   get_all_unapproved_links()]
    elif promote_status == PROMOTE_STATUS.rejected:
        inserts = [get_rejected_links(link.author_id), get_all_rejected_links()]
    elif promote_status == PROMOTE_STATUS.promoted:
        inserts = [get_live_links(link.author_id), get_all_live_links()]
    elif promote_status in (PROMOTE_STATUS.accepted, PROMOTE_STATUS.pending,
                            PROMOTE_STATUS.finished):
        inserts = [get_accepted_links(link.author_id), get_all_accepted_links()]

    deletes = list(set(all_queries) - set(inserts))
    with CachedQueryMutator() as m:
        for q in inserts:
            m.insert(q, [link])
        for q in deletes:
            m.delete(q, [link])

    link.promote_status = promote_status
    link._commit()


def _promoted_link_query(user_id, status):
    STATUS_CODES = {'unpaid': PROMOTE_STATUS.unpaid,
                    'unapproved': PROMOTE_STATUS.unseen,
                    'rejected': PROMOTE_STATUS.rejected,
                    'live': PROMOTE_STATUS.promoted,
                    'accepted': (PROMOTE_STATUS.accepted,
                                 PROMOTE_STATUS.pending,
                                 PROMOTE_STATUS.finished)}

    q = Link._query(Link.c.sr_id == get_promote_srid(),
                    Link.c._spam == (True, False),
                    Link.c._deleted == (True, False),
                    Link.c.promote_status == STATUS_CODES[status],
                    sort=db_sort('new'))
    if user_id:
        q._filter(Link.c.author_id == user_id)
    return q


@cached_query(UserQueryCache)
def get_unpaid_links(user_id):
    return _promoted_link_query(user_id, 'unpaid')


@cached_query(UserQueryCache)
def get_all_unpaid_links():
    return _promoted_link_query(None, 'unpaid')


@cached_query(UserQueryCache)
def get_unapproved_links(user_id):
    return _promoted_link_query(user_id, 'unapproved')


@cached_query(UserQueryCache)
def get_all_unapproved_links():
    return _promoted_link_query(None, 'unapproved')


@cached_query(UserQueryCache)
def get_rejected_links(user_id):
    return _promoted_link_query(user_id, 'rejected')


@cached_query(UserQueryCache)
def get_all_rejected_links():
    return _promoted_link_query(None, 'rejected')


@cached_query(UserQueryCache)
def get_live_links(user_id):
    return _promoted_link_query(user_id, 'live')


@cached_query(UserQueryCache)
def get_all_live_links():
    return _promoted_link_query(None, 'live')


@cached_query(UserQueryCache)
def get_accepted_links(user_id):
    return _promoted_link_query(user_id, 'accepted')


@cached_query(UserQueryCache)
def get_all_accepted_links():
    return _promoted_link_query(None, 'accepted')


@merged_cached_query
def get_promoted_links(user_id):
    queries = [get_unpaid_links(user_id), get_unapproved_links(user_id),
               get_rejected_links(user_id), get_live_links(user_id),
               get_accepted_links(user_id)]
    return queries


@merged_cached_query
def get_all_promoted_links():
    queries = [get_all_unpaid_links(), get_all_unapproved_links(),
               get_all_rejected_links(), get_all_live_links(),
               get_all_accepted_links()]
    return queries


@cached_query(SubredditQueryCache, sort=[desc("date")], filter_fn=filter_thing)
def get_all_gilded_comments():
    return


@cached_query(SubredditQueryCache, sort=[desc("date")], filter_fn=filter_thing)
def get_gilded_comments(sr_id):
    return


def add_queries(queries, insert_items=None, delete_items=None, foreground=False):
    """Adds multiple queries to the query queue. If insert_items or
       delete_items is specified, the query may not need to be
       recomputed against the database."""
    for q in queries:
        if insert_items and q.can_insert():
            log.debug("Inserting %s into query %s" % (insert_items, q))
            if foreground:
                q.insert(insert_items)
            else:
                worker.do(q.insert, insert_items)
        elif delete_items and q.can_delete():
            log.debug("Deleting %s from query %s" % (delete_items, q))
            if foreground:
                q.delete(delete_items)
            else:
                worker.do(q.delete, delete_items)
        else:
            raise Exception("Cannot update query %r!" % (q,))

    # dual-write any queries that are being migrated to the new query cache
    with CachedQueryMutator() as m:
        new_queries = [getattr(q, 'new_query') for q in queries if hasattr(q, 'new_query')]

        if insert_items:
            for query in new_queries:
                m.insert(query, tup(insert_items))

        if delete_items:
            for query in new_queries:
                m.delete(query, tup(delete_items))

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

    for domain in utils.UrlParser(link.url).domain_permutations():
        results.append(get_domain_links(domain, 'new', "all"))

    with CachedQueryMutator() as m:
        if link._spam:    
            m.insert(get_spam_links(sr), [link])
        m.insert(get_unmoderated_links(sr), [link])

    add_queries(results, insert_items = link)
    amqp.add_item('new_link', link._fullname)


def new_comment(comment, inbox_rels):
    author = Account._byID(comment.author_id)
    job = [get_comments(author, 'new', 'all'),
           get_comments(author, 'top', 'all'),
           get_comments(author, 'controversial', 'all')]

    sr = Subreddit._byID(comment.sr_id)

    with CachedQueryMutator() as m:
        if comment._deleted:
            job_key = "delete_items"
            job.append(get_sr_comments(sr))
            job.append(get_all_comments())
        else:
            job_key = "insert_items"
            if comment._spam:
                m.insert(get_spam_comments(sr), [comment])
            if (was_spam_filtered(comment) and
                    not (sr.exclude_banned_modqueue and author._spam)):
                m.insert(get_spam_filtered_comments(sr), [comment])

            amqp.add_item('new_comment', comment._fullname)

            if utils.to36(comment.link_id) in g.live_config["fastlane_links"]:
                amqp.add_item('commentstree_fastlane_q', comment._fullname)
            elif g.shard_commentstree_queues:
                amqp.add_item('commentstree_%d_q' % (comment.link_id % 10),
                              comment._fullname)
            else:
                amqp.add_item('commentstree_q', comment._fullname)

            if not g.amqp_host:
                add_comments([comment])

        job_dict = { job_key: comment }
        add_queries(job, **job_dict)

        # note that get_all_comments() is updated by the amqp process
        # r2.lib.db.queries.run_new_comments (to minimise lock contention)

        if inbox_rels:
            for inbox_rel in tup(inbox_rels):
                inbox_owner = inbox_rel._thing1
                if inbox_rel._name == "inbox":
                    query = get_inbox_comments(inbox_owner)
                elif inbox_rel._name == "selfreply":
                    query = get_inbox_selfreply(inbox_owner)
                else:
                    raise ValueError("wtf is " + inbox_rel._name)

                # mentions happen in butler_q

                if not comment._deleted:
                    m.insert(query, [inbox_rel])
                else:
                    m.delete(query, [inbox_rel])

                set_unread(comment, inbox_owner,
                           unread=not comment._deleted, mutator=m)


def new_subreddit(sr):
    "no precomputed queries here yet"
    amqp.add_item('new_subreddit', sr._fullname)


def new_vote(vote, foreground=False, timer=None):
    user = vote._thing1
    item = vote._thing2

    if timer is None:
        timer = SimpleSillyStub()

    if not isinstance(item, (Link, Comment)):
        return

    if vote.valid_thing and not item._spam and not item._deleted:
        sr = item.subreddit_slow
        results = []

        author = Account._byID(item.author_id)
        for sort in ('hot', 'top', 'controversial', 'new'):
            if isinstance(item, Link):
                results.append(get_submitted(author, sort, 'all'))
            if isinstance(item, Comment):
                results.append(get_comments(author, sort, 'all'))

        if isinstance(item, Link):
            # don't do 'new', because that was done by new_link, and
            # the time-filtered versions of top/controversial will be
            # done by mr_top
            results.extend([get_links(sr, 'hot', 'all'),
                            get_links(sr, 'top', 'all'),
                            get_links(sr, 'controversial', 'all'),
                            ])

            parsed = utils.UrlParser(item.url)
            if parsed.hostname and not parsed.hostname.endswith('imgur.com'):
                for domain in parsed.domain_permutations():
                    for sort in ("hot", "top", "controversial"):
                        results.append(get_domain_links(domain, sort, "all"))

        add_queries(results, insert_items = item, foreground=foreground)

    timer.intermediate("permacache")
    
    if isinstance(item, Link):
        # must update both because we don't know if it's a changed
        # vote
        with CachedQueryMutator() as m:
            if vote._name == '1':
                m.insert(get_liked(user), [vote])
                m.delete(get_disliked(user), [vote])
            elif vote._name == '-1':
                m.delete(get_liked(user), [vote])
                m.insert(get_disliked(user), [vote])
            else:
                m.delete(get_liked(user), [vote])
                m.delete(get_disliked(user), [vote])

def new_message(message, inbox_rels):
    from r2.lib.comment_tree import add_message

    from_user = Account._byID(message.author_id)
    for inbox_rel in tup(inbox_rels):
        to = inbox_rel._thing1

        with CachedQueryMutator() as m:
            m.insert(get_sent(from_user), [message])

            # moderator message
            if isinstance(inbox_rel, ModeratorInbox):
                m.insert(get_subreddit_messages(to), [inbox_rel])
            # personal message
            else:
                m.insert(get_inbox_messages(to), [inbox_rel])

            set_unread(message, to, unread=True, mutator=m)

    add_message(message)

def set_unread(messages, to, unread, mutator=None):
    # Maintain backwards compatability
    messages = tup(messages)

    if not mutator:
        m = CachedQueryMutator()
    else:
        m = mutator

    if isinstance(to, Subreddit):
        for i in ModeratorInbox.set_unread(messages, unread):
            q = get_unread_subreddit_messages(i._thing1_id)
            if unread:
                m.insert(q, [i])
            else:
                m.delete(q, [i])
    else:
        # All messages should be of the same type
        # (asserted by Inbox.set_unread)
        for i in Inbox.set_unread(messages, unread, to=to):
            query = None
            if isinstance(messages[0], Comment):
                if i._name == "inbox":
                    query = get_unread_comments(i._thing1_id)
                elif i._name == "selfreply":
                    query = get_unread_selfreply(i._thing1_id)
                elif i._name == "mention":
                    query = get_unread_comment_mentions(i._thing1_id)
            elif isinstance(messages[0], Message):
                query = get_unread_messages(i._thing1_id)
            assert query is not None

            if unread:
                m.insert(query, [i])
            else:
                m.delete(query, [i])

    if not mutator:
        m.send()


def changed(things, boost_only=False):
    """Indicate to search that a given item should be updated in the index"""
    for thing in tup(things):
        msg = {'fullname': thing._fullname}
        if boost_only:
            msg['boost_only'] = True

        amqp.add_item('search_changes', pickle.dumps(msg),
                      message_id = thing._fullname,
                      delivery_mode = amqp.DELIVERY_TRANSIENT)

def _by_srid(things, srs=True):
    """Takes a list of things and returns them in a dict separated by
       sr_id, in addition to the looked-up subreddits"""
    ret = {}

    for thing in tup(things):
        if getattr(thing, 'sr_id', None) is not None:
            ret.setdefault(thing.sr_id, []).append(thing)

    if srs:
        _srs = Subreddit._byID(ret.keys(), return_dict=True) if ret else {}
        return ret, _srs
    else:
        return ret


def _by_author(things, authors=True):
    ret = collections.defaultdict(list)

    for thing in tup(things):
        author_id = getattr(thing, 'author_id')
        if author_id:
            ret[author_id].append(thing)

    if authors:
        _authors = Account._byID(ret.keys(), return_dict=True) if ret else {}
        return ret, _authors
    else:
        return ret

def _by_thing1_id(rels):
    ret = {}
    for rel in tup(rels):
        ret.setdefault(rel._thing1_id, []).append(rel)
    return ret


def was_spam_filtered(thing):
    if (thing._spam and not thing._deleted and
        getattr(thing, 'verdict', None) != 'mod-removed'):
        return True
    else:
        return False


def delete(things):
    query_cache_inserts, query_cache_deletes = _common_del_ban(things)
    by_srid, srs = _by_srid(things)
    by_author, authors = _by_author(things)

    for sr_id, sr_things in by_srid.iteritems():
        sr = srs[sr_id]
        links = [x for x in sr_things if isinstance(x, Link)]
        comments = [x for x in sr_things if isinstance(x, Comment)]

        if links:
            query_cache_deletes.append((get_spam_links(sr), links))
            query_cache_deletes.append((get_spam_filtered_links(sr), links))
            query_cache_deletes.append((get_unmoderated_links(sr_id),
                                            links))
        if comments:
            query_cache_deletes.append((get_spam_comments(sr), comments))
            query_cache_deletes.append((get_spam_filtered_comments(sr),
                                        comments))

    for author_id, a_things in by_author.iteritems():
        author = authors[author_id]
        links = [x for x in a_things if isinstance(x, Link)]
        comments = [x for x in a_things if isinstance(x, Comment)]

        if links:
            results = [get_submitted(author, 'hot', 'all'),
                       get_submitted(author, 'new', 'all')]
            for sort in time_filtered_sorts:
                for time in db_times.keys():
                    results.append(get_submitted(author, sort, time))
            add_queries(results, delete_items=links)
            query_cache_inserts.append((get_deleted_links(author_id), links))
        if comments:
            results = [get_comments(author, 'hot', 'all'),
                       get_comments(author, 'new', 'all')]
            for sort in time_filtered_sorts:
                for time in db_times.keys():
                    results.append(get_comments(author, sort, time))
            add_queries(results, delete_items=comments)
            query_cache_inserts.append((get_deleted_comments(author_id),
                                        comments))

    with CachedQueryMutator() as m:
        for q, inserts in query_cache_inserts:
            m.insert(q, inserts)
        for q, deletes in query_cache_deletes:
            m.delete(q, deletes)
    changed(things)


def ban(things, filtered=True):
    query_cache_inserts, query_cache_deletes = _common_del_ban(things)
    by_srid = _by_srid(things, srs=False)

    for sr_id, sr_things in by_srid.iteritems():
        links = []
        modqueue_links = []
        comments = []
        modqueue_comments = []
        for item in sr_things:
            # don't add posts by banned users if subreddit prefs exclude them
            add_to_modqueue = (filtered and
                       not (item.subreddit_slow.exclude_banned_modqueue and
                            item.author_slow._spam))

            if isinstance(item, Link):
                links.append(item)
                if add_to_modqueue:
                    modqueue_links.append(item)
            elif isinstance(item, Comment):
                comments.append(item)
                if add_to_modqueue:
                    modqueue_comments.append(item)

        if links:
            query_cache_inserts.append((get_spam_links(sr_id), links))
            if not filtered:
                query_cache_deletes.append(
                        (get_spam_filtered_links(sr_id), links))
                query_cache_deletes.append(
                        (get_unmoderated_links(sr_id), links))

        if modqueue_links:
            query_cache_inserts.append(
                    (get_spam_filtered_links(sr_id), modqueue_links))

        if comments:
            query_cache_inserts.append((get_spam_comments(sr_id), comments))
            if not filtered:
                query_cache_deletes.append(
                        (get_spam_filtered_comments(sr_id), comments))

        if modqueue_comments:
            query_cache_inserts.append(
                    (get_spam_filtered_comments(sr_id), modqueue_comments))

    with CachedQueryMutator() as m:
        for q, inserts in query_cache_inserts:
            m.insert(q, inserts)
        for q, deletes in query_cache_deletes:
            m.delete(q, deletes)
    changed(things)


def _common_del_ban(things):
    query_cache_inserts = []
    query_cache_deletes = []
    by_srid, srs = _by_srid(things)

    for sr_id, sr_things in by_srid.iteritems():
        sr = srs[sr_id]
        links = [x for x in sr_things if isinstance(x, Link)]
        comments = [x for x in sr_things if isinstance(x, Comment)]

        if links:
            results = [get_links(sr, 'hot', 'all'), get_links(sr, 'new', 'all')]
            for sort in time_filtered_sorts:
                for time in db_times.keys():
                    results.append(get_links(sr, sort, time))
            add_queries(results, delete_items=links)
            query_cache_deletes.append([get_reported_links(sr), links])
        if comments:
            query_cache_deletes.append([get_reported_comments(sr), comments])

    return query_cache_inserts, query_cache_deletes


def unban(things, insert=True):
    query_cache_deletes = []

    by_srid, srs = _by_srid(things)
    if not by_srid:
        return

    for sr_id, things in by_srid.iteritems():
        sr = srs[sr_id]
        links = [x for x in things if isinstance(x, Link)]
        comments = [x for x in things if isinstance(x, Comment)]

        if insert and links:
            # put it back in the listings
            results = [get_links(sr, 'hot', 'all'),
                       get_links(sr, 'top', 'all'),
                       get_links(sr, 'controversial', 'all'),
                       ]
            # the time-filtered listings will have to wait for the
            # next mr_top run
            add_queries(results, insert_items=links)

            # Check if link is being unbanned and should be put in
            # 'new' with current time
            new_links = []
            for l in links:
                ban_info = l.ban_info
                if ban_info.get('reset_used', True) == False and \
                    ban_info.get('auto', False):
                    l_copy = deepcopy(l)
                    l_copy._date = ban_info['unbanned_at']
                    new_links.append(l_copy)
                else:
                    new_links.append(l)
            add_queries([get_links(sr, 'new', 'all')], insert_items=new_links)
            query_cache_deletes.append([get_spam_links(sr), links])

        if insert and comments:
            add_queries([get_all_comments(), get_sr_comments(sr)],
                        insert_items=comments)
            query_cache_deletes.append([get_spam_comments(sr), comments])

        if links:
            query_cache_deletes.append((get_unmoderated_links(sr), links))
            query_cache_deletes.append([get_spam_filtered_links(sr), links])

        if comments:
            query_cache_deletes.append([get_spam_filtered_comments(sr), comments])

    with CachedQueryMutator() as m:
        for q, deletes in query_cache_deletes:
            m.delete(q, deletes)

    changed(things)

def new_report(thing, report_rel):
    reporter_id = report_rel._thing1_id

    with CachedQueryMutator() as m:
        if isinstance(thing, Link):
            m.insert(get_reported_links(thing.sr_id), [thing])
            m.insert(get_user_reported_links(reporter_id), [report_rel])
        elif isinstance(thing, Comment):
            m.insert(get_reported_comments(thing.sr_id), [thing])
            m.insert(get_user_reported_comments(reporter_id), [report_rel])
        elif isinstance(thing, Message):
            m.insert(get_user_reported_messages(reporter_id), [report_rel])


def clear_reports(things, rels):
    query_cache_deletes = []

    by_srid = _by_srid(things, srs=False)

    for sr_id, sr_things in by_srid.iteritems():
        links = [ x for x in sr_things if isinstance(x, Link) ]
        comments = [ x for x in sr_things if isinstance(x, Comment) ]

        if links:
            query_cache_deletes.append([get_reported_links(sr_id), links])
        if comments:
            query_cache_deletes.append([get_reported_comments(sr_id), comments])

    # delete from user_reported if the report was correct
    rels = [r for r in rels if r._name == '1']
    if rels:
        link_rels = [r for r in rels if r._type2 == Link]
        comment_rels = [r for r in rels if r._type2 == Comment]
        message_rels = [r for r in rels if r._type2 == Message]

        rels_to_query = ((link_rels, get_user_reported_links),
                         (comment_rels, get_user_reported_comments),
                         (message_rels, get_user_reported_messages))

        for thing_rels, query in rels_to_query:
            if not thing_rels:
                continue

            by_thing1_id = _by_thing1_id(thing_rels)
            for reporter_id, reporter_rels in by_thing1_id.iteritems():
                query_cache_deletes.append([query(reporter_id), reporter_rels])

    with CachedQueryMutator() as m:
        for q, deletes in query_cache_deletes:
            m.delete(q, deletes)


def add_all_srs():
    """Recalculates every listing query for every subreddit. Very,
       very slow."""
    q = Subreddit._query(sort = asc('_date'))
    for sr in fetch_things2(q):
        for q in all_queries(get_links, sr, ('hot', 'new'), ['all']):
            q.update()
        for q in all_queries(get_links, sr, time_filtered_sorts, db_times.keys()):
            q.update()
        get_spam_links(sr).update()
        get_spam_comments(sr).update()
        get_reported_links(sr).update()
        get_reported_comments(sr).update()

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
               get_submitted(user, 'new', 'all'),
               get_comments(user, 'new', 'all')]
    for q in results:
        q.update()

def add_all_users():
    q = Account._query(sort = asc('_date'))
    for user in fetch_things2(q):
        update_user(user)

# amqp queue processing functions

def run_new_comments(limit=1000):
    """Add new incoming comments to the /comments page"""
    # this is done as a queue because otherwise the contention for the
    # lock on the query would be very high

    @g.stats.amqp_processor('newcomments_q')
    def _run_new_comments(msgs, chan):
        fnames = [msg.body for msg in msgs]

        comments = Comment._by_fullname(fnames, data=True, return_dict=False)
        add_queries([get_all_comments()],
                    insert_items=comments)

        bysrid = _by_srid(comments, False)
        for srid, sr_comments in bysrid.iteritems():
            add_queries([_get_sr_comments(srid)],
                        insert_items=sr_comments)

    amqp.handle_items('newcomments_q', _run_new_comments, limit=limit)

def run_commentstree(qname="commentstree_q", limit=100):
    """Add new incoming comments to their respective comments trees"""

    @g.stats.amqp_processor(qname)
    def _run_commentstree(msgs, chan):
        comments = Comment._by_fullname([msg.body for msg in msgs],
                                        data = True, return_dict = False)
        print 'Processing %r' % (comments,)

        # when fastlaning a thread, we may need to have this qproc ignore
        # messages that were put into the non-fastlane queue and are causing
        # both to back up. a full recompute of the old thread will fix these
        # missed messages.
        if qname != "commentstree_fastlane_q":
            fastlaned_links = g.live_config["fastlane_links"]
            links = Link._byID([com.link_id for com in comments], data=True)
            comments = [com for com in comments
                        if utils.to36(com.link_id) not in fastlaned_links and
                           links[com.link_id].skip_commentstree_q != qname]

        if comments:
            add_comments(comments)

    amqp.handle_items(qname, _run_commentstree, limit = limit)

vote_link_q = 'vote_link_q'
vote_comment_q = 'vote_comment_q'
vote_fastlane_q = 'vote_fastlane_q'

def queue_vote(user, thing, dir, ip, organic = False,
               cheater = False, store = True):
    # set the vote in memcached so the UI gets updated immediately
    key = prequeued_vote_key(user, thing)
    g.cache.set(key, '1' if dir is True else '0' if dir is None else '-1')
    # queue the vote to be stored unless told not to
    if store:
        if g.amqp_host:
            if isinstance(thing, Link):
                if thing._id36 in g.live_config["fastlane_links"]:
                    qname = vote_fastlane_q
                else:
                    if g.shard_link_vote_queues:
                        qname = "vote_link_%s_q" % str(thing.sr_id)[-1]
                    else:
                        qname = vote_link_q

            elif isinstance(thing, Comment):
                if utils.to36(thing.link_id) in g.live_config["fastlane_links"]:
                    qname = vote_fastlane_q
                else:
                    qname = vote_comment_q
            else:
                log.warning("%s tried to vote on %r. that's not a link or comment!",
                            user, thing)
                return

            amqp.add_item(qname,
                          pickle.dumps((user._id, thing._fullname,
                                        dir, ip, organic, cheater)))
        else:
            handle_vote(user, thing, dir, ip, organic)

def prequeued_vote_key(user, item):
    return 'registered_vote_%s_%s' % (user._id, item._fullname)

def get_likes(user, items):
    if not user or not items:
        return {}

    res = {}

    # check the prequeued_vote_keys
    keys = {}
    for item in items:
        if (user, item) in res:
            continue

        key = prequeued_vote_key(user, item)
        keys[key] = (user, item)
    if keys:
        r = g.cache.get_multi(keys.keys())
        for key, v in r.iteritems():
            res[keys[key]] = (True if v == '1'
                              else False if v == '-1'
                              else None)

    for item in items:
        # already retrieved above
        if (user, item) in res:
            continue

        # we can only vote on links and comments
        if not isinstance(item, (Link, Comment)):
            res[(user, item)] = None

    likes = Vote.likes(user, [i for i in items if (user, i) not in res])

    res.update(likes)

    return res

def handle_vote(user, thing, dir, ip, organic,
                cheater=False, foreground=False, timer=None, date=None):
    if timer is None:
        timer = SimpleSillyStub()

    from r2.lib.db import tdb_sql
    from sqlalchemy.exc import IntegrityError
    try:
        v = Vote.vote(user, thing, dir, ip, organic, cheater = cheater,
                      timer=timer, date=date)
    except (tdb_sql.CreationError, IntegrityError):
        g.log.error("duplicate vote for: %s" % str((user, thing, dir)))
        return

    new_vote(v, foreground=foreground, timer=timer)

    timestamps = []
    if isinstance(thing, Link):

        #update the modified flags
        if user._id == thing.author_id:
            timestamps.append('Overview')
            timestamps.append('Submitted')
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
            timestamps.append('Overview')
            timestamps.append('Commented')
            #update sup listings
            sup.add_update(user, 'commented')

    timer.intermediate("sup")

    for timestamp in timestamps:
        set_last_modified(user, timestamp.lower())
    LastModified.touch(user._fullname, timestamps)
    timer.intermediate("last_modified")


def process_votes(qname, limit=0):
    # limit is taken but ignored for backwards compatibility
    stats_qname = qname
    if stats_qname.startswith("vote_link"):
        stats_qname = "vote_link_q"

    @g.stats.amqp_processor(stats_qname)
    def _handle_vote(msg):
        timer = stats.get_timer("service_time." + stats_qname)
        timer.start()

        #assert(len(msgs) == 1)
        r = pickle.loads(msg.body)

        uid, tid, dir, ip, organic, cheater = r
        voter = Account._byID(uid, data=True)
        votee = Thing._by_fullname(tid, data = True)
        timer.intermediate("preamble")

        # Convert the naive timestamp we got from amqplib to a
        # timezone aware one.
        tt = mktime(msg.timestamp.timetuple())
        date = datetime.utcfromtimestamp(tt).replace(tzinfo=pytz.UTC)

        # I don't know how, but somebody is sneaking in votes
        # for subreddits
        if isinstance(votee, (Link, Comment)):
            print (voter, votee, dir, ip, organic, cheater)
            handle_vote(voter, votee, dir, ip, organic,
                        cheater = cheater, foreground=True, timer=timer,
                        date=date)

        if isinstance(votee, Comment):
            update_comment_votes([votee])
            timer.intermediate("update_comment_votes")

        timer.flush()

    amqp.consume_items(qname, _handle_vote, verbose = False)
