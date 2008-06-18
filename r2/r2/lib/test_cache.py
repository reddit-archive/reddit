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
from cache import *

c1 = LocalCache()
c2 = Memcache(('127.0.0.1:11211',))
c = CacheChain((c1, c2))

#basic set/get
c.set('1', 1)
assert(c1.get('1') == 1)
assert(c2.get('1') == 1)
assert(c.get('1') == 1)

#python data
c.set('2', [1,2,3])
assert(c1.get('2') == [1,2,3])
assert(c2.get('2') == [1,2,3])
assert(c.get('2') == [1,2,3])

#set multi, no prefix
c.set_multi({'3':3, '4': 4})
assert(c1.get_multi(('3', '4')) == {'3':3, '4': 4})
assert(c2.get_multi(('3', '4')) == {'3':3, '4': 4})
assert(c.get_multi(('3', '4')) == {'3':3, '4': 4})

#set multi, prefix
c.set_multi({'3':3, '4': 4}, prefix='p_')
assert(c1.get_multi(('3', 4), prefix='p_') == {'3':3, 4: 4})
assert(c2.get_multi(('3', 4), prefix='p_') == {'3':3, 4: 4})
assert(c.get_multi(('3', 4), prefix='p_') == {'3':3, 4: 4})

assert(c1.get_multi(('p_3', 'p_4')) == {'p_3':3, 'p_4': 4})
assert(c2.get_multi(('p_3', 'p_4')) == {'p_3':3, 'p_4': 4})
assert(c.get_multi(('p_3', 'p_4')) == {'p_3':3, 'p_4': 4})

#incr
c.set('5', 1)
c.set('6', 1)
c.incr('5')
assert(c1.get('5'), 2)
assert(c2.get('5'), 2)
assert(c.get('5'), 2)

c.incr('5',2)
assert(c1.get('5'), 4)
assert(c2.get('5'), 4)
assert(c.get('5'), 4)

c.incr_multi(('5', '6'), 1)
assert(c1.get('5'), 5)    
assert(c2.get('5'), 5)    
assert(c.get('5'), 5)    

assert(c1.get('6'), 2)
assert(c2.get('6'), 2)
assert(c.get('6'), 2)

c.flush_all()

c.set('1', 1)
c2.set('2', 2)
c2.set('1', 4)
c.set('3', 3)

assert(c.get_multi((1,2,3)) == {1:1, 2:2, 3:3})
