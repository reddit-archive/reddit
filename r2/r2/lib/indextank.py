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
"""
    Module for reddit-level communication with IndexTank
"""

from pylons import g, config
import cPickle as pickle
from time import sleep

from r2.models import *
from r2.lib import amqp
from r2.lib.contrib import indextank_clientv1
from r2.lib.utils import in_chunks, progress, get_after, UrlParser
from r2.lib.utils import domain, strordict_fullname

indextank_indexed_types = (Link,)

sorts = dict(relevance = 1,
             new = 2,
             top = 3)

index = indextank_clientv1.ApiClient(g.INDEXTANK_API_URL).get_index('main')


class Results(object):
    __slots__ = ['docs', 'hits']

    def __init__(self, docs, hits):
        self.docs = docs
        self.hits = hits

    def __repr__(self):
        return '%s(%r,%r)' % (self.__class__.__name__,
                              self.docs,
                              self.hits)

class IndextankQuery(object):
    def __init__(self, query, sr, sort):
        self.query, self.sr, self.sort = query, sr, sort

    def __repr__(self):
        return '%s(%r,%r,%r)' % (self.__class__.__name__,
                                 self.query, self.sr, self.sort)

    def run(self, after=None, reverse=False, num=1000, _update=False):
        results = self._run(_update=_update)

        docs, hits = results.docs, results.hits

        after_docs = get_after(docs,
                               after, num, reverse=reverse)

        return Results(after_docs, hits)

    def _req_fs(self, sr_ids, field='sr_id'):
        if len(sr_ids) == 1:
            return '+%s:%d' % (field, sr_ids[0])
        else:
            return '+(%s)' % ' OR '.join(('%s:%s' % (field, sr_id))
                                         for sr_id in sr_ids)

    def _run(self, start=0, num=1000, _update=False):
        q = []
        q.append(self.query)

        if self.sr == All or not self.sr or self.sr == Default:
            pass
        #elif self.sr == Default:
        #    q.append(self._req_fs(
        #            Subreddit.user_subreddits(c.user,over18=c.over18,
        #                                      ids=True, limit=None)))
        elif isinstance(self.sr, MultiReddit):
            q.append(self._req_fs(
                    self.sr.sr_ids))
        elif self.sr == Friends and c.user_is_loggedin and c.user.friends:
            friend_ids = c.user.friends[:100] # we're not about to
                                              # look up more than 100
                                              # of these

            friends = Account._byID(friend_ids, data=True, return_dict=False)
            friend_names = map(lambda x: x.name, friends)

            q.append(self._req_fs(
                    friend_names, field='author'))
        elif isinstance(self.sr, ModContribSR):
            q.append(self._req_fs(
                    self.sr.sr_ids()))
        elif not isinstance(self.sr, FakeSubreddit):
            q.append(self._req_fs([self.sr._id]))

        query = ' '.join(q)

        return self._run_cached(query, sorts[self.sort], start=start, num=num,
                                _update=_update)
        
    @classmethod
    def _run_cached(cls, query, sort, start=0, num=1000, _update=False):
        # we take and ignore the _update parameter to make plugging in
        # a @memoize later easy

        if g.sqlprinting:
            g.log.info('%s: %r %r' % (cls.__name__, query, sort))

        resp = index.search(query.encode('utf-8'), start=start, len=num,
                            scoring_function=sort)

        docs = [t['docid'] for t in resp['results']]
        hits = resp['matches']

        return Results(docs, hits)

def yesno(b):
    return 'yes' if b else 'no'

def maps_from_things(things, boost_only = False):
    """We only know how to do links for now"""

    maps = []

    if not boost_only:
        # we can avoid looking these up at all if only the boosts were
        # updated

        author_ids = [thing.author_id for thing in things
                      if hasattr(thing, 'author_id') ]
        accounts = Account._byID(author_ids, data = True, return_dict = True)

        sr_ids = [thing.sr_id for thing in things
                  if hasattr(thing, 'sr_id')]
        srs = Subreddit._byID(sr_ids, data=True, return_dict=True)

    for thing in things:
        try:
            d = dict(fullname = thing._fullname,
                     ups = thing._ups,
                     downs = thing._downs,
                     num_comments = getattr(thing, 'num_comments', 0))

            if not boost_only:
                a = accounts[thing.author_id]
                sr = srs[thing.sr_id]

                if a._deleted:
                    # if the author was deleted, we won't updated it in
                    # indextank at all
                    continue

                d.update(dict(fullname = thing._fullname,
                              subreddit = sr.name,
                              reddit = sr.name,
                              text = ' '.join([thing.title, a.name, sr.name]),
                              author = a.name,
                              timestamp = thing._date.strftime("%s"),
                              sr_id = str(thing.sr_id),
                              over18 = yesno(sr.over_18),
                              is_self = yesno(thing.is_self),
                              ))
                if thing.is_self:
                    d['site'] = g.domain
                    if thing.selftext:
                        d['selftext'] = thing.selftext
                else:
                    d['url'] = thing.url
                    d['site'] = ' '.join(UrlParser(thing.url).domain_permutations())
            maps.append(d)
        except AttributeError:
            pass
    return maps

def to_variables(ups, downs, num_comments):
    return {0: ups,
            1: downs,
            2: num_comments}

def inject_maps(maps, boost_only=False):
    for d in maps:
        fullname = d.pop("fullname")
        ups = d.pop("ups")
        downs = d.pop("downs")
        num_comments = d.pop("num_comments")
        boosts = to_variables(ups, downs, num_comments)

        if boost_only:
            index.update_variables(docid=fullname, variables=boosts)
        else:
            index.add_document(docid=fullname, fields=d, variables=boosts)

def delete_thing(thing):
    index.delete_document(docid=thing._fullname)

def inject(things, boost_only=False):
    things = [x for x in things if isinstance(x, indextank_indexed_types)]

    update_things = [x for x in things if not x._spam and not x._deleted
                     and x.promoted is None
                     and getattr(x, 'sr_id', None) != -1]
    delete_things = [x for x in things if x._spam or x._deleted]

    if update_things:
        maps = maps_from_things(update_things, boost_only = boost_only)
        inject_maps(maps, boost_only=boost_only)
    if delete_things:
        for thing in delete_things:
            delete_thing(thing)

def rebuild_index(after_id = None, estimate=10000000):
    cls = Link

    # don't pull spam/deleted
    q = cls._query(sort=desc('_date'), data=True)

    if after_id:
        q._after(cls._byID(after_id))

    q = fetch_things2(q)

    def key(link):
        # we're going back in time, so this will give us a good idea
        # of how far we've gone
        return "%s/%s" % (link._id, link._date)

    q = progress(q, verbosity=1000, estimate=estimate, persec=True, key=key)
    for chunk in in_chunks(q):
        inject(chunk)

def run_changed(drain=False, limit=1000):
    """
        Run by `cron` (through `paster run`) on a schedule to send Things to
        IndexTank
    """
    def _run_changed(msgs, chan):
        changed = map(lambda x: strordict_fullname(x.body), msgs)

        boost = set()
        add = set()

        # an item can request that only its boost fields be updated,
        # so we need to separate those out

        for item in changed:
            fname = item['fullname']
            boost_only = item.get('boost_only', False)

            if fname in add:
                # we're already going to do all of the work
                continue

            if boost_only:
                boost.add(fname)
            else:
                if fname in boost:
                    # we've previously seen an instance of this fname
                    # that requested that only its boosts be updated,
                    # but now we have to update the whole thing
                    boost.remove(fname)

                add.add(fname)

        things = Thing._by_fullname(boost | add, data=True, return_dict=True)

        print ("%d messages: %d docs, %d boosts (%d duplicates, %s remaining)"
               % (len(changed),
                  len(add),
                  len(boost),
                  len(changed) - len(things),
                  msgs[-1].delivery_info.get('message_count', 'unknown'),
               ))

        if boost:
            inject([things[fname] for fname in boost], boost_only=True)
        if add:
            inject([things[fname] for fname in add])

    amqp.handle_items('indextank_changes', _run_changed, limit=limit,
                      drain=drain, verbose=False)
