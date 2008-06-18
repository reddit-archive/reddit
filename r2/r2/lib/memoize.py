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
from r2.config import cache
import sha

class NoneResult(object): pass

def memoize(iden, time = 0):
    def memoize_fn(fn):
        from r2.lib.memoize import NoneResult
        def new_fn(*a, **kw):
            key = iden + str(a) + str(kw)
            #print 'CHECKING', key
            res = cache.get(key)
            if res is None:
                res = fn(*a, **kw)
                if res is None:
                    res = NoneResult
                cache.set(key, res, time = time)
            if res == NoneResult:
                res = None
            return res
        return new_fn
    return memoize_fn

def clear_memo(iden, *a, **kw):
    key = iden + str(a) + str(kw)
    #print 'CLEARING', key
    cache.delete(key)

@memoize('test')
def test(x, y):
    import time
    time.sleep(1)
    if x + y == 10:
        return None
    else:
        return x + y
