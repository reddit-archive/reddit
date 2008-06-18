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
#TODO byID use Things?
from __future__ import with_statement

import operators
import tdb_sql as tdb
import sorts
from .. utils import iters, Results, tup, to36, Storage
from r2.config import cache
from r2.config.databases import tz
from r2.lib.cache import sgm

import new, sys, sha
from datetime import datetime
from copy import copy, deepcopy
class NotFound(Exception): pass

thing_types = {}
rel_types = {}

def begin():
    tdb.transactions.begin()

def commit():
    tdb.transactions.commit()

def rollback():
    tdb.transactions.rollback()

def obj_id(things):
    return tuple(t if isinstance(t, (int, long)) else t._id for t in things)

def thing_prefix(cls_name, id=None):
    p = cls_name + '_'
    if id:
        p += str(id)
    return p

class SafeSetAttr:
    def __init__(self, cls):
        self.cls = cls

    def __enter__(self):
        self.cls.__safe__ = True

    def __exit__(self, type, value, tb):
        self.cls.__safe__ = False

class DataThing(object):
    _base_props = ()
    _int_props = ()
    _data_int_props = ()
    _int_prop_suffix = None
    _defaults = {}
    c = operators.Slots()
    __safe__ = False

    def __init__(self):
        safe_set_attr = SafeSetAttr(self)
        with safe_set_attr:
            self.safe_set_attr = safe_set_attr
            self._dirties = {}
            self._t = {}
            self._created = False
            self._loaded = True

    #TODO some protection here?
    def __setattr__(self, attr, val, make_dirty=True):
        if attr.startswith('__') or self.__safe__:
            object.__setattr__(self, attr, val)
            return 

        if attr.startswith('_'):
            #assume baseprops has the attr
            if make_dirty and hasattr(self, attr):
                old_val = getattr(self, attr)
            object.__setattr__(self, attr, val)
            if not attr in self._base_props:
                return
        else:
            old_val = self._t.get(attr, self._defaults.get(attr))
            self._t[attr] = val

        if make_dirty and val != old_val:
            self._dirties[attr] = val

    def __getattr__(self, attr):
        #makes pickling work for some reason
        if attr.startswith('__'):
            raise AttributeError

        try:
            if hasattr(self, '_t'):
                return self._t[attr]
            else:
                raise AttributeError, attr
        except KeyError:
            try:
                return getattr(self, '_defaults')[attr]
            except KeyError:
                if self._loaded:
                    raise AttributeError, '%s not found' % attr
                else:
                    raise AttributeError,\
                              attr + ' not found. thing is not loaded'

    def _commit(self, keys=None):
        if not self._created:
            self._create()

        if self._dirty:
            if keys:
                keys = tup(keys)
                to_set = dict((k, self._dirties[k])
                              for k in keys if self._dirties.has_key(k))
            else:
                to_set = self._dirties

            data_props = {}
            thing_props = {}
            for k, v in to_set.iteritems():
                if k.startswith('_'):
                    thing_props[k[1:]] = v
                else:
                    data_props[k] = v

            if data_props:
                self._set_data(self._type_id, self._id, **data_props)
            
            if thing_props:
                self._set_props(self._type_id, self._id, **thing_props)
            
            if keys:
                for k in keys:
                    if self._dirties.has_key(k):
                        del self._dirties[k]
            else:
                self._dirties.clear()

        # always set the cache
        cache.set(thing_prefix(self.__class__.__name__, self._id), self)

    @classmethod
    def _load_multi(cls, need):
        need = tup(need)
        need_ids = [n._id for n in need]
        datas = cls._get_data(cls._type_id, need_ids)
        to_save = {}
        for i in need:
            #if there wasn't any data, keep the empty dict
            i._t.update(datas.get(i._id, i._t))
            i._loaded = True
            to_save[i._id] = i

        prefix = thing_prefix(cls.__name__)

        #avoid race condition when incrementing data int props by
        #putting all the int props into the cache.

        #prop prefix
        def pp(prop, id):
            return prop + '_' + str(i._id)

        #do defined data props first, this also checks default values
        for prop in cls._data_int_props:
            for i in need:
                to_save[pp(prop, i._id)] = getattr(i, prop)

        #int props based on the suffix
        for i in need:
            for prop, val in i._t.iteritems():
                if cls._int_prop_suffix and prop.endswith(cls._int_prop_suffix):
                    to_save[pp(prop, i._id)] = val

        cache.set_multi(to_save, prefix)
        

    def _load(self):
        self._load_multi(self)

    def _safe_load(self):
        if not self._loaded:
            self._load()

    def _incr(self, prop, amt = 1):

        if self._dirty:
            raise ValueError, "cannot incr dirty thing"

        prefix = thing_prefix(self.__class__.__name__)
        key =  prefix + prop + '_' + str(self._id)
        cache_val = old_val = cache.get(key)
        if old_val is None:
            old_val = getattr(self, prop)

        if self._defaults.has_key(prop) and self._defaults[prop] == old_val:
            #potential race condition if the same property gets incr'd
            #from default at the same time
            setattr(self, prop, old_val + amt)
            self._commit(prop)
        else:
            self.__setattr__(prop, old_val + amt, False)
            #db
            if prop.startswith('_'):
                tdb.incr_thing_prop(self._type_id, self._id, prop[1:], amt)
            else:
                self._incr_data(self._type_id, self._id, prop, amt)
            cache.set(prefix + str(self._id), self)
            
        #cache
        if cache_val:
            cache.incr(key, amt)
        else:
            cache.set(key, getattr(self, prop))

    @property
    def _id36(self):
        return to36(self._id)

    @property
    def _fullname(self):
        return self._type_prefix + to36(self._type_id) + '_' + to36(self._id)

    #TODO error when something isn't found?
    @classmethod
    def _byID(cls, ids, data=False, return_dict=True, extra_props=None):
        ids, single = tup(ids, True)
        prefix = thing_prefix(cls.__name__)

        def items_db(ids):
            items = cls._get_item(cls._type_id, ids)
            for i in items.keys():
                items[i] = cls._build(i, items[i])

            #avoid race condition when incrmenting int props (data int
            #props are set in load_multi)
            for prop in cls._int_props:
                keys = dict((i, getattr(item, prop))
                            for i, item in items.iteritems())
                cache.set_multi(keys, prefix + prop + '_' )

            return items

        bases = sgm(cache, ids, items_db, prefix)

        if not bases:
            raise NotFound, '%s %s' % (cls.__name__, ids)

        if data:
            need = [v for v in bases.itervalues() if not v._loaded]
            if need:
                cls._load_multi(need)

        #e.g. add the sort prop
        if extra_props:
            for _id, props in extra_props.iteritems():
                for k, v in props.iteritems():
                    bases[_id].__setattr__(k, v, False)

        if single:
            return bases[ids[0]]
        elif return_dict:
            return bases
        else:
            return filter(None, (bases.get(i) for i in ids))

    @classmethod
    def _by_fullname(cls, names,
                     return_dict = True, 
                     data=False, extra_props=None):
        names, single = tup(names, True)

        table = {}
        lookup = {}
        # build id list by type
        for fullname in names:
            try:
                real_type, thing_id = fullname.split('_')
                #distinguish between things and realtions
                if real_type[0] == 't':
                    type_dict = thing_types
                elif real_type[0] == 'r':
                    type_dict = rel_types
                real_type = type_dict[int(real_type[1:], 36)]
                thing_id = int(thing_id, 36)
                lookup[fullname] = (real_type, thing_id)
                table.setdefault(real_type, []).append(thing_id)
            except ValueError:
                if single:
                    raise NotFound

        # lookup ids for each type
        identified = {}
        for real_type, thing_ids in table.iteritems():
            try:
                i = real_type._byID(thing_ids, data = data,
                                               extra_props = extra_props)
                identified[real_type] = i
            except NotFound:
                continue

        # interleave types in original order of the name
        res = []
        for fullname in names:
            if lookup.has_key(fullname):
                real_type, thing_id = lookup[fullname]
                res.append((fullname,
                            identified.get(real_type, {}).get(thing_id)))

        if single:
            return res[0][1]
        elif return_dict:
            return dict(res)
        else:
            return [x for i, x in res]

    @property
    def _dirty(self):
        return bool(len(self._dirties))

    @classmethod
    def _query(cls, *a, **kw):
        raise NotImplementedError()

    @classmethod
    def _build(*a, **kw):
        raise NotImplementedError()

    def _get_data(*a, **kw):
        raise NotImplementedError()

    def _set_data(*a, **kw):
        raise NotImplementedError()

    def _incr_data(*a, **kw):
        raise NotImplementedError()

    def _get_item(*a, **kw):
        raise NotImplementedError

    def _create(self):
        base_props = (getattr(self, prop) for prop in self._base_props)
        self._id = self._make_fn(self._type_id, *base_props)
        self._created = True

class ThingMeta(type):
    def __init__(cls, name, bases, dct):
        if name == 'Thing' or hasattr(cls, '_nodb') and cls._nodb: return
        #print "checking thing", name

        #TODO exceptions
        cls._type_name = name.lower()
        try:
            cls._type_id = tdb.types_name[cls._type_name].type_id
        except KeyError:
            raise KeyError, 'is the thing database %s defined?' % name

        global thing_types
        thing_types[cls._type_id] = cls

        super(ThingMeta, cls).__init__(name, bases, dct)
    
    def __repr__(cls):
        return '<thing: %s>' % cls._type_name

class Thing(DataThing):
    __metaclass__ = ThingMeta
    _base_props = ('_ups', '_downs', '_date', '_deleted', '_spam')
    _int_props = ('_ups', '_downs')
    _make_fn = staticmethod(tdb.make_thing)
    _set_props = staticmethod(tdb.set_thing_props)
    _get_data = staticmethod(tdb.get_thing_data)
    _set_data = staticmethod(tdb.set_thing_data)
    _get_item = staticmethod(tdb.get_thing)
    _incr_data = staticmethod(tdb.incr_thing_data)
    _type_prefix = 't'

    def __init__(self, ups = 0, downs = 0, date = None, deleted = False,
                 spam = False, id = None, **attrs):
        DataThing.__init__(self)

        with self.safe_set_attr:
            if id:
                self._id = id
                self._created = True
                self._loaded = False

            if not date: date = datetime.now(tz)
            
            self._ups = ups
            self._downs = downs
            self._date = date
            self._deleted = deleted
            self._spam = spam

        #new way
        for k, v in attrs.iteritems():
            self.__setattr__(k, v, not self._created)
        
    def __repr__(self):
        return '<%s %s>' % (self.__class__.__name__,
                            self._id if self._created else '[unsaved]')

    def _set_id(self, thing_id):
        if not self._created:
            with self.safe_set_attr:
                self._base_props += ('_thing_id',)
                self._thing_id = thing_id

    @property
    def _hot(self):
        return sorts.hot(self._ups, self._downs, self._date)

    @property
    def _score(self):
        return sorts.score(self._ups, self._downs)

    @property
    def _controversy(self):
        return sorts.controversy(self._ups, self._downs)

    @classmethod
    def _build(cls, id, bases):
        return cls(bases.ups, bases.downs, bases.date,
                   bases.deleted, bases.spam, id)

    @classmethod
    def _query(cls, *rules, **kw):
        need_deleted = True
        need_spam = True
        #add default spam/deleted
        for r in rules:
            if not isinstance(r, operators.op):
                continue
            if r.lval_name == '_deleted':
                need_deleted = False
            elif r.lval_name == '_spam':
                need_spam = False

        if need_deleted or need_spam:
            rules = list(rules)

        if need_deleted:
            rules.append(cls.c._deleted == False)

        if need_spam:
            rules.append(cls.c._spam == False)

        return Things(cls, *rules, **kw)

    def __getattr__(self, attr):
        return DataThing.__getattr__(self, attr)
            
        

class RelationMeta(type):
    def __init__(cls, name, bases, dct):
        if name == 'RelationCls': return
        #print "checking relation", name

        cls._type_name = name.lower()
        try:
            cls._type_id = tdb.rel_types_name[cls._type_name].type_id
        except KeyError:
            raise KeyError, 'is the relationship database %s defined?' % name

        global rel_types
        rel_types[cls._type_id] = cls

        super(RelationMeta, cls).__init__(name, bases, dct)

    def __repr__(cls):
        return '<relation: %s>' % cls._type_name

def Relation(type1, type2, denorm1 = None, denorm2 = None):
    class RelationCls(DataThing):
        __metaclass__ = RelationMeta
        if not (issubclass(type1, Thing) and issubclass(type2, Thing)):
                raise TypeError('Relation types must be subclass of %s' % Thing)

        _type1 = type1
        _type2 = type2

        _base_props = ('_thing1_id', '_thing2_id', '_name', '_date')
        _make_fn = staticmethod(tdb.make_relation)
        _set_props = staticmethod(tdb.set_rel_props)
        _get_data = staticmethod(tdb.get_rel_data)
        _set_data = staticmethod(tdb.set_rel_data)
        _get_item = staticmethod(tdb.get_rel)
        _incr_data = staticmethod(tdb.incr_rel_data)
        _type_prefix = 'r'

        def __init__(self, thing1, thing2, name, date = None, id = None, **attrs):
            DataThing.__init__(self)

            def id_and_obj(in_thing):
                if isinstance(in_thing, (int, long)):
                    return in_thing
                else:
                    return in_thing._id

            with self.safe_set_attr:
                if id:
                    self._id = id
                    self._created = True
                    self._loaded = False

                if not date: date = datetime.now(tz)


                #store the id, and temporarily store the actual object
                #because we may need it later
                self._thing1_id = id_and_obj(thing1)
                self._thing2_id = id_and_obj(thing2)
                self._name = name
                self._date = date

            for k, v in attrs.iteritems():
                self.__setattr__(k, v, not self._created)

            def denormalize(denorm, src, dest):
                if denorm:
                    setattr(dest, denorm[0], getattr(src, denorm[1]))
                
            #denormalize
            if not self._created:
                denormalize(denorm1, thing2, thing1)
                denormalize(denorm2, thing1, thing2)

        def __getattr__(self, attr):
            if attr == '_thing1':
                return self._type1._byID(self._thing1_id)
            elif attr == '_thing2':
                return self._type2._byID(self._thing2_id)
            elif attr.startswith('_t1'):
                return getattr(self._thing1, attr[3:])
            elif attr.startswith('_t2'):
                return getattr(self._thing2, attr[3:])
            else:
                return DataThing.__getattr__(self, attr)
                            
        def __repr__(self):
            return ('<%s %s: <%s %s> - <%s %s> %s>' %
                    (self.__class__.__name__, self._name,
                     self._type1.__name__, self._thing1_id,
                     self._type2.__name__,self._thing2_id,
                     '[unsaved]' if not self._created else '\b'))

        def _commit(self):
            DataThing._commit(self)
            #if i denormalized i need to check here
            if denorm1: self._thing1._commit(denorm1[0])
            if denorm2: self._thing2._commit(denorm2[0])
            #set fast query cache
            cache.set(thing_prefix(self.__class__.__name__)
                      + str((self._thing1_id, self._thing2_id, self._name)),
                      self._id)

        def _delete(self):
            tdb.del_rel(self._type_id, self._id)
            
            #clear cache
            prefix = thing_prefix(self.__class__.__name__)
            #TODO - there should be just one cache key for a rel?
            cache.delete(prefix + str(self._id))
            #update fast query cache
            cache.set(prefix + str((self._thing1_id,
                                    self._thing2_id,
                                    self._name)), None)

        @classmethod
        def _fast_query(cls, thing1s, thing2s, name, data=True):
            """looks up all the relationships between thing1_ids and thing2_ids
            and caches them"""
            prefix = thing_prefix(cls.__name__)

            thing1_dict = dict((t._id, t) for t in thing1s)
            thing2_dict = dict((t._id, t) for t in thing2s)

            thing1_ids = thing1_dict.keys()
            thing2_ids = thing2_dict.keys()

            name = tup(name)

            pairs = set((x, y, n)
                        for x in thing1_ids
                        for y in thing2_ids
                        for n in name)

            def items_db(pairs):
                t1_ids = set()
                t2_ids = set()
                names = set()
                for t1, t2, name in pairs:
                    t1_ids.add(t1)
                    t2_ids.add(t2)
                    names.add(name)

                q = cls._query(cls.c._thing1_id == t1_ids,
                               cls.c._thing2_id == t2_ids,
                               cls.c._name == names,
                               eager_load = True,
                               data = data)

                rel_ids = {}
                for rel in q:
                    #TODO an alternative for multiple
                    #relations with the same keys
                    #l = rel_ids.setdefault((rel._thing1_id, rel._thing2_id), [])
                    #l.append(rel._id)
                    rel_ids[(rel._thing1._id, rel._thing2._id, rel._name)] = rel._id
                
                for p in pairs:
                    if p not in rel_ids:
                        rel_ids[p] = None
                        
                return rel_ids

            res = sgm(cache, pairs, items_db, prefix)
            #convert the keys back into objects
            #we can assume the rels will be in the cache and just call
            #_byID lots
            res_obj = {}
            for k, rid in res.iteritems():
                obj_key = (thing1_dict[k[0]], thing2_dict[k[1]], k[2])
                res_obj[obj_key] = cls._byID(rid, data=data) if rid else None
                
            return res_obj
            
        @classmethod
        def _gay(cls):
            return cls._type1 == cls._type2

        @classmethod
        def _build(cls, id, bases):
            return cls(bases.thing1_id, bases.thing2_id, bases.name, bases.date, id)

        @classmethod
        def _query(cls, *a, **kw):
            return Relations(cls, *a, **kw)


    return RelationCls

#TODO can this be more efficient?
class QueryAttr(object):
    __slots__ = ('cols',)
    def __init__(self, *cols):
        self.cols = cols

    def __eq__(self, other):
        return (self, other)

    def lookup(self, obj):
        return reduce(getattr, self.cols, obj)

    def __getattr__(self, attr):
        return QueryAttr(*list(self.cols) + [attr])

class Query(object):
    def __init__(self, kind, *rules, **kw):
        self._rules = []
        self._kind = kind

        self._read_cache = kw.get('read_cache')
        self._write_cache = kw.get('write_cache')
        self._cache_time = kw.get('cache_time', 0)
        self._stats_collector = kw.get('stats_collector')
        self._limit = kw.get('limit')
        self._data = kw.get('data')
        self._sort = kw.get('sort', ())

        self._filter(*rules)
    
    def _setsort(self, sorts):
        sorts = tup(sorts)
        #make sure sorts are wrapped in a Sort obj
        have_date = False
        op_sorts = []
        for s in sorts:
            if not isinstance(s, operators.sort):
                s = operators.asc(s)
            op_sorts.append(s)
            if s.col.endswith('_date'):
                have_date = True
        if op_sorts and not have_date:
            op_sorts.append(operators.desc('_date'))

        self._sort_param = op_sorts
        return self

    def _getsort(self):
        return self._sort_param

    _sort = property(_getsort, _setsort)

    def _reverse(self):
        for s in self._sort:
            if isinstance(s, operators.asc):
                s.__class__ = operators.desc
            else:
                s.__class__ = operators.asc

    def _list(self, data = False):
        if data:
            self._data = data

        return list(self)

    def _dir(self, thing, reverse):
        ors = []
        #for each sort add and a comparison operator
        for i in range(len(self._sort)):
            s = self._sort[i]

            if isinstance(s, operators.asc):
                op = operators.gt
            else:
                op = operators.lt

            if reverse:
                op = operators.gt if op == operators.lt else operators.lt

            #remember op takes lval and lval_name
            ands = [op(s.col, s.col, getattr(thing, s.col))]

            #for each sort up to the last add an equals operator
            for j in range(0, i):
                s = self._sort[j]
                ands.append(thing.c[s.col] == getattr(thing, s.col))

            ors.append(operators.and_(*ands))

        return self._filter(operators.or_(*ors))

    def _before(self, thing):
        return self._dir(thing, True)

    def _after(self, thing):
        return self._dir(thing, False)

    def _count(self):
        return self._cursor().rowcount()

    def __getattr__(self, attr):
        if attr.startswith('__'):
            raise AttributeError
        else:
            return QueryAttr(attr)

    def _filter(*a, **kw):
        raise NotImplementedError

    def _cursor(*a, **kw):
        raise NotImplementedError

    def _iden(self):
        i = str(self._sort) + str(self._kind) + str(self._limit)
        if self._rules:
            rules = copy(self._rules)
            rules.sort()
            for r in rules:
                i += str(r)
        return sha.new(i).hexdigest()

    def __iter__(self):
        used_cache = False

        if self._stats_collector:
            self._stats_collector.add(self)

        lst = None
        if self._read_cache:
            names = cache.get(self._iden())
            if names:
                lst = Thing._by_fullname(names, data = self._data, return_dict = False)

        if lst is None:
            #hit the db
            try:
                lst = self._cursor().fetchall()
            except NotFound:
                lst = ()
        else:
            used_cache = True

        if self._write_cache and not used_cache:
            names = tuple(i._fullname for i in lst)
            cache.set(self._iden(), names, self._cache_time)

        for i in lst:
            yield i

class Things(Query):
    def __init__(self, kind, *rules, **kw):
        self._use_data = False
        Query.__init__(self, kind, *rules, **kw)

    def _filter(self, *rules):
        for op in operators.op_iter(rules):
            if not op.lval_name.startswith('_'):
                self._use_data = True

        self._rules += rules
        return self

            
    def _cursor(self):
        #TODO why was this even here?
        #get_cols = bool(self._sort_param)
        get_cols = False
        params = (self._kind._type_id,
                  get_cols,
                  self._sort,
                  self._limit,
                  self._rules)
        if self._use_data:
            c = tdb.find_data(*params)
        else:
            c = tdb.find_things(*params)
            
        #TODO simplfy this! get_cols is always false?
        #called on a bunch of rows to fetch their properties in batch
        def row_fn(rows):
            #if have a sort, add the sorted column to the results
            if get_cols:
                extra_props = {}
                for r in rows:
                    for sc in (s.col for s in self._sort):
                        #dict of ids to the extra sort params
                        props = extra_props.setdefault(r.thing_id, {})
                        props[sc] = getattr(r, sc)
                _ids = extra_props.keys()
            else:
                _ids = rows
                extra_props = {}
            return self._kind._byID(_ids, self._data, False, extra_props)

        return Results(c, row_fn, True)

def load_things(rels, load_data=False):
    rels = tup(rels)
    kind = rels[0].__class__

    t1_ids = set()
    t2_ids = t1_ids if kind._gay() else set()
    for rel in rels:
        t1_ids.add(rel._thing1_id)
        t2_ids.add(rel._thing2_id)
    kind._type1._byID(t1_ids, load_data)
    if not kind._gay():
        t2_items = kind._type2._byID(t2_ids, load_data)

class Relations(Query):
    #params are thing1, thing2, name, date
    def __init__(self, kind, *rules, **kw):
        self._eager_load = kw.get('eager_load')
        self._thing_data = kw.get('thing_data')
        Query.__init__(self, kind, *rules, **kw)

    def _filter(self, *rules):
        self._rules += rules
        return self

    def _eager(self, eager, thing_data = False):
        #load the things (id, ups, down, etc.)
        self._eager_load = eager
        #also load the things' data
        self._thing_data = thing_data
        return self

    def _make_rel(self, rows):
        rels = self._kind._byID(rows, self._data, False)
        if self._eager_load:
            load_things(rels, self._thing_data)
        return rels

    def _cursor(self):
        c = tdb.find_rels(self._kind._type_id,
                          False,
                          sort = self._sort,
                          limit = self._limit,
                          constraints = self._rules)
        return Results(c, self._make_rel, True)

class MultiCursor(object):
    def __init__(self, *execute_params):
        self._execute_params = execute_params
        self._cursor = None

    def fetchone(self):
        if not self._cursor:
            self._cursor = self._execute(*self._execute_params)
            
        return self._cursor.next()
                
    def fetchall(self):
        if not self._cursor:
            self._cursor = self._execute(*self._execute_params)

        return [i for i in self._cursor]

class MergeCursor(MultiCursor):
    def _execute(self, cursors, sorts):
        #a "pair" is a (cursor, item, done) tuple
        def safe_next(c):
            try:
                #hack to keep searching even if fetching a thing returns notfound
                while True:
                    try:
                        return [c, c.fetchone(), False]
                    except NotFound:
                        #skips the broken item
                        pass
            except StopIteration:
                return c, None, True

        def undone(pairs):
            return [p for p in pairs if not p[2]]

        pairs = undone(safe_next(c) for c in cursors)
        while pairs:
            #only one query left, just dump it
            if len(pairs) == 1:
                c, item, done = pair = pairs[0]
                while not done:
                    yield item
                    c, item, done = safe_next(c)
                    pair[:] = c, item, done
            else:
                #by default, yield the first item
                yield_pair = pairs[0]
                for s in sorts:
                    col = s.col
                    #sort direction?
                    max_fn = min if isinstance(s, operators.asc) else max

                    #find the max (or min) val
                    vals = [(getattr(i[1], col), i) for i in pairs]
                    max_pair = vals[0]
                    all_equal = True
                    for pair in vals[1:]:
                        if all_equal and pair[0] != max_pair[0]:
                            all_equal = False
                        max_pair = max_fn(max_pair, pair, key=lambda x: x[0])

                    if not all_equal:
                        yield_pair = max_pair[1]
                        break

                c, item, done = yield_pair
                yield item
                yield_pair[:] = safe_next(c)

            pairs = undone(pairs)
        raise StopIteration

class MultiQuery(Query):
    def __init__(self, queries, *rules, **kw):
        self._queries = queries
        Query.__init__(self, None, *rules, **kw)

    def _iden(self):
        return ''.join(q._iden() for q in self._queries)

    def _cursor(self):
        raise NotImplementedError()

    def _reverse(self):
        for q in self._queries:
            q._reverse()

    def _setdata(self, data):
        for q in self._queries:
            q._data = data

    def _getdata(self):
        if self._queries:
            return self._queries[0]._data

    _data = property(_getdata, _setdata)

    def _setsort(self, sorts):
        for q in self._queries:
            q._sort = deepcopy(sorts)

    def _getsort(self):
        if self._queries:
            return self._queries[0]._sort

    _sort = property(_getsort, _setsort)

    def _filter(self, *rules):
        for q in self._queries:
            q._filter(*rules)

    def _getrules(self):
        return [q._rules for q in self._queries]

    def _setrules(self, rules):
        for q,r in zip(self._queries, rules):
            q._rules = r

    _rules = property(_getrules, _setrules)

    def _getlimit(self):
        return self._queries[0]._limit

    def _setlimit(self, limit):
        for q in self._queries:
            q._limit = limit

    _limit = property(_getlimit, _setlimit)

class Merge(MultiQuery):
    def _cursor(self):
        if (any(q._sort for q in self._queries) and
            not reduce(lambda x,y: (x == y) and x,
                      (q._sort for q in self._queries))):
            raise "The sorts should be the same"

        return MergeCursor((q._cursor() for q in self._queries),
                           self._sort)

def MultiRelation(name, *relations):
    rels_tmp = {}
    for rel in relations:
        t1, t2 = rel._type1, rel._type2
        clsname = name + '_' + t1.__name__.lower() + '_' + t2.__name__.lower()
        cls = new.classobj(clsname, (rel,), {'__module__':t1.__module__})
        setattr(sys.modules[t1.__module__], clsname, cls)
        rels_tmp[(t1, t2)] = cls

    class MultiRelationCls(object):
        c = operators.Slots()
        rels = rels_tmp

        def __init__(self, thing1, thing2, *a, **kw):
            r = self.rel(thing1, thing2)
            self.__class__ = r
            self.__init__(thing1, thing2, *a, **kw)

        @classmethod
        def rel(cls, thing1, thing2):
            t1 = thing1 if isinstance(thing1, ThingMeta) else thing1.__class__
            t2 = thing2 if isinstance(thing2, ThingMeta) else thing2.__class__
            return cls.rels[(t1, t2)]

        @classmethod
        def _query(cls, *rules, **kw):
            #TODO it should be possible to send the rules and kw to
            #the merge constructor
            queries = [r._query(*rules, **kw) for r in cls.rels.values()]
            return Merge(queries)

        @classmethod
        def _fast_query(cls, sub, obj, name, data=True):
            #divide into types
            def type_dict(items):
                types = {}
                for i in items:
                    types.setdefault(i.__class__, []).append(i)
                return types
            
            sub_dict = type_dict(tup(sub))
            obj_dict = type_dict(tup(obj))

            #for each pair of types, see if we have a query to send
            res = {}
            for types, rel in cls.rels.iteritems():
                t1, t2 = types
                if sub_dict.has_key(t1) and obj_dict.has_key(t2):
                    res.update(rel._fast_query(sub_dict[t1], obj_dict[t2], name,
                                               data = True))

            return res

    return MultiRelationCls

# class JoinCursor(MultiCursor):
#     def _execute(self, c1, c2, col_fn1, col_fn2):
#         orig_c1 = c1
#         orig_c2 = c2

#         done1 = False
#         done2 = False

#         c1_item = c1.fetchone()
#         c2_item = c2.fetchone()

#         def safe_next(c, cur):
#             try: return c.fetchone(), False
#             except StopIteration: return cur, True

#         while not (done1 and done2):
#             if col_fn1(c1_item) == col_fn2(c2_item):
#                 if c1 == orig_c1:
#                     yield (c1_item, c2_item)
#                 else:
#                     yield (c2_item, c1_item)
#             else:
#                 c1, c2 = c2, c1
#                 col_fn1, col_fn2 = col_fn2, col_fn1
#                 done1, done2 = done2, done1
#                 c1_item, c2_item = c2_item, c1_item

#             c2_item, done2 = safe_next(c2, c2_item)
#             if done2:
#                 c1_item, done1 = safe_next(c1, c1_item)

#         raise StopIteration

#TODO the constructors on these classes are dumb
# class Join(MultiQuery):
#     cursor_cls = JoinCursor

#     def __init__(self, query1, query2, rule):
#         MultiQuery.__init__(self, query1, query2)
#         self._a = (rule[0].lookup, rule, rule[1].lookup)
