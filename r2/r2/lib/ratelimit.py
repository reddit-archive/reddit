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
# All portions of the code written by reddit are Copyright (c) 2006-2015 reddit
# Inc. All Rights Reserved.
###############################################################################

import collections
import time

import pylibmc

from pylons import g

from r2.lib.cache import MemcachedMaximumRetryException


TimeSlice = collections.namedtuple("TimeSlice", ["beginning", "remaining", "end"])


class RatelimitError(Exception):
    def __init__(self, e):
        self.wrapped = e

    def __str__(self):
        return str(self.wrapped)


def _append_time_slice(key_prefix, time_slice):
    return key_prefix + time.strftime("-%H%M%S", time_slice.beginning)


def get_timeslice(slice_seconds):
    """Return tuple describing the current slice given slice width.

    The elements of the tuple are:

    - `beginning`: seconds since epoch to beginning of time period
    - `remaining`: seconds from now until `end`
    - `end`: seconds since epoch to end of time period

    """

    now = time.time()
    slice_start, secs_since = divmod(now, slice_seconds)
    slice_start = time.gmtime(int(slice_start * slice_seconds))
    secs_to_next = slice_seconds - int(secs_since)
    return TimeSlice(slice_start, secs_to_next, now + secs_to_next)


def record_usage(key_prefix, time_slice):
    """Record usage of a ratelimit for the specified time slice.

    The total usage (including this one) of the ratelimit is returned or
    RatelimitError is raised if something went wrong during the process.

    """

    key = _append_time_slice(key_prefix, time_slice)

    try:
        g.ratelimitcache.add(key, 0, time=time_slice.remaining + 1)

        try:
            recent_usage = g.ratelimitcache.incr(key)
        except pylibmc.NotFound:
            # Previous round of ratelimiting fell out in the
            # time between calling `add` and calling `incr`.
            g.ratelimitcache.add(key, 1, time=time_slice.remaining + 1)
            recent_usage = 1
            g.stats.simple_event("ratelimit.eviction")
        return recent_usage
    except (pylibmc.Error, MemcachedMaximumRetryException) as e:
        raise RatelimitError(e)


def get_usage(key_prefix, time_slice):
    """Return the current usage of a ratelimit for the specified time slice."""

    key = _append_time_slice(key_prefix, time_slice)

    try:
        return g.ratelimitcache.get(key)
    except pylibmc.NotFound:
        return 0
    except (pylibmc.Error, MemcachedMaximumRetryException) as e:
        raise RatelimitError(e)
