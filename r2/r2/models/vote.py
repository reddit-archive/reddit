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

from account import Account
from link import Link, Comment

from pylons import g


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
    _bool_props = ('valid_user', 'valid_thing', 'organic')
    _str_props  = ('name', # one of '-1', '0', '1'
                   'notes', 'ip')

    @classmethod
    def _rel(cls, thing1_cls, thing2_cls):
        if (thing1_cls, thing2_cls) == (Account, Link):
            return CassandraLinkVote
        elif (thing1_cls, thing2_cls) == (Account, Comment):
            return CassandraCommentVote

class VotesByLink(tdb_cassandra.View):
    _use_db = True
    _type_prefix = 'VotesByLink'

    # _view_of = LinkVote

    @classmethod
    def get_all(cls, link_id):
        vbl = cls._byID(link_id)
        return LinkVote._byID(vbl._t.values()).values()

class CassandraLinkVote(CassandraVote):
    _use_db = True
    _type_prefix = 'r6'
    _cf_name = 'LinkVote'

    # these parameters aren't actually meaningful, they just help
    # keep track
    # _views = [VotesByLink]
    _thing1_cls = Account
    _thing2_cls = Link

    def _on_create(self):
        try:
            vbl = VotesByLink._byID(self.thing1_id)
        except tdb_cassandra.NotFound:
            vbl = VotesByLink(_id=self.thing1_id)

        vbl[self._id] = self._id
        vbl._commit()

        CassandraVote._on_create(self)

class CassandraCommentVote(CassandraVote):
    _use_db = True
    _type_prefix = 'r5'
    _cf_name = 'CommentVote'

    # these parameters aren't actually meaningful, they just help
    # keep track
    _thing1_cls = Account
    _thing2_cls = Comment

class Vote(MultiRelation('vote',
                         Relation(Account, Link),
                         Relation(Account, Comment))):


    @classmethod
    def vote(cls, sub, obj, dir, ip, organic = False, cheater = False):
        from admintools import valid_user, valid_thing, update_score
        from r2.lib.count import incr_counts
        from r2.lib.db import queries

        sr = obj.subreddit_slow
        kind = obj.__class__.__name__.lower()
        karma = sub.karma(kind, sr)

        is_self_link = (kind == 'link'
                        and hasattr(obj,'is_self')
                        and obj.is_self)

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
            old_valid_thing = v.valid_thing
            v.valid_thing = (valid_thing(v, karma, cheater = cheater)
                             and v.valid_thing)
            v.valid_user = (v.valid_user
                            and v.valid_thing
                            and valid_user(v, sr, karma))
        #new vote
        else:
            is_new = True
            oldamount = 0
            v = rel(sub, obj, str(amount))
            v.author_id = obj.author_id
            v.sr_id = sr._id
            v.ip = ip
            old_valid_thing = v.valid_thing = \
                              valid_thing(v, karma, cheater = cheater)
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
                         v.valid_thing, old_valid_thing)

        if v.valid_user:
            author = Account._byID(obj.author_id, data=True)
            author.incr_karma(kind, sr, up_change - down_change)

        #update the sr's valid vote count
        if is_new and v.valid_thing and kind == 'link':
            if sub._id != obj.author_id:
                incr_counts([sr])

        # now write it out to Cassandra. We'll write it out to both
        # this way for a while
        voter = v._thing1
        votee = v._thing2
        cvc = CassandraVote._rel(Account, votee.__class__)
        try:
            cv = cvc._fast_query(voter._id36, votee._id36)
        except tdb_cassandra.NotFound:
            cv = cvc(thing1_id = voter._id36, thing2_id = votee._id36)
        cv.name = v._name
        cv.valid_user, cv.valid_thing = v.valid_user, v.valid_thing
        cv.ip = v.ip
        if getattr(v, 'organic', False) or hasattr(cv, 'organic'):
            cv.organic = getattr(v, 'organic', False)
        cv._commit()

        queries.changed(votee, True)

        return v

    #TODO make this generic and put on multirelation?
    @classmethod
    def likes(cls, sub, obj):
        votes = cls._fast_query(sub, obj, ('1', '-1'),
                                data=False, eager_load=False,
                                timestamp_optimize=True)
        votes = dict((tuple(k[:2]), v) for k, v in votes.iteritems() if v)
        return votes


