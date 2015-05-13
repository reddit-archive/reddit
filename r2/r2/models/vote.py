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
# All portions of the code written by reddit are Copyright (c) 2006-2015 reddit
# Inc. All Rights Reserved.
###############################################################################

import json
import collections

from r2.lib.db.thing import MultiRelation, Relation
from r2.lib.db import tdb_cassandra
from r2.lib.db.tdb_cassandra import TdbException, ASCII_TYPE, UTF8_TYPE
from r2.lib.db.sorts import epoch_seconds
from r2.lib.utils import Storage

from account import Account
from link import Link, Comment

import pytz

from pycassa.types import CompositeType, AsciiType
from pylons import g
from datetime import datetime, timedelta

__all__ = ['cast_vote', 'get_votes']


VOTE_TIMEZONE = pytz.timezone("America/Los_Angeles")


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
    # this is taken care of in r2.lib.db.queries:queue_vote
    _write_last_modified = False


class CommentVotesByAccount(VotesByAccount):
    _use_db = True
    _thing2_cls = Comment
    _views = []
    _last_modified_name = "CommentVote"
    # this is taken care of in r2.lib.db.queries:queue_vote
    _write_last_modified = False


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
    def get_details(cls, thing, voters=None):
        if isinstance(thing, Link):
            details_cls = VoteDetailsByLink
        elif isinstance(thing, Comment):
            details_cls = VoteDetailsByComment
        else:
            raise ValueError

        voter_id36s = None
        if voters:
            voter_id36s = [voter._id36 for voter in voters]

        try:
            raw_details = details_cls._byID(thing._id36, properties=voter_id36s)
        except tdb_cassandra.NotFound:
            return []

        try:
            ips = VoterIPByThing._byID(thing._fullname, properties=voter_id36s)
        except tdb_cassandra.NotFound:
            ips = None

        return raw_details.decode_details(ips=ips)

    def decode_details(self, ips=None):
        raw_details = self._values()
        details = []
        for key, value in raw_details.iteritems():
            data = Storage(json.loads(value))
            data["_id"] = key + "_" + self._id
            data["voter_id"] = key
            try:
                data["ip"] = str(getattr(ips, key))
            except AttributeError:
                data["ip"] = None
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


class VoteDetailsByDay(tdb_cassandra.View):
    _use_db = False
    _fetch_all_columns = True
    _write_consistency_level = tdb_cassandra.CL.ONE
    _compare_with = CompositeType(AsciiType(), AsciiType())
    _extra_schema_creation_args = {
        "key_validation_class": ASCII_TYPE,
        "default_validation_class": UTF8_TYPE,
    }

    @classmethod
    def _rowkey(cls, date):
        return date.strftime("%Y-%m-%d")

    @classmethod
    def create(cls, thing1, thing2s, pgvote, vote_info):
        assert len(thing2s) == 1

        voter = pgvote._thing1
        votee = pgvote._thing2

        rowkey = cls._rowkey(pgvote._date.astimezone(VOTE_TIMEZONE).date())
        colname = (voter._id36, votee._id36)
        details = {
            "direction": pgvote._name,
            "date": epoch_seconds(pgvote._date),
        }
        cls._set_values(rowkey, {colname: json.dumps(details)})

    @classmethod
    def count_votes(cls, date):
        return sum(1 for x in cls._cf.xget(cls._rowkey(date)))


@tdb_cassandra.view_of(LinkVotesByAccount)
class LinkVoteDetailsByDay(VoteDetailsByDay):
    _use_db = True


@tdb_cassandra.view_of(CommentVotesByAccount)
class CommentVoteDetailsByDay(VoteDetailsByDay):
    _use_db = True


class VoterIPByThing(tdb_cassandra.View):
    _use_db = True
    _ttl = timedelta(days=90)
    _fetch_all_columns = True
    _extra_schema_creation_args = dict(key_validation_class=ASCII_TYPE,
                                       default_validation_class=UTF8_TYPE)

    @classmethod
    def create(cls, votee_fullname, voter_id36, ip):
        cls._set_values(votee_fullname, {voter_id36: ip})


def cast_vote(sub, obj, vote_info, timer, date):
    from r2.models.admintools import valid_user, valid_thing, update_score
    from r2.lib.count import incr_sr_count

    names_by_dir = {True: "1", None: "0", False: "-1"}

    # `vote` mimics the old pg vote rel interface so downstream code doesn't
    # need to change. (but it totally needn't stay that way forever!)
    vote = Storage(
        _thing1=sub,
        _thing2=obj,
        _name=names_by_dir[vote_info["dir"]],
        _date=date,
        valid_thing=True,
        valid_user=True,
        ip=vote_info["ip"],
    )

    # these track how much ups/downs should change on `obj`
    ups_delta = 1 if int(vote._name) > 0 else 0
    downs_delta = 1 if int(vote._name) < 0 else 0

    # see if the user has voted on this thing before
    old_votes = VoteDetailsByThing.get_details(obj, [sub])
    old_vote = None
    if old_votes:
        old_vote = old_votes[0]
    timer.intermediate("cass_read_vote")

    if old_vote:
        vote._date = datetime.utcfromtimestamp(
            old_vote["date"]).replace(tzinfo=pytz.UTC)
        vote.valid_thing = old_vote["valid_thing"]
        vote.valid_user = old_vote["valid_user"]
        vote.ip = old_vote["ip"]

        if vote._name == old_vote["direction"]:
            # the old vote and new vote are the same. bail out.
            return vote

        # remove the old vote from the score
        old_direction = int(old_vote["direction"])
        ups_delta -= 1 if old_direction > 0 else 0
        downs_delta -= 1 if old_direction < 0 else 0

    # calculate valid_thing and valid_user
    sr = obj.subreddit_slow
    kind = obj.__class__.__name__.lower()
    karma = sub.karma(kind, sr)

    if vote.valid_thing:
        vote.valid_thing = valid_thing(vote, karma, vote_info["cheater"],
                                       vote_info["info"])

    if vote.valid_user:
        vote.valid_user = vote.valid_thing and valid_user(vote, sr, karma)

    if kind == "link" and getattr(obj, "is_self", False):
        # self-posts do not generate karma
        vote.valid_user = False

    g.stats.simple_event("vote.valid_thing." + str(vote.valid_thing).lower())
    g.stats.simple_event("vote.valid_user." + str(vote.valid_user).lower())

    # update various score/karma/vote counts
    if not (not old_vote and obj.author_id == sub._id and vote._name == "1"):
        # newly created objects start out with _ups = 1, so we skip updating
        # their score here if this is the author's own initial vote on it.
        old_valid_thing = old_vote["valid_thing"] if old_vote else True
        update_score(obj, ups_delta, downs_delta, vote, old_valid_thing)
        timer.intermediate("pg_update_score")

    if vote.valid_user:
        author = Account._byID(obj.author_id, data=True)
        author.incr_karma(kind, sr, ups_delta - downs_delta)
        timer.intermediate("pg_incr_karma")

    if not old_vote and vote.valid_thing and kind == "link":
        if sub._id != obj.author_id:
            incr_sr_count(sr)
            timer.intermediate("incr_sr_counts")

    # write the vote to cassandra
    VotesByAccount.copy_from(vote, vote_info["info"])
    timer.intermediate("cassavotes")

    num_votes = vote._thing2._ups + vote._thing2._downs
    if num_votes < 20 or num_votes % 10 == 0:
        # always update the search index if the thing has fewer than 20 votes
        # when the thing has more votes queue an update less often
        vote._thing2.update_search_index(boost_only=True)
        timer.intermediate("update_search_index")

    if "event" in vote_info and vote_info["event"]:
        g.events.vote_event(vote, old_vote, event_base=vote_info["event"])

    return vote


def get_votes(sub, objs):
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
