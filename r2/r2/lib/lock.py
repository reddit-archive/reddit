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

from __future__ import with_statement
from time import sleep
from datetime import datetime
from threading import local

# thread-local storage for detection of recursive locks
locks = local()

class TimeoutExpired(Exception): pass

class MemcacheLock(object):
    """A simple global lock based on the memcache 'add' command. We
    attempt to grab a lock by 'adding' the lock name. If the response
    is True, we have the lock. If it's False, someone else has it."""

    def __init__(self, key, cache, time = 30, timeout = 30):
        # get a thread-local set of locks that we own
        self.locks = locks.locks = getattr(locks, 'locks', set())

        self.key = key
        self.cache = cache.get_local_client()
        self.time = time
        self.timeout = timeout
        self.have_lock = False

    def __enter__(self):
        start = datetime.now()

        #if this thread already has this lock, move on
        if self.key in self.locks:
            return

        #try and fetch the lock, looping until it's available
        while not self.cache.add(self.key, 1, time = self.time):
            if (datetime.now() - start).seconds > self.timeout:
                raise TimeoutExpired

            sleep(.1)

        #tell this thread we have this lock so we can avoid deadlocks
        #of requests for the same lock in the same thread
        self.locks.add(self.key)
        self.have_lock = True

    def __exit__(self, type, value, tb):
        #only release the lock if we gained it in the first place
        if self.have_lock:
            self.cache.delete(self.key)
            self.locks.remove(self.key)

def make_lock_factory(cache):
    def factory(key):
        return MemcacheLock(key, cache)
    return factory
