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

"""
Contains utilities intended to be run from a command line
"""

from time import sleep
import sys

    
def bench_cache_lifetime(minutes):
    "Attempts to find how long a given memcached key can be expected to live"

    from pylons import g
    from r2.lib.cache import PyMemcache as Memcache

    # we'll create an independent connection to memcached for this
    # test
    mc = Memcache(g.memcaches)

    # set N keys, and tell them not to live for longer than this test
    mc.set_multi(dict( ('bench_cache_%d' % x, x)
                       for x in xrange(minutes) ),
                 time=minutes*60)

    # and every minute, check to see that the keys are still present,
    # until we find one missing
    for x in xrange(minutes):
        if mc.get('bench_cache_%d' % x, None) is not None:
            sleep(60)
        else:
            # we found one missing
            return x-1
    else:
        # we're out of numbers, and we didn't find any missing
        # keys. Since we only set N keys, we can't check for anything
        # else
        print (("Cache lifetime is greater than %d minutes. Try again with a"+
                " higher 'minutes' value") % minutes)
        return None

def bench_cache_lifetime_multi(attempts=10, minutes=60*24):
    """
    Attempts to find the minimum, maximum, and average cache key lifetime

    Example:
        paster run production.ini r2/lib/utils/cmd_utils.py -c "bench_cache_lifetime_multi()"
    """
    total = 0
    attempts_so_far = 0
    minimum = sys.maxint
    maximum = 0

    for x in xrange(attempts):
        this_attempt = bench_cache_lifetime(minutes)
        maximum = max(this_attempt, maximum)
        minimum = min(this_attempt, minimum)

        total += this_attempt
        attempts_so_far += 1
        mean = float(total)/float(attempts_so_far)

        print ("Attempt #%d of %d: %d; min=%d, max=%d, mean=%.2f"
               % (x+1, attempts, this_attempt, minimum, maximum, mean))

    return (minimum, maximum, mean)

def subs_contribs(sr_name = 'betateam'):
    """Convert all subscribers of a given subreddit to
       contributors. Useful for forming opt-in beta teams"""
    from r2.models import Subreddit, SRMember

    sr = Subreddit._by_name(sr_name)
    q = SRMember._query(SRMember.c._thing1_id == sr._id)

    for rel in rels:
        if rel._name == 'subscriber':
            sr.add_contributor(rel._thing2)
