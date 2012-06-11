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
from r2.lib.db.thing import MultiRelation, Relation
from r2.lib.db import tdb_cassandra
from r2.lib.db.tdb_cassandra import TdbException
from r2.lib.utils._utils import flatten

from account import Account
from link import Link, Comment

from pylons import g
from datetime import datetime, timedelta

__all__ = ['Vote', 'CassandraLinkVote', 'CassandraCommentVote', 'score_changes']

def score_changes(amount, old_amount):
    uc = dc = 0
    a, oa = amount, old_amount
    if oa == 0 and a > 0: uc = a
    elif oa == 0 and a < 0: dc = -a
    elif oa > 0 and a == 0: uc = -oa
    elif oa < 0 and a == 0: dc = oa
    elif oa > 0 and a < 0: uc = -oa; dc = -a
    elif oa < 0 and a > 0: dc = oa; uc = a
    return uc, dc

class CassandraVote(tdb_cassandra.Relation):
    _use_db = False
    _connection_pool = 'main'

    _bool_props = ('valid_user', 'valid_thing', 'organic')
    _str_props  = ('name', # one of '-1', '0', '1'
                   'notes', 'ip')

    _defaults = {'organic': False}
    _default_ttls = {'ip': 30*24*60*60}

    @classmethod
    def _rel(cls, thing1_cls, thing2_cls):
        if (thing1_cls, thing2_cls) == (Account, Link):
            return CassandraLinkVote
        elif (thing1_cls, thing2_cls) == (Account, Comment):
            return CassandraCommentVote

        raise TdbException("Can't find relation for %r(%r,%r)"
                           % (cls, thing1_cls, thing2_cls))

    @classmethod
    def _copy_from(cls, v):
        voter = v._thing1
        votee = v._thing2
        cvc = cls._rel(Account, votee.__class__)
        try:
            cv = cvc._fast_query(voter, votee)
        except tdb_cassandra.NotFound:
            cv = cvc(thing1_id = voter._id36, thing2_id = votee._id36)
        cv.name = v._name
        cv.valid_user, cv.valid_thing = v.valid_user, v.valid_thing
        if hasattr(v, 'ip'):
            cv.ip = v.ip
        if getattr(v, 'organic', False) or hasattr(cv, 'organic'):
            cv.organic = getattr(v, 'organic', False)
        cv._commit()


class VotesByLink(tdb_cassandra.View):
    _use_db = True
    _type_prefix = 'VotesByLink'
    _connection_pool = 'main'

    # _view_of = CassandraLinkVote

    @classmethod
    def get_all(cls, *link_ids):
        vbls = cls._byID(link_ids)
        
        lists = [vbl._values().keys() for vbl in vbls.values()]
        vals = flatten(lists)
        
        return CassandraLinkVote._byID(vals).values()

class VotesByDay(tdb_cassandra.View):
    _use_db = True
    _type_prefix = 'VotesByDay'
    _connection_pool = 'main'

    # _view_of = CassandraLinkVote

    @staticmethod
    def _id_for_day(dt):
        return dt.strftime('%Y-%j')

    @classmethod
    def _votes_for_period(ls, start_date, length):
        """An iterator yielding every vote that occured in the given
           period in no particular order

           start_date =:= datetime()
           length =:+ timedelta()
        """

        # n.b. because of the volume of data involved this has to do
        # multiple requests and can be quite slow

        thisdate = start_date
        while thisdate <= start_date + length:
            for voteid_chunk in in_chunks(cls._byID(cls._id_for_date(thisdate)),
                                      chunk_size=1000):
                for vote in LinkVote._byID(voteid_chunk).values():
                    yield vote

            thisdate += timedelta(days=1)

class CassandraLinkVote(CassandraVote):
    _use_db = True
    _type_prefix = 'LinkVote'
    _cf_name = 'LinkVote'
    _read_consistency_level = tdb_cassandra.CL.ONE

    # _views = [VotesByLink, VotesByDay]
    _thing1_cls = Account
    _thing2_cls = Link

    def _on_create(self):
        # it's okay if these indices get lost
        wcl = tdb_cassandra.CL.ONE

        v_id = {self._id: self._id}

        VotesByLink._set_values(self.thing2_id, v_id,
                                write_consistency_level=wcl)
        VotesByDay._set_values(VotesByDay._id_for_day(self.date), v_id,
                               write_consistency_level=wcl)

        return CassandraVote._on_create(self)

class CassandraCommentVote(CassandraVote):
    _use_db = True
    _type_prefix = 'CommentVote'
    _cf_name = 'CommentVote'
    _read_consistency_level = tdb_cassandra.CL.ONE

    _thing1_cls = Account
    _thing2_cls = Comment

class Vote(MultiRelation('vote',
                         Relation(Account, Link),
                         Relation(Account, Comment))):
    _defaults = {'organic': False}

    @classmethod
    def vote(cls, sub, obj, dir, ip, organic = False, cheater = False):
        from admintools import valid_user, valid_thing, update_score
        from r2.lib.count import incr_sr_count
        from r2.lib.db import queries

        sr = obj.subreddit_slow
        kind = obj.__class__.__name__.lower()
        karma = sub.karma(kind, sr)

        is_self_link = (kind == 'link'
                        and getattr(obj,'is_self',False))

        #check for old vote
        rel = cls.rel(sub, obj)
        oldvote = rel._fast_query(sub, obj, ['-1', '0', '1']).values()
        oldvote = filter(None, oldvote)

        amount = 1 if dir is True else 0 if dir is None else -1

        is_new = False
        #old vote
        if len(oldvote):
            v = oldvote[0]
            oldamount = int(v._name)
            v._name = str(amount)

            #these still need to be recalculated
            old_valid_thing = getattr(v, 'valid_thing', False)
            v.valid_thing = (valid_thing(v, karma, cheater = cheater)
                             and getattr(v,'valid_thing', False))
            v.valid_user = (getattr(v, 'valid_user', False)                   
                            and v.valid_thing
                            and valid_user(v, sr, karma))
        #new vote
        else:
            is_new = True
            oldamount = 0
            v = rel(sub, obj, str(amount))
            v.ip = ip
            old_valid_thing = v.valid_thing = valid_thing(v, karma, cheater = cheater)
            v.valid_user = (v.valid_thing and valid_user(v, sr, karma)
                            and not is_self_link)
            if organic:
                v.organic = organic

        v._commit()

        v._fast_query_timestamp_touch(sub)

        up_change, down_change = score_changes(amount, oldamount)

        if not (is_new and obj.author_id == sub._id and amount == 1):
            # we don't do this if it's the author's initial automatic
            # vote, because we checked it in with _ups == 1
            update_score(obj, up_change, down_change,
                         v, old_valid_thing)

        if v.valid_user:
            author = Account._byID(obj.author_id, data=True)
            author.incr_karma(kind, sr, up_change - down_change)

        #update the sr's valid vote count
        if is_new and v.valid_thing and kind == 'link':
            if sub._id != obj.author_id:
                incr_sr_count(sr)

        # now write it out to Cassandra. We'll write it out to both
        # this way for a while
        CassandraVote._copy_from(v)

        queries.changed(v._thing2, True)

        return v

    @classmethod
    def likes(cls, sub, objs):
        # generalise and put on all abstract relations?

        if not sub or not objs:
            return {}

        from r2.models import Account

        assert isinstance(sub, Account)

        rels = {}
        for obj in objs:
            try:
                types = CassandraVote._rel(sub.__class__, obj.__class__)
            except TdbException:
                # for types for which we don't have a vote rel, we'll
                # skip them
                continue

            rels.setdefault(types, []).append(obj)


        ret = {}

        for relcls, items in rels.iteritems():
            votes = relcls._fast_query(sub, items,
                                       properties=['name'])
            for cross, rel in votes.iteritems():
                ret[cross] = (True if rel.name == '1'
                              else False if rel.name == '-1'
                              else None)
        return ret

def test():
    from r2.models import Link, Account, Comment
    from r2.lib.db.tdb_cassandra import thing_cache

    assert CassandraVote._rel(Account, Link) == CassandraLinkVote
    assert CassandraVote._rel(Account, Comment) == CassandraCommentVote

    v1 = CassandraLinkVote('abc', 'def', valid_thing=True, valid_user=False)
    v1.testing = 'lala'
    v1._commit()
    print 'v1', v1, v1._id, v1._t

    v2 = CassandraLinkVote._byID('abc_def')
    print 'v2', v2, v2._id, v2._t

    if v1 != v2:
        # this can happen after running the test more than once, it's
        # not a big deal
        print "Expected %r to be the same as %r" % (v1, v2)

    v2.testing = 'lala'
    v2._commit()
    v1 = None # invalidated this

    assert CassandraLinkVote._byID('abc_def') == v2

    CassandraLinkVote('abc', 'ghi', name='1')._commit()

    try:
        print v2.falsy
        raise Exception("Got an attribute that doesn't exist?")
    except AttributeError:
        pass

    try:
        assert Vote('1', '2') is None
        raise Exception("I shouldn't be able to create _use_db==False instances")
    except TdbException:
        print "You can safely ignore the warning about discarding the uncommitted '1_2'"
    except CassandraException:
        print "Seriously?"
    except Exception, e:
        print id(e.__class__), id(TdbException.__class__)
        print isinstance(e, TdbException)
        print 'Huh?', repr(e)

    try:
        CassandraLinkVote._byID('bacon')
        raise Exception("I shouldn't be able to look up items that don't exist")
    except NotFound:
        pass

    print 'fast_query', CassandraLinkVote._fast_query('abc', ['def'])

    assert CassandraLinkVote._fast_query('abc', 'def') == v2
    assert CassandraLinkVote._byID('abc_def') == CassandraLinkVote._by_fullname('LinkVote_abc_def')

    print 'all', list(CassandraLinkVote._all()), list(VotesByLink._all())

    print 'all_by_link', VotesByLink.get_all('abc')

    print 'Localcache:', dict(thing_cache.caches[0])

