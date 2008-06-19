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
from threading import local

from utils import lstrips
from contrib import memcache

class CacheUtils(object):
    def incr_multi(self, keys, amt=1, prefix=''):
        for k in keys:
            try:
                self.incr(prefix + k, amt)
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
        memcache.Client.delete_multi(self, keys, seconds = time,
                                     key_prefix = prefix)

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
        self._check_key(key)
        self[key] = val

    def set_multi(self, keys, prefix='', time=0):
        for k,v in keys.iteritems():
            self.set(prefix+str(k), v)

    def add(self, key, val):
        self._check_key(key)
        self.setdefault(key, val)

    def delete(self, key):
        if self.has_key(key):
            del self[key]

    def delete_multi(self, keys):
        for key in keys:
            if self.has_key(key):
                del self[key]

    def incr(self, key, amt=1):
        if self.has_key(key):
            self[key] += amt

    def decr(self, key, amt=1): 
        if self.has_key(key):
            self[key] -= amt

    def flush_all(self):
        self.clear()

class CacheChain(CacheUtils, local):
    def __init__(self, caches):
        self.caches = caches

    def make_set_fn(fn_name):
        def fn(self, *a, **kw):
            for c in self.caches:
                getattr(c, fn_name)(*a, **kw)
        return fn

    set = make_set_fn('set')
    set_multi = make_set_fn('set_multi')
    add = make_set_fn('add')
    incr = make_set_fn('incr')
    decr = make_set_fn('decr')
    delete = make_set_fn('delete')
    delete_multi = make_set_fn('delete_multi')
    flush_all = make_set_fn('flush_all')

    def get(self, key, default=None):
        for c in self.caches:
            val = c.get(key, default)
            if val is not None:
                #update other caches
                for d in self.caches:
                    if c == d:
                        break;
                    d.set(key, val)
                return val
        #didn't find anything
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
                        break;
                    d.set_multi(r)
                r.update(out)
                out = r
                need = need - set(r.keys())
        return out

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
    assert(cache.get('1') == 1)

    #python data
    cache.set('2', [1,2,3])
    assert(cache.get('2') == [1,2,3])

    #set multi, no prefix
    cache.set_multi({'3':3, '4': 4})
    assert(cache.get_multi(('3', '4')) == {'3':3, '4': 4})

    #set multi, prefix
    cache.set_multi({'3':3, '4': 4}, prefix='p_')
    assert(cache.get_multi(('3', 4), prefix='p_') == {'3':3, 4: 4})
    assert(cache.get_multi(('p_3', 'p_4')) == {'p_3':3, 'p_4': 4})

    #incr
    cache.set('5', 1)
    cache.set('6', 1)
    cache.incr('5')
    assert(cache.get('5'), 2)
    cache.incr('5',2)
    assert(cache.get('5'), 4)
    cache.incr_multi(('5', '6'), 1)
    assert(cache.get('5'), 5)    
    assert(cache.get('6'), 2)

# a cache that occasionally dumps itself to be used for long-running
# processes
class SelfEmptyingCache(LocalCache):
    def __init__(self,max_size=50*1000):
        self.max_size = max_size

    def maybe_reset(self):
        if len(self) > self.max_size:
            print "SelfEmptyingCache clearing!"
            self.clear()
            print "Cleared (%d)" % len(self)

    def set(self,key,val,time = 0):
        self.maybe_reset()
        return LocalCache.set(self,key,val,time)
    def add(self,key,val):
        return self.set(key,val)
