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
from hashlib import md5

import pylibmc
from _pylibmc import MemcachedError
from contrib import memcache

from utils import lstrips, in_chunks, tup
from r2.lib.hardcachebackend import HardCacheBackend

class NoneResult(object): pass

class CacheUtils(object):
    def incr_multi(self, keys, delta=1, prefix=''):
        for k in keys:
            try:
                self.incr(prefix + k, delta)
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

class Permacache(CacheUtils, memcache.Client):
    """We still use our patched python-memcache to talk to the
       permacaches for legacy reasons"""
    simple_get_multi = memcache.Client.get_multi

    def __init__(self, servers):
        memcache.Client.__init__(self, servers, pickleProtocol = 1)

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

    def get_local_client(self):
        return self # memcache.py handles this itself

class Memcache(CacheUtils, pylibmc.Client):
    simple_get_multi = pylibmc.Client.get_multi

    def __init__(self, servers,
                 debug = False,
                 binary=True,
                 noreply=False):
        pylibmc.Client.__init__(self, servers, binary=binary)
        behaviors = {'no_block': True, # use async I/O
                     'cache_lookups': True, # cache DNS lookups
                     'tcp_nodelay': True, # no nagle
                     'ketama': True, # consistant hashing
                     '_noreply': int(noreply),
                     'verify_key': int(debug)} # spend the CPU to verify keys
        self.behaviors.update(behaviors)
        self.local_clients = local()

    def get_local_client(self):
        # if this thread hasn't had one yet, make one
        if not getattr(self.local_clients, 'client', None):
            self.local_clients.client = self.clone()
        return self.local_clients.client

    def set_multi(self, keys, prefix='', time=0):
        new_keys = {}
        for k,v in keys.iteritems():
            new_keys[str(k)] = v
        pylibmc.Client.set_multi(self, new_keys, key_prefix = prefix,
                                 time = time)

    def incr(self, key, delta=1, time=0):
        # ignore the time on these
        return pylibmc.Client.incr(self, key, delta)

    def add(self, key, val, time=0):
        try:
            return pylibmc.Client.add(self, key, val, time=time)
        except pylibmc.DataExists:
            return None

    def get(self, key, default=None):
        r = pylibmc.Client.get(self, key)
        if r is None:
            return default
        return r

    def set(self, key, val, time=0):
        pylibmc.Client.set(self, key, val, time = time)

    def delete_multi(self, keys, prefix='', time=0):
        pylibmc.Client.delete_multi(self, keys, time = time,
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
        was = key in self
        self.setdefault(key, val)
        return not was

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

    # note that because of the naive nature of `add' when used on a
    # cache chain, its return value isn't reliable. if you need to
    # verify its return value you'll either need to make it smarter or
    # use the underlying cache directly
    add = make_set_fn('add')

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

    def get(self, key, default = None, local = True):
        for c in self.caches:
            if not local and isinstance(c,LocalCache):
                continue

            val = c.get(key)

            if val is not None:
                #update other caches
                for d in self.caches:
                    if c is d:
                        break # so we don't set caches later in the chain
                    d.set(key, val)

                if self.cache_negative_results and val is NoneResult:
                    return default
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
                # we've found them all
                break
            r = c.simple_get_multi(need)
            #update other caches
            if r:
                for d in self.caches:
                    if c is d:
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

    def __repr__(self):
        return '<%s>' % (self.__class__.__name__,)

    def debug(self, key):
        print "Looking up [%r]" % key
        for i, c in enumerate(self.caches):
            print "[%d] %10s has value [%r]" % (i, c.__class__.__name__,
                                                c.get(key))

    def reset(self):
        # the first item in a cache chain is a LocalCache
        self.caches = (self.caches[0].__class__(),) +  self.caches[1:]

class MemcacheChain(CacheChain):
    def __init__(self, caches):
        CacheChain.__init__(self, caches)
        self.mc_master = self.caches[-1]

    def reset(self):
        CacheChain.reset(self)
        localcache, old_mc = self.caches
        self.caches = (localcache, self.mc_master.get_local_client())

class DoubleMemcacheChain(CacheChain):
    """Temporary cache chain that places the new cache ahead of the
       old one for easier deployment"""
    def __init__(self, caches):
        self.caches = localcache, memcache, permacache = caches
        self.mc_master = memcache

    def reset(self):
        CacheChain.reset(self)
        self.caches = (self.caches[0],
                       self.mc_master.get_local_client(),
                       self.caches[2])

class PermacacheChain(CacheChain):
    pass

class HardcacheChain(CacheChain):
    def __init__(self, caches, cache_negative_results = False):
        CacheChain.__init__(self, caches, cache_negative_results)
        localcache, memcache, hardcache = self.caches
        self.mc_master = memcache

    def add(self, key, val, time=0):
        authority = self.caches[-1] # the authority is the hardcache
                                    # itself
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
            auth_value = int(auth_value) + delta
        except ValueError:
            raise ValueError("Can't accrue %s; it's a %s (%r)" %
                             (key, auth_value.__class__.__name__, auth_value))

        for c in self.caches:
            c.set(key, auth_value, time=time)

    @property
    def backend(self):
        # the hardcache is always the last item in a HardCacheChain
        return self.caches[-1].backend

    def reset(self):
        CacheChain.reset(self)
        assert len(self.caches) == 3
        self.caches = (self.caches[0],
                       self.mc_master.get_local_client(),
                       self.caches[2])

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

def test_cache(cache, prefix=''):
    #basic set/get
    cache.set('%s1' % prefix, 1)
    assert cache.get('%s1' % prefix) == 1

    #python data
    cache.set('%s2' % prefix, [1,2,3])
    assert cache.get('%s2' % prefix) == [1,2,3]

    #set multi, no prefix
    cache.set_multi({'%s3' % prefix:3, '%s4' % prefix: 4})
    assert cache.get_multi(('%s3' % prefix, '%s4' % prefix)) == {'%s3' % prefix: 3, 
                                                                 '%s4' % prefix: 4}

    #set multi, prefix
    cache.set_multi({'3':3, '4': 4}, prefix='%sp_' % prefix)
    assert cache.get_multi(('3', 4), prefix='%sp_' % prefix) == {'3':3, 4: 4}
    assert cache.get_multi(('%sp_3' % prefix, '%sp_4' % prefix)) == {'%sp_3'%prefix: 3,
                                                                     '%sp_4'%prefix: 4}

    #incr
    cache.set('%s5'%prefix, 1)
    cache.set('%s6'%prefix, 1)
    cache.incr('%s5'%prefix)
    assert cache.get('%s5'%prefix) == 2
    cache.incr('%s5'%prefix,2)
    assert cache.get('%s5'%prefix) == 4
    cache.incr_multi(('%s5'%prefix, '%s6'%prefix), 1)
    assert cache.get('%s5'%prefix) == 5
    assert cache.get('%s6'%prefix) == 2

def test_multi(cache):
    from threading import Thread

    num_threads = 100
    num_per_thread = 1000

    threads = []
    for x in range(num_threads):
        def _fn(prefix):
            def __fn():
                for y in range(num_per_thread):
                    test_cache(cache,prefix=prefix)
            return __fn
        t = Thread(target=_fn(str(x)))
        t.start()
        threads.append(t)

    for thread in threads:
        thread.join()

# a cache that occasionally dumps itself to be used for long-running
# processes
class SelfEmptyingCache(LocalCache):
    def __init__(self, max_size=10*1000):
        self.max_size = max_size

    def maybe_reset(self):
        if len(self) > self.max_size:
            self.clear()

    def set(self, key, val, time=0):
        self.maybe_reset()
        return LocalCache.set(self,key,val,time)

    def add(self, key, val, time=0):
        self.maybe_reset()
        return LocalCache.add(self, key, val)

def make_key(iden, *a, **kw):
    """
    A helper function for making memcached-usable cache keys out of
    arbitrary arguments. Hashes the arguments but leaves the `iden'
    human-readable
    """
    h = md5()

    def _conv(s):
        if isinstance(s, str):
            return s
        elif isinstance(s, unicode):
            return s.encode('utf-8')
        elif isinstance(s, (tuple, list)):
            return ','.join(_conv(x) for x in s)
        elif isinstance(s, dict):
            return ','.join('%s:%s' % (_conv(k), _conv(v))
                            for (k, v) in sorted(s.iteritems()))
        else:
            return str(s)

    iden = _conv(iden)
    h.update(iden)
    h.update(_conv(a))
    h.update(_conv(kw))

    return '%s(%s)' % (iden, h.hexdigest())
