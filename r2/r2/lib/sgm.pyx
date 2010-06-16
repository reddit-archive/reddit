# smart get multi:
# For any keys not found in the cache, miss_fn() is run and the result is
# stored in the cache. Then it returns everything, both the hits and misses.
def sgm(cache, keys, miss_fn, str prefix='', int time=0):
    cdef dict ret
    cdef dict s_keys
    cdef dict cached
    cdef dict calculated
    cdef dict calculated_to_cache
    cdef set  s_need
    cdef list k_need

    ret = {}

    s_keys = {}
    for key in keys:
        s_keys[str(key)] = key

    cached = cache.get_multi(s_keys.keys(), prefix=prefix)
    for k, v in cached.iteritems():
        ret[s_keys[k]] = v

    if miss_fn and len(cached) < len(s_keys):
        # if we didn't get all of the keys from the cache. take the
        # missing subset
        s_need = set(s_keys.keys()) - set(ret.keys())

        k_need = []
        for i in s_need:
            k_need.append(s_keys[i])

        calculated = miss_fn(k_need)
        ret.update(calculated)

        calculated_to_cache = {}
        for k, v in calculated.iteritems():
            calculated_to_cache[str(k)] = v
        cache.set_multi(calculated_to_cache, prefix=prefix)

    return ret
