# smart get multi:
# For any keys not found in the cache, miss_fn() is run and the result is
# stored in the cache. Then it returns everything, both the hits and misses.
def sgm(cache, keys, miss_fn, str prefix='', int time=0, _update=False):
    cdef dict ret
    cdef dict s_keys
    cdef dict cached
    cdef dict calculated
    cdef dict calculated_to_cache
    cdef set  still_need

    ret = {}

    # map the string versions of the keys to the real version. we only
    # need this to interprate the cache's response and turn it back
    # into the version they asked for
    s_keys = {}
    for key in keys:
        s_keys[str(key)] = key

    if _update:
        cached = {}
    else:
        cached = cache.get_multi(s_keys.keys(), prefix=prefix)
        for k, v in cached.iteritems():
            ret[s_keys[k]] = v

    if miss_fn and len(cached) < len(s_keys):
        # if we didn't get all of the keys from the cache, go to the
        # miss_fn with the keys they asked for minus the ones that we
        # found
        still_need = set(s_keys.values()) - set(ret.keys())

        calculated = miss_fn(still_need)
        ret.update(calculated)

        calculated_to_cache = {}
        for k, v in calculated.iteritems():
            calculated_to_cache[str(k)] = v
        cache.set_multi(calculated_to_cache, prefix=prefix)

    return ret
