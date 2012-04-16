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

import random
import datetime
import collections

from pylons import g
from pycassa.system_manager import ASCII_TYPE, UTF8_TYPE
from pycassa.batch import Mutator

from r2.models import Thing
from r2.lib.db import tdb_cassandra
from r2.lib.db.operators import asc
from r2.lib.db.sorts import epoch_seconds
from r2.lib.utils import flatten, to36
from r2.lib.db.tdb_cassandra import json

CONNECTION_POOL = g.cassandra_pools['main']
PRUNE_CHANCE = g.querycache_prune_chance
MAX_CACHED_ITEMS = 1000
LOG = g.log

class ThingTupleComparator(object):
    def __init__(self, sorts):
        self.sorts = sorts

    def __call__(self, t1, t2):
        for i, s in enumerate(self.sorts):
            # t1 and t2 are tuples of (fullname, *sort_cols), so we
            # can get the value to compare right out of the tuple
            v1, v2 = t1[i + 1], t2[i + 1]
            if v1 != v2:
                return cmp(v1, v2) if isinstance(s, asc) else cmp(v2, v1)
        #they're equal
        return 0


class CachedQueryBase(object):
    def __init__(self, sort):
        self.sort = sort
        self.sort_cols = [s.col for s in self.sort]
        self.data = []
        self._fetched = False

    def fetch(self, force=False, data=None):
        if not force and self._fetched:
            return

        self._fetch()
        self._sort_data()
        self._fetched = True

    def _fetch(self):
        raise NotImplementedError()

    def _sort_data(self):
        comparator = ThingTupleComparator(self.sort_cols)
        self.data.sort(cmp=comparator)

    def __iter__(self):
        self.fetch()

        for x in self.data:
            yield x[0]


class CachedQuery(CachedQueryBase):
    def __init__(self, model, key, query, filter_fn):
        self.model = model
        self.key = key
        self.query = query
        self.query._limit = MAX_CACHED_ITEMS  # .update() should only get as many items as we need
        self.filter = filter_fn
        self.timestamps = None  # column timestamps, for safe pruning
        super(CachedQuery, self).__init__(query._sort)

    def _make_item_tuple(self, item):
        """Given a single 'item' from the result of a query build the tuple
        that will be stored in the query cache. It is effectively the
        fullname of the item after passing through the filter plus the
        columns of the unfiltered item to sort by."""
        filtered_item = self.filter(item)
        lst = [filtered_item._fullname]
        for col in self.sort_cols:
            # take the property of the original
            attr = getattr(item, col)
            # convert dates to epochs to take less space
            if isinstance(attr, datetime.datetime):
                attr = epoch_seconds(attr)
            lst.append(attr)
        return tuple(lst)

    def _fetch(self):
        self._fetch_multi([self])

    @classmethod
    def _fetch_multi(self, queries):
        by_model = collections.defaultdict(list)
        for q in queries:
            by_model[q.model].append(q)

        cached_queries = {}
        for model, queries in by_model.iteritems():
            fetched = model.get([q.key for q in queries])
            cached_queries.update(fetched)

        for q in queries:
            cached_query = cached_queries.get(q.key)
            if cached_query:
                q.data, q.timestamps = cached_query

    def _insert(self, mutator, things):
        if not things:
            return

        values = {}
        for thing in things:
            t = self._make_item_tuple(thing)
            values[t[0]] = tuple(t[1:])

        self.model.insert(mutator, self.key, values)

    def _delete(self, mutator, things):
        if not things:
            return

        fullnames = [self.filter(x)._fullname for x in things]
        self.model.remove(mutator, self.key, fullnames)

    def _prune(self, mutator):
        extraneous_ids = [t[0] for t in self.data[MAX_CACHED_ITEMS:]]

        if extraneous_ids:
            self.model.remove_if_unchanged(mutator, self.key,
                                        extraneous_ids, self.timestamps)

            cf_name = self.model.__name__
            query_name = self.key.split('.')[0]
            counter = g.stats.get_counter('cache.%s.%s' % (cf_name, query_name))
            if counter:
                counter.increment('pruned', delta=len(extraneous_ids))

    def update(self):
        things = list(self.query)

        with Mutator(CONNECTION_POOL) as m:
            self.model.remove(m, self.key, None)  # empty the whole row
            self._insert(m, things)

    @classmethod
    def _prune_multi(cls, queries):
        cls._fetch_multi(queries)

        with Mutator(CONNECTION_POOL) as m:
            for q in queries:
                q._sort_data()
                q._prune(m)

    def __hash__(self):
        return hash(self.key)

    def __eq__(self, other):
        return self.key == other.key

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return "%s(%s, %r)" % (self.__class__.__name__,
                               self.model.__name__, self.key)


class MergedCachedQuery(CachedQueryBase):
    def __init__(self, queries):
        self.queries = queries

        if queries:
            sort = queries[0].sort
            assert all(sort == q.sort for q in queries)
        else:
            sort = []
        super(MergedCachedQuery, self).__init__(sort)

    def _fetch(self):
        CachedQuery._fetch_multi(self.queries)
        self.data = flatten([q.data for q in self.queries])

    def update(self):
        for q in self.queries:
            q.update()


class CachedQueryMutator(object):
    def __init__(self):
        self.mutator = Mutator(CONNECTION_POOL)
        self.to_prune = set()

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.send()

    def insert(self, query, things):
        if not things:
            return

        LOG.debug("Inserting %r into query %r", things, query)

        query._insert(self.mutator, things)

        if (random.random() / len(things)) < PRUNE_CHANCE:
            self.to_prune.add(query)

    def delete(self, query, things):
        if not things:
            return

        LOG.debug("Deleting %r from query %r", things, query)

        query._delete(self.mutator, things)

    def send(self):
        self.mutator.send()

        if self.to_prune:
            LOG.debug("Pruning queries %r", self.to_prune)
            CachedQuery._prune_multi(self.to_prune)


def filter_identity(x):
    return x


def filter_thing2(x):
    """A filter to apply to the results of a relationship query returns
    the object of the relationship."""
    return x._thing2


def cached_query(model, filter_fn=filter_identity):
    def cached_query_decorator(fn):
        def cached_query_wrapper(*args):
            # build the row key from the function name and arguments
            row_key_components = [fn.__name__[len('get_'):]]

            if len(args) > 0:
                # we want to accept either a Thing or a thing's ID at this
                # layer, but the query itself should always get just an ID
                if isinstance(args[0], Thing):
                    args = list(args)
                    args[0] = args[0]._id

                thing_id = to36(args[0])
                row_key_components.append(thing_id)

            row_key_components.extend(str(x) for x in args[1:])
            row_key = '.'.join(row_key_components)

            # call the wrapped function to get a query
            query = fn(*args)

            # cached results for everyone!
            return CachedQuery(model, row_key, query, filter_fn)
        return cached_query_wrapper
    return cached_query_decorator


def merged_cached_query(fn):
    def merge_wrapper(*args):
        queries = fn(*args)
        return MergedCachedQuery(queries)
    return merge_wrapper


class BaseQueryCache(object):
    __metaclass__ = tdb_cassandra.ThingMeta
    _connection_pool = 'main'
    _extra_schema_creation_args = dict(key_validation_class=ASCII_TYPE,
                                       default_validation_class=UTF8_TYPE)
    _compare_with = ASCII_TYPE
    _use_db = False

    _type_prefix = None
    _cf_name = None

    @classmethod
    def get(cls, keys):
        rows = cls._cf.multiget(keys, include_timestamp=True,
                                column_count=tdb_cassandra.max_column_count)

        res = {}
        for row, columns in rows.iteritems():
            data = []
            timestamps = []

            for (key, (value, timestamp)) in columns.iteritems():
                value = json.loads(value)
                data.append((key,) + tuple(value))
                timestamps.append((key, timestamp))

            res[row] = (data, dict(timestamps))

        return res

    @classmethod
    @tdb_cassandra.will_write
    def insert(cls, mutator, key, columns):
        updates = dict((key, json.dumps(value))
                       for key, value in columns.iteritems())
        mutator.insert(cls._cf, key, updates)

    @classmethod
    @tdb_cassandra.will_write
    def remove(cls, mutator, key, columns):
        mutator.remove(cls._cf, key, columns=columns)

    @classmethod
    @tdb_cassandra.will_write
    def remove_if_unchanged(cls, mutator, key, columns, timestamps):
        for col in columns:
            mutator.remove(cls._cf, key, columns=[col],
                           timestamp=timestamps.get(col))


class UserQueryCache(BaseQueryCache):
    _use_db = True


class SubredditQueryCache(BaseQueryCache):
    _use_db = True
