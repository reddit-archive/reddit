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
# All portions of the code written by reddit are Copyright (c) 2006-2014 reddit
# Inc. All Rights Reserved.
###############################################################################

import json
import collections

from r2.lib.db.thing import MultiRelation, Relation
from r2.lib.db import tdb_cassandra
from r2.lib.db.tdb_cassandra import TdbException, ASCII_TYPE, UTF8_TYPE
from r2.lib.db.sorts import epoch_seconds
from r2.lib.utils import SimpleSillyStub, Storage

from account import Account
from link import Link, Comment

from pylons import g
from datetime import datetime, timedelta

__all__ = ['Vote', 'score_changes']

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


class VotesByAccount(tdb_cassandra.DenormalizedRelation):
    _use_db = False
    _thing1_cls = Account
    _read_consistency_level = tdb_cassandra.CL.ONE

    @classmethod
    def rel(cls, thing1_cls, thing2_cls):
        if (thing1_cls, thing2_cls) == (Account, Link):
            return LinkVotesByAccount
        elif (thing1_cls, thing2_cls) == (Account, Comment):
            return CommentVotesByAccount

        raise TdbException("Can't find relation for %r(%r,%r)"
                           % (cls, thing1_cls, thing2_cls))

    @classmethod
    def copy_from(cls, pgvote, vote_info):
        rel = cls.rel(Account, pgvote._thing2.__class__)
        rel.create(pgvote._thing1, pgvote._thing2, pgvote=pgvote,
                   vote_info=vote_info)

    @classmethod
    def value_for(cls, thing1, thing2, pgvote, vote_info):
        return pgvote._name


class LinkVotesByAccount(VotesByAccount):
    _use_db = True
    _thing2_cls = Link
    _views = []
    _last_modified_name = "LinkVote"


class CommentVotesByAccount(VotesByAccount):
    _use_db = True
    _thing2_cls = Comment
    _views = []
    _last_modified_name = "CommentVote"


class VoteDetailsByThing(tdb_cassandra.View):
    _use_db = False
    _fetch_all_columns = True
    _extra_schema_creation_args = dict(key_validation_class=ASCII_TYPE,
                                       default_validation_class=UTF8_TYPE)

    @classmethod
    def create(cls, thing1, thing2s, pgvote, vote_info):
        assert len(thing2s) == 1

        voter = pgvote._thing1
        votee = pgvote._thing2

        details = dict(
            direction=pgvote._name,
            date=epoch_seconds(pgvote._date),
            valid_user=pgvote.valid_user,
            valid_thing=pgvote.valid_thing,
        )
        if vote_info and isinstance(vote_info, basestring):
            details['vote_info'] = vote_info
        cls._set_values(votee._id36, {voter._id36: json.dumps(details)})
        ip = getattr(pgvote, "ip", "")
        if ip:
            VoterIPByThing.create(votee._fullname, voter._id36, ip)

    @classmethod
    def get_details(cls, thing):
        if isinstance(thing, Link):
            details_cls = VoteDetailsByLink
        elif isinstance(thing, Comment):
            details_cls = VoteDetailsByComment
        else:
            raise ValueError

        try:
            raw_details = details_cls._byID(thing._id36)
            return raw_details.decode_details()
        except tdb_cassandra.NotFound:
            return []

    def decode_details(self):
        raw_details = self._values()
        details = []
        try:
            ips = VoterIPByThing._byID(self.votee_fullname)
        except tdb_cassandra.NotFound:
            ips = None
        for key, value in raw_details.iteritems():
            data = Storage(json.loads(value))
            data["_id"] = key + "_" + self._id
            data["voter_id"] = key
            if "ip" not in data:
                data["ip"] = getattr(ips, key, None)
            details.append(data)
        details.sort(key=lambda d: d["date"])
        return details


@tdb_cassandra.view_of(LinkVotesByAccount)
class VoteDetailsByLink(VoteDetailsByThing):
    _use_db = True

    @property
    def votee_fullname(self):
        id36 = self._id
        return Link._fullname_from_id36(id36)


@tdb_cassandra.view_of(CommentVotesByAccount)
class VoteDetailsByComment(VoteDetailsByThing):
    _use_db = True

    @property
    def votee_fullname(self):
        id36 = self._id
        return Comment._fullname_from_id36(id36)


class VoterIPByThing(tdb_cassandra.View):
    _use_db = True
    _ttl = timedelta(days=90)
    _fetch_all_columns = True
    _extra_schema_creation_args = dict(key_validation_class=ASCII_TYPE,
                                       default_validation_class=UTF8_TYPE)

    @classmethod
    def create(cls, votee_fullname, voter_id36, ip):
        cls._set_values(votee_fullname, {voter_id36: ip})


class Vote(MultiRelation('vote',
                         Relation(Account, Link),
                         Relation(Account, Comment))):
    @classmethod
    def vote(cls, sub, obj, dir, ip, vote_info = None, cheater = False,
             timer=None, date=None):
        from admintools import valid_user, valid_thing, update_score
        from r2.lib.count import incr_sr_count
        from r2.lib.db import queries

        if timer is None:
            timer = SimpleSillyStub()

        sr = obj.subreddit_slow
        kind = obj.__class__.__name__.lower()
        karma = sub.karma(kind, sr)

        is_self_link = (kind == 'link'
                        and getattr(obj,'is_self',False))

        #check for old vote
        rel = cls.rel(sub, obj)
        oldvote = rel._fast_query(sub, obj, ['-1', '0', '1']).values()
        oldvote = filter(None, oldvote)

        timer.intermediate("pg_read_vote")

        amount = 1 if dir is True else 0 if dir is None else -1

        is_new = False
        #old vote
        if len(oldvote):
            v = oldvote[0]
            oldamount = int(v._name)
            if amount == oldamount:
                return v

            v._name = str(amount)

            #these still need to be recalculated
            old_valid_thing = getattr(v, 'valid_thing', False)
            v.valid_thing = (old_valid_thing and
                             valid_thing(
                                v, karma, cheater=cheater, vote_info=vote_info)
                            )
            v.valid_user = (getattr(v, 'valid_user', False)
                            and v.valid_thing
                            and valid_user(v, sr, karma))
        #new vote
        else:
            is_new = True
            oldamount = 0
            v = rel(sub, obj, str(amount), date=date)
            v.ip = ip
            v.valid_thing = valid_thing(
                                v, karma, cheater=cheater, vote_info=vote_info)
            old_valid_thing = v.valid_thing
            v.valid_user = (v.valid_thing and valid_user(v, sr, karma)
                            and not is_self_link)

        v._commit()

        timer.intermediate("pg_write_vote")

        up_change, down_change = score_changes(amount, oldamount)

        if not (is_new and obj.author_id == sub._id and amount == 1):
            # we don't do this if it's the author's initial automatic
            # vote, because we checked it in with _ups == 1
            update_score(obj, up_change, down_change,
                         v, old_valid_thing)
            timer.intermediate("pg_update_score")

        if v.valid_user:
            author = Account._byID(obj.author_id, data=True)
            author.incr_karma(kind, sr, up_change - down_change)
            timer.intermediate("pg_incr_karma")

        #update the sr's valid vote count
        if is_new and v.valid_thing and kind == 'link':
            if sub._id != obj.author_id:
                incr_sr_count(sr)
            timer.intermediate("incr_sr_counts")

        # now write it out to Cassandra. We'll write it out to both
        # this way for a while
        VotesByAccount.copy_from(v, vote_info)
        timer.intermediate("cassavotes")

        queries.changed(v._thing2, True)
        timer.intermediate("changed")

        return v

    @classmethod
    def likes(cls, sub, objs):
        if not sub or not objs:
            return {}

        from r2.models import Account
        assert isinstance(sub, Account)

        rels = {}
        for obj in objs:
            try:
                types = VotesByAccount.rel(sub.__class__, obj.__class__)
            except TdbException:
                # for types for which we don't have a vote rel, we'll
                # skip them
                continue

            rels.setdefault(types, []).append(obj)

        dirs_by_name = {"1": True, "0": None, "-1": False}

        ret = {}
        for relcls, items in rels.iteritems():
            votes = relcls.fast_query(sub, items)
            for cross, name in votes.iteritems():
                ret[cross] = dirs_by_name[name]
        return ret
