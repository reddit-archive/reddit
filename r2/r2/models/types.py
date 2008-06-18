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
from r2.lib.db.thing import Thing, Relation, Vote

#defining types
class Link(Thing):
    _int_props = Thing._int_props + ('num_comments',)

class Account(Thing): pass

#defining relationships
class Tag(Relation(Account, Link)): pass
class LinkAuthor(Relation(Account, Link)): pass

class Friend(Relation(Account, Account)): 
    _int_props = ('extra',)

v= Vote((Account, Link))

#v.vote(spez, link, True)
#v.vote(spez, comment, False)

#v.likes(spez, links)
#v.likes(spez, comments)

#t = thing.Things(reddit.Account, name='spez')
#r = thing.Relations(reddit.Friend)
# s = Relations(Subreddit)
# a = Relations(Author, thing1_id='spezs id')

#friends of accounts named spez
#j = thing.Join(t, r, t._id == r._thing1_id)


#items in programming.reddit by spez
#join(s, a, s.thing2_id == a.thing2_id)

#create of instances
#link = Link()
#link.url = 'http://reddit.com'
#link.title = 'best website evar!'
# link.save()

# spez = Account()
# spez.name = 'spez'
# spez.password = 'tard'
# spez.save()

# t = Tag(spez, link, 'cool')
# t.save()

# #set different types of query functions
# class Link(Thing):
#     queries = dict(baseurl = sa.func(baseurl))
# q = Query(Link)
# q.filter(baseurl='google.com')
