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
from datetime import datetime

from pylons import g

import pycassa
import cassandra.ttypes
from cassandra.ttypes import ConsistencyLevel

from r2.lib.utils import tup, Storage
from r2.lib.db.sorts import epoch_seconds
from r2.lib import cache
from uuid import uuid1

cassandra = g.cassandra
thing_cache = g.thing_cache
keyspace = 'reddit'
disallow_db_writes = g.disallow_db_writes
tz = g.tz
read_consistency_level = g.cassandra_rcl
write_consistency_level = g.cassandra_wcl

# descriptions of the CFs available on boot.
boot_cfs = cassandra.describe_keyspace(keyspace)

thing_types = {}

# The available consistency levels
CL = Storage(ZERO   = ConsistencyLevel.ZERO,
             ANY    = ConsistencyLevel.ANY,
             ONE    = ConsistencyLevel.ONE,
             QUORUM = ConsistencyLevel.QUORUM,
             ALL    = ConsistencyLevel.ALL)

# the greatest number of columns that we're willing to accept over the
# wire for a given row (this should be increased if we start working
# with classes with lots of columns, like Account which has lots of
# karma_ rows, or we should not do that)
max_column_count = 100

class CassandraException(Exception):
    """Base class for Exceptions in tdb_cassandra"""
    pass

class InvariantException(CassandraException):
    """Exceptions that can only be caused by bugs in tdb_cassandra"""
    pass

class ConfigurationException(CassandraException):
    """Exceptions that are caused by incorrect configuration on the
       Cassandra server"""
    pass

class TdbException(CassandraException):
    """Exceptions caused by bugs in our callers or subclasses"""
    pass

class NotFound(CassandraException):
    """Someone asked us for an ID that isn't stored in the DB at
       all. This is probably an end-user's fault."""
    pass

class ThingMeta(type):
    def __init__(cls, name, bases, dct):
        type.__init__(cls, name, bases, dct)

        global boot_cfs

        if cls._use_db:
            if cls._type_prefix is None:
                raise TdbException('_type_prefix not present for %r' % cls)

            if cls._type_prefix in thing_types:
                raise InvariantException("Redefining type #%s?" % (cls._type_prefix))

            cf_name = cls._cf_name or name

            # make sure the CF for this type exists, or refuse to
            # start
            if cf_name not in boot_cfs:
                # do another lookup in case both this class and the CF
                # were created after boot (this may have the effect of
                # doubling the connection load on the seed node(s) if
                # someone rolls a patch without first creating the
                # appropriate CFs if that drives reddit into a restart
                # loop; if that happens often just remove the next two
                # lines)
                boot_cfs = cassandra.describe_keyspace(keyspace)
                if name not in boot_cfs:
                    raise ConfigurationException("ColumnFamily %s does not exist" % name)

            thing_types[cls._type_prefix] = cls

            cls.cf = pycassa.ColumnFamily(cassandra, keyspace,
                                          cf_name,
                                          read_consistency_level = read_consistency_level,
                                          write_consistency_level = write_consistency_level)

        cls._kind = name

    def __repr__(cls):
        return '<thing: %s>' % cls.__name__

class ThingBase(object):
    # base class for Things and Relation

    __metaclass__ = ThingMeta

    _cf_name = None # the name of the ColumnFamily; defaults to the
                    # name of the class

    # subclasses must replace these

    _type_prefix = None # this must be present for classes with _use_db==True

    _use_db = False

    _int_props = ()
    _float_props = () # note that we can lose resolution on these
    _bool_props = ()
    _pickle_props = ()
    _date_props = () # note that we can lose resolution on these
    _bytes_props = ()

    _str_props = () # at present we never actually read out of here,
                    # so it's more of a comment

    # the value that we assume a property to have if it is not found
    # in the DB. Note that we don't do type-checking here, so if you
    # want a default to be a boolean and want it to be storable you'll
    # also have to set it in _bool_props
    _defaults = {}

    # a timestamp property that will automatically be added to newly
    # created Things (disable by setting to None)
    _timestamp_prop = None

    def __init__(self, _id = None, _committed = False, **kw):
        # things that have changed
        self._dirties = kw.copy()

        # what the original properties were when we went to Cassandra to
        # get them
        self._orig = {}

        self._defaults = self._defaults.copy()

        # whether this item has ever been created
        self._committed = _committed

        # our row key
        self._id = _id

        if not self._use_db:
            raise TdbException("Cannot make instances of %r" % (self.__class__,))

    @classmethod
    def _byID(cls, ids):
        ids, is_single = tup(ids, True)

        if not len(ids):
            if is_single:
                raise InvariantException("whastis?")
            else:
                return {}

        # all keys must be strings or directly convertable to strings
        assert all(isinstance(_id, basestring) and str(_id) for _id in ids)

        def lookup(l_ids):
            rows = cls.cf.multiget(l_ids, column_count=max_column_count)

            l_ret = {}
            for t_id, row in rows.iteritems():
                t = cls._from_serialized_columns(t_id, row)
                l_ret[t._id] = t

            return l_ret

        ret = cache.sgm(thing_cache, ids, lookup, prefix=cls._cache_prefix())

        if is_single and not ret:
            raise NotFound("<%s %r>" % (cls.__name__,
                                        ids[0]))
        elif is_single:
            assert len(ret) == 1
            return ret.values()[0]

        return ret

    @property
    def _fullname(self):
        if self._type_prefix is None:
            raise TdbException("%r has no _type_prefix, so fullnames cannot be generated"
                               % self.__class__)

        return '%s_%s' % (self._type_prefix, self._id)

    @classmethod
    def _by_fullname(cls, fnames):
        ids, is_single = tup(fnames, True)

        by_cls = {}
        for i in ids:
            typ, underscore, _id = i.partition('_')
            assert underscore == '_'

            by_cls.setdefault(thing_types[typ], []).append(_id)

        items = []
        for typ, ids in by_cls.iteritems():
            items.extend(typ._byID(ids).values())

        return items[0] if is_single else dict((x._fullname, x)
                                               for x in items)

    @classmethod
    def _cache_prefix(cls):
        return 'tdbcassandra_' + cls._type_prefix + '_'

    def _cache_key(self):
        if not self._id:
            raise TdbException('no cache key for uncommitted %r' % (self,))

        return self._cache_prefix() + self._id

    @classmethod
    def _deserialize_column(cls, attr, val):
        if attr in cls._int_props:
            try:
                return int(val)
            except ValueError:
                return long(val)
        elif attr in cls._float_props:
            return float(val)
        elif attr in cls._bool_props:
            # note that only the string "1" is considered true!
            return val == '1'
        elif attr in cls._pickle_props:
            return pickle.loads(val)
        elif attr in cls._date_props or attr == cls._timestamp_prop:
            as_float = float(val)
            return datetime.utcfromtimestamp(as_float).replace(tzinfo = tz)
        elif attr in cls._bytes_props:
            return val

        # otherwise we'll assume that it's a utf-8 string
        return val.decode('utf-8')

    @classmethod
    def _serialize_column(cls, attr, val):
        if attr in cls._int_props or attr in cls._float_props:
            return str(val)
        elif attr in cls._bool_props:
            # n.b. we "truncate" this to a boolean, so truthy but
            # non-boolean values are discarded
            return '1' if val else '0'
        elif attr in cls._pickle_props:
            return pickle.dumps(val)
        elif attr in cls._date_props:
            return cls._serialize_date(val)
        elif attr in cls._bytes_props:
            return val

        return unicode(val).encode('utf-8')

    @classmethod
    def _serialize_date(cls, date):
        return str(epoch_seconds(date))

    @classmethod
    def _deserialize_date(cls, val):
        as_float = float(val)
        return datetime.utcfromtimestamp(as_float).replace(tzinfo = tz)

    @classmethod
    def _from_serialized_columns(cls, t_id, columns):
        d_columns = dict((attr, cls._deserialize_column(attr, val))
                         for (attr, val)
                         in columns.iteritems())
        return cls._from_columns(t_id, d_columns)

    @classmethod
    def _from_columns(cls, t_id, columns):
        """Given a dictionary of freshly deserialized columns
           construct an instance of cls"""
        # if modifying this, check Relation._from_columns and see if
        # you should change it as well
        t = cls()
        t._orig = columns
        t._id = t_id
        t._committed = True
        return t

    @property
    def _dirty(self):
        return len(self._dirties) or not self._committed

    def _commit(self):
        if disallow_db_writes:
            raise CassandraException("Not so fast! DB writes have been disabled")

        if not self._dirty:
            return

        if self._id is None:
            raise TdbException("Can't commit %r without an ID" % (self,))

        if not self._committed:
            # if this has never been committed we should also consider
            # the _orig columns as dirty (but "less dirty" than the
            # _dirties)
            upd = self._orig.copy()
            upd.update(self._dirties)
            self._dirties = upd
            self._orig.clear()

        # Cassandra values are untyped byte arrays, so we need to
        # serialize everything, filtering out anything that's been
        # dirtied but doesn't actually differ from what's written out
        updates = dict((attr, self._serialize_column(attr, val))
                       for (attr, val)
                       in self._dirties.iteritems()
                       if (attr not in self._orig or
                           val != self._orig[attr]))


        if not self._committed and self._timestamp_prop and self._timestamp_prop not in updates:
            # auto-create timestamps on classes that request them

            # this serialize/deserialize is a bit funny: the process
            # of storing and retrieving causes us to lose some
            # resolution because of the floating-point representation,
            # so this is just to make sure that we have the same value
            # that the DB does after writing it out. Note that this is
            # the only property munged this way: other timestamp and
            # floating point properties may lose resolution
            s_now = self._serialize_date(datetime.now(tz))
            now = self._deserialize_date(s_now)

            updates[self._timestamp_prop] = s_now
            self._dirties[self._timestamp_prop] = now

        if not updates:
            return

        self.cf.insert(self._id, updates)

        self._orig.update(self._dirties)
        self._dirties.clear()

        if not self._committed:
            self._on_create()

        self._committed = True

        thing_cache.set(self._cache_key(), self)

    def _revert(self):
        if not self._committed:
            raise TdbException("Revert to what?")

        self._dirties.clear()

    def __getattr__(self, attr):
        if attr.startswith('_'):
            try:
                return self.__dict__[attr]
            except KeyError:
                raise AttributeError, attr

        if attr in self._dirties:
            return self._dirties[attr]
        elif attr in self._orig:
            return self._orig[attr]
        elif attr in self._defaults:
            return self._defaults[attr]
        else:
            raise AttributeError('%r has no %r' % (self, attr))

    def __setattr__(self, attr, val):
        if attr == '_id' and self._committed:
            raise ValueError('cannot change _id on a committed %r' % (self.__class__))

        if attr.startswith('_'):
            return object.__setattr__(self, attr, val)

        self._dirties[attr] = val

    def __eq__(self, other):
        return (self.__class__ == other.__class__ # yes equal, not a subclass
                and self._id == other._id
                and self._t == other._t)

    def __ne__(self, other):
        return not (self == other)

    @property
    def _t(self):
        """Emulate the _t property from tdb_sql: a dictionary of all
           values that are or will be stored in the database, (not
           including _defaults)"""
        ret = self._orig.copy()
        ret.update(self._dirties)
        return ret

    # allow the dictionary mutation syntax; it makes working some some
    # keys a bit easier
    def __getitem__(self, key):
        return self.__getattr__(self, attr)

    def __setitem__(self, key, value):
        return self.__setattr__(key, value)

    def _get(self, key, default = None):
        try:
            return self.__getattr__(key)
        except AttributeError:
            return default

    def _on_create(self):
        """A hook executed on creation, good for creation of static
           Views. Subclasses should call their parents' hook(s) as
           well"""
        pass

    @classmethod
    def _all(cls):
        # returns a query object yielding every single item in a
        # column family. it probably shouldn't be used except in
        # debugging
        return Query(cls, limit=None)

    def __repr__(self):
        # it's safe for subclasses to override this to e.g. put a Link
        # title or Account name in the repr(), but they must be
        # careful to check hasattr for the properties that they read
        # out, as __getattr__ itself may call __repr__ in constructing
        # its error messages
        id_str = self._id
        comm_str = '' if self._committed else ' (uncommitted)'
        return "<%s %r%s>" % (self.__class__.__name__,
                              id_str,
                              comm_str)

    def __del__(self):
        if not self._committed:
            # normally we'd log this with g.log or something, but we
            # can't guarantee what thread is destructing us
            print "Warning: discarding uncomitted %r; this is usually a bug" % (self,)

class Thing(ThingBase):
    _timestamp_prop = 'date'

class Relation(ThingBase):
    _timestamp_prop = 'date'

    def __init__(self, thing1_id, thing2_id, **kw):
        # NB! When storing relations between postgres-backed Thing
        # objects, these IDs are actually ID36s
        return ThingBase.__init__(self,
                                  _id = '%s_%s' % (thing1_id, thing2_id),
                                  thing1_id=thing1_id, thing2_id=thing2_id,
                                  **kw)

    @classmethod
    def _fast_query(cls, thing1_ids, thing2_ids, **kw):
        """Find all of the relations of this class between all of the
           members of thing1_ids and thing2_ids"""
        thing1_ids, thing1s_is_single = tup(thing1_ids, True)
        thing2_ids, thing2s_is_single = tup(thing2_ids, True)

        # permute all of the pairs
        ids = set(('%s_%s' % (x, y))
                  for x in thing1_ids
                  for y in thing2_ids)

        rels = cls._byID(ids).values()

        # does anybody actually use us this way?
        if thing1s_is_single and thing2s_is_single:
            if rels:
                assert len(rels) == 1
                return rels[0]
            else:
                raise NotFound("<%s '%s_%s'>" % (cls.__name__,
                                                 thing1_ids[0],
                                                 thing2_ids[0]))

        return dict(((rel.thing1_id, rel.thing2_id), rel)
                    for rel in rels)

    @classmethod
    def _from_columns(cls, t_id, columns):
        # we deserialize relations a little specially so that we can
        # throw our toys on the floor if they don't have thing1_id and
        # thing2_id
        if not ('thing1_id' in columns and 'thing2_id' in columns
                and t_id == ('%s_%s' % (columns['thing1_id'], columns['thing2_id']))):
            raise InvariantException("Looked up %r with unmatched IDs (%r)"
                                     % (cls, t_id))

        r = cls(thing1_id=columns['thing1_id'], thing2_id=columns['thing2_id'])
        r._orig = columns
        assert r._id == t_id
        r._committed = True
        return r

    def _commit(self):
        assert self._id == '%s_%s' % (self.thing1_id, self.thing2_id)

        return ThingBase._commit(self)

    @classmethod
    def _rel(cls, thing1_cls, thing2_cls):
        # should be implemented by abstract relations, like Vote
        raise NotImplementedError

    @classmethod
    def _datekey(cls, date):
        # ick
        return str(long(cls._serialize_date(cls.date)))

class Query(object):
    """A query across a CF. Note that while you can query rows from a
     CF that has a RandomPartitioner, you won't get them in any sort
     of order, which makes 'after' unreliable"""
    def __init__(self, cls, after=None, limit=100, chunk_size=100):
        self.cls = cls
        self.after = after
        self.limit = limit
        self.chunk_size = chunk_size

    def __iter__(self):
        # n.b.: we aren't caching objects that we find this way in the
        # LocalCache. This may will need to be changed if we ever
        # start using OPP in Cassandra (since otherwise these types of
        # queries aren't useful for anything but debugging anyway)
        after = '' if self.after is None else self.after._id
        limit = self.limit

        r = self.cls.cf.get_range(start=after, row_count=limit,
                                  column_count = max_column_count)
        for t_id, columns in r:
            t = self.cls._from_serialized_columns(t_id, columns)
            yield t

class View(ThingBase):
    # Views are Things like any other, but may have special key
    # characteristics

    _timestamp_prop = None

    @staticmethod
    def _gen_uuid():
        """Convenience method for generating UUIDs for view
           keys. Generates time-based UUIDs, safe for use as TimeUUID
           indices in Cassandra"""
        
        return uuid1()

