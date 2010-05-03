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
from threading import local

from utils import lstrips, in_chunks
from contrib import memcache

from r2.lib.hardcachebackend import HardCacheBackend

class NoneResult(object): pass

class CacheUtils(object):
    def incr_multi(self, keys, delta=1, time=0, prefix=''):
        for k in keys:
            try:
                self.incr(prefix + k, time=time, delta=delta)
            except ValueError:
                pass

    def add_multi(self, keys, prefix=''):
        for k,v in keys.iteritems():
            self.add(prefix+str(k), v)

    def get_multi(self, keys, prefix='', partial=True):
        if prefix:
            key_map = dict((prefix+str(k), k) for k in keys)
        else:
            key_map = dict((str(k), k) for k in keys)

        r = self.simple_get_multi(key_map.keys())

        if not partial and len(r.keys()) < len(key_map):
            return None

        return dict((key_map[k], r[k]) for k in r.keys())

class Memcache(CacheUtils, memcache.Client):
    simple_get_multi = memcache.Client.get_multi

    def set_multi(self, keys, prefix='', time=0):

        new_keys = {}
        for k,v in keys.iteritems():
            new_keys[str(k)] = v
        memcache.Client.set_multi(self, new_keys, key_prefix = prefix,
                                  time = time)

    def get(self, key, default=None):
        r = memcache.Client.get(self, key)
        if r is None: return default
        return r

    def set(self, key, val, time=0):
        memcache.Client.set(self, key, val, time = time)

    def delete(self, key, time=0):
        memcache.Client.delete(self, key, time=time)

    def delete_multi(self, keys, prefix='', time=0):
        memcache.Client.delete_multi(self, keys, time = time,
                                     key_prefix = prefix)

class HardCache(CacheUtils):
    backend = None

    def __init__(self, gc):
        self.backend = HardCacheBackend(gc)

    def _split_key(self, key):
        tokens = key.split("-", 1)
        if len(tokens) != 2:
            raise ValueError("key %s has no dash" % key)

        category, ids = tokens
        return category, ids

    def set(self, key, val, time=0):
        if val is NoneResult:
            # NoneResult caching is for other parts of the chain
            return

        category, ids = self._split_key(key)
        self.backend.set(category, ids, val, time)

    def simple_get_multi(self, keys):
        results = {}
        category_bundles = {}
        for key in keys:
            category, ids = self._split_key(key)
            category_bundles.setdefault(category, []).append(ids)

        for category in category_bundles:
            idses = category_bundles[category]
            chunks = in_chunks(idses, size=50)
            for chunk in chunks:
                new_results = self.backend.get_multi(category, chunk)
                results.update(new_results)

        return results

    def set_multi(self, keys, prefix='', time=0):
        for k,v in keys.iteritems():
            if v is not NoneResult:
                self.set(prefix+str(k), v, time=time)

    def get(self, key, default=None):
        category, ids = self._split_key(key)
        r = self.backend.get(category, ids)
        if r is None: return default
        return r

    def delete(self, key, time=0):
        # Potential optimization: When on a negative-result caching chain,
        # shove NoneResult throughout the chain when a key is deleted.
        category, ids = self._split_key(key)
        self.backend.delete(category, ids)

    def add(self, key, value, time=0):
        category, ids = self._split_key(key)
        return self.backend.add(category, ids, value, time=time)

    def incr(self, key, delta=1, time=0):
        category, ids = self._split_key(key)
        return self.backend.incr(category, ids, delta=delta, time=time)


class LocalCache(dict, CacheUtils):
    def __init__(self, *a, **kw):
        return dict.__init__(self, *a, **kw)

    def _check_key(self, key):
        if not isinstance(key, str):
            raise TypeError('Key must be a string.')

    def get(self, key, default=None):
        r = dict.get(self, key)
        if r is None: return default
        return r

    def simple_get_multi(self, keys):
        out = {}
        for k in keys:
            if self.has_key(k):
                out[k] = self[k]
#        print "Local cache answers: " + str(out)
        return out

    def set(self, key, val, time = 0):
        # time is ignored on localcache
        self._check_key(key)
        self[key] = val

    def set_multi(self, keys, prefix='', time=0):
        for k,v in keys.iteritems():
            self.set(prefix+str(k), v, time=time)

    def add(self, key, val, time = 0):
        self._check_key(key)
        return self.setdefault(key, val)

    def delete(self, key):
        if self.has_key(key):
            del self[key]

    def delete_multi(self, keys):
        for key in keys:
            if self.has_key(key):
                del self[key]

    def incr(self, key, delta=1, time=0):
        if self.has_key(key):
            self[key] = int(self[key]) + delta

    def decr(self, key, amt=1):
        if self.has_key(key):
            self[key] = int(self[key]) - amt

    def append(self, key, val, time = 0):
        if self.has_key(key):
            self[key] = str(self[key]) + val

    def prepend(self, key, val, time = 0):
        if self.has_key(key):
            self[key] = val + str(self[key])

    def replace(self, key, val, time = 0):
        if self.has_key(key):
            self[key] = val

    def flush_all(self):
        self.clear()

class CacheChain(CacheUtils, local):
    def __init__(self, caches, cache_negative_results=False):
        self.caches = caches
        self.cache_negative_results = cache_negative_results

    def make_set_fn(fn_name):
        def fn(self, *a, **kw):
            for c in self.caches:
                ret = getattr(c, fn_name)(*a, **kw)
            return ret
        return fn

    set = make_set_fn('set')
    append = make_set_fn('append')
    prepend = make_set_fn('prepend')
    replace = make_set_fn('replace')
    set_multi = make_set_fn('set_multi')
    add = make_set_fn('add')
    incr = make_set_fn('incr')
    decr = make_set_fn('decr')
    delete = make_set_fn('delete')
    delete_multi = make_set_fn('delete_multi')
    flush_all = make_set_fn('flush_all')
    cache_negative_results = False

    def add(self, key, val, time=0):
        authority = self.caches[-1]
        added_val = authority.add(key, val, time=time)
        for cache in self.caches[:-1]:
            # Calling set() rather than add() to ensure that all caches are
            # in sync and that de-syncs repair themselves
            cache.set(key, added_val, time=time)
        return added_val

    def accrue(self, key, time=0, delta=1):
        auth_value = self.caches[-1].get(key)

        if auth_value is None:
            self.caches[-1].set(key, 0, time)
            auth_value = 0

        try:
            auth_value = int(auth_value)
        except ValueError:
            raise ValueError("Can't accrue %s; it's a %s (%r)" %
                             (key, auth_value.__class__.__name__, auth_value))

        for c in self.caches:
            c.set(key, auth_value, time=time)

        self.incr(key, time=time, delta=delta)

    def get(self, key, default = None, local = True):
        for c in self.caches:
            if not local and isinstance(c,LocalCache):
                continue

            val = c.get(key)

            if val is not None:
                #update other caches
                for d in self.caches:
                    if c == d:
                        break # so we don't set caches later in the chain
                    d.set(key, val)

                if self.cache_negative_results and val is NoneResult:
                    return None
                else:
                    return val

        #didn't find anything

        if self.cache_negative_results:
            for c in self.caches:
                c.set(key, NoneResult)

        return default

    def simple_get_multi(self, keys):
        out = {}
        need = set(keys)
        for c in self.caches:
            if len(out) == len(keys):
                break
            r = c.simple_get_multi(need)
            #update other caches
            if r:
                for d in self.caches:
                    if c == d:
                        break # so we don't set caches later in the chain
                    d.set_multi(r)
                r.update(out)
                out = r
                need = need - set(r.keys())

        if need and self.cache_negative_results:
            d = dict( (key,NoneResult) for key in need)
            for c in self.caches:
                c.set_multi(d)

        if self.cache_negative_results:
            filtered_out = {}
            for k,v in out.iteritems():
                if v is not NoneResult:
                    filtered_out[k] = v
            out = filtered_out

        return out

    def debug(self, key):
        print "Looking up [%r]" % key
        for i, c in enumerate(self.caches):
            print "[%d] %10s has value [%r]" % (i, c.__class__.__name__,
                                                c.get(key))

#smart get multi
def sgm(cache, keys, miss_fn, prefix='', time=0):
    keys = set(keys)
    s_keys = dict((str(k), k) for k in keys)
    r = cache.get_multi(s_keys.keys(), prefix)
    if miss_fn and len(r.keys()) < len(keys):
        need = set(s_keys.keys()) - set(r.keys())
        #TODO i can't send a generator
        nr = miss_fn([s_keys[i] for i in need])
        nr = dict((str(k), v) for k,v in nr.iteritems())
        r.update(nr)
        cache.set_multi(nr, prefix, time = time)

    return dict((s_keys[k], v) for k,v in r.iteritems())

def test_cache(cache):
    #basic set/get
    cache.set('1', 1)
    assert cache.get('1') == 1

    #python data
    cache.set('2', [1,2,3])
    assert cache.get('2') == [1,2,3]

    #set multi, no prefix
    cache.set_multi({'3':3, '4': 4})
    assert cache.get_multi(('3', '4')) == {'3':3, '4': 4}

    #set multi, prefix
    cache.set_multi({'3':3, '4': 4}, prefix='p_')
    assert cache.get_multi(('3', 4), prefix='p_') == {'3':3, 4: 4}
    assert cache.get_multi(('p_3', 'p_4')) == {'p_3':3, 'p_4': 4}

    #incr
    cache.set('5', 1)
    cache.set('6', 1)
    cache.incr('5')
    assert cache.get('5') == 2
    cache.incr('5',2)
    assert cache.get('5') == 4
    cache.incr_multi(('5', '6'), 1)
    assert cache.get('5') == 5
    assert cache.get('6') == 2

# a cache that occasionally dumps itself to be used for long-running
# processes
class SelfEmptyingCache(LocalCache):
    def __init__(self, max_size=10*1000):
        self.max_size = max_size

    def maybe_reset(self):
        if len(self) > self.max_size:
            self.clear()

    def set(self,key,val,time = 0):
        self.maybe_reset()
        return LocalCache.set(self,key,val,time)

    def add(self,key,val):
        return self.set(key,val)
