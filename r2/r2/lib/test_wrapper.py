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
from utils import Wrapped, storify

def t1():
    w = Wrapped(foo = 1, bar = 2)
    assert(w.foo == 1)
    assert(w.bar == 2)

class Foo(Wrapped):
    defaults = dict(foo = 1,
                    bar = 3)

def t2():
    f = Foo(bar = 2)
    assert(f.foo == 1)
    assert(f.bar == 2)

l1 = storify({'bar': 1})
l2 = storify({'bar': 2, 'baz': 3})

def t3():
    f = Foo(l1, l2, ok = 1)
    assert(f.bar == 1)
    assert(f.baz == 3)
    assert(f.ok == 1)
    #assert(f.blah == 5)

def t4():
    x = Wrapped(Foo())
    assert(x.foo == 1)
    assert(x.bar == 3)
    
t1()
t2()
t3()
t4()
