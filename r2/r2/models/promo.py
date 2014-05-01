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

from datetime import datetime, timedelta
from uuid import uuid1

from pycassa.types import CompositeType
from pylons import g, c
from pylons.i18n import _, N_

from r2.lib import filters
from r2.lib.cache import sgm
from r2.lib.db import tdb_cassandra
from r2.lib.db.thing import Thing, NotFound
from r2.lib.memoize import memoize
from r2.lib.utils import Enum, to_datetime, to_date
from r2.models.subreddit import Subreddit


PROMOTE_STATUS = Enum("unpaid", "unseen", "accepted", "rejected",
                      "pending", "promoted", "finished")

class PriorityLevel(object):
    name = ''
    _text = N_('')
    _description = N_('')
    value = 1   # Values are from 1 (highest) to 100 (lowest)
    default = False
    inventory_override = False
    cpm = True  # Non-cpm is percentage, will fill unsold impressions

    def __repr__(self):
        return "<PriorityLevel %s: %s>" % (self.name, self.value)

    @property
    def text(self):
        return _(self._text) if self._text else ''

    @property
    def description(self):
        return _(self._description) if self._description else ''


class HighPriority(PriorityLevel):
    name = 'high'
    _text = N_('highest')
    value = 5


class MediumPriority(PriorityLevel):
    name = 'standard'
    _text = N_('standard')
    value = 10
    default = True


class RemnantPriority(PriorityLevel):
    name = 'remnant'
    _text = N_('remnant')
    _description = N_('lower priority, impressions are not guaranteed')
    value = 20
    inventory_override = True


class HousePriority(PriorityLevel):
    name = 'house'
    _text = N_('house')
    _description = N_('non-CPM, displays in all unsold impressions')
    value = 30
    inventory_override = True
    cpm = False


HIGH, MEDIUM, REMNANT, HOUSE = HighPriority(), MediumPriority(), RemnantPriority(), HousePriority()
PROMOTE_PRIORITIES = {p.name: p for p in (HIGH, MEDIUM, REMNANT, HOUSE)}
PROMOTE_DEFAULT_PRIORITY = MEDIUM


class Location(object):
    DELIMITER = '-'
    def __init__(self, country, region=None, metro=None):
        self.country = country or None
        self.region = region or None
        self.metro = metro or None

    def __repr__(self):
        return '<%s (%s/%s/%s)>' % (self.__class__.__name__, self.country,
                                    self.region, self.metro)

    def to_code(self):
        fields = [self.country, self.region, self.metro]
        return self.DELIMITER.join(i or '' for i in fields)

    @classmethod
    def from_code(cls, code):
        country, region, metro = [i or None for i in code.split(cls.DELIMITER)]
        return cls(country, region, metro)

    def contains(self, other):
        if not self.country:
            # self is set of all countries, it includes all possible
            # values of other.country
            return True
        elif not other or not other.country:
            # self is more specific than other
            return False
        else:
            # both self and other specify a country
            if self.country != other.country:
                # countries don't match
                return False
            else:
                # countries match
                if not self.metro:
                    # self.metro is set of all metros within country, it
                    # includes all possible values of other.metro
                    return True
                elif not other.metro:
                    # self is more specific than other
                    return False
                else:
                    return self.metro == other.metro


@memoize("get_promote_srid")
def get_promote_srid(name = 'promos'):
    try:
        sr = Subreddit._by_name(name, stale=True)
    except NotFound:
        sr = Subreddit._new(name = name,
                            title = "promoted links",
                            # negative author_ids make this unlisable
                            author_id = -1,
                            type = "public", 
                            ip = '0.0.0.0')
    return sr._id


def calc_impressions(bid, cpm_pennies):
    # bid is in dollars, cpm_pennies is pennies
    # CPM is cost per 1000 impressions
    return int(bid / cpm_pennies * 1000 * 100)


NO_TRANSACTION = 0

class PromoCampaign(Thing):
    _defaults = dict(
        priority_name=PROMOTE_DEFAULT_PRIORITY.name,
        trans_id=NO_TRANSACTION,
        location_code=None,
    )

    def __getattr__(self, attr):
        val = Thing.__getattr__(self, attr)
        if attr in ('start_date', 'end_date'):
            val = to_datetime(val)
            if not val.tzinfo:
                val = val.replace(tzinfo=g.tz)
        return val

    @classmethod
    def get_priority_name(cls, priority):
        if not priority in PROMOTE_PRIORITIES.values():
            raise ValueError("%s is not a valid priority" % val)
        return priority.name

    @classmethod 
    def _new(cls, link, sr_name, bid, cpm, start_date, end_date, priority,
             location):
        location_code = location.to_code() if location else None
        pc = PromoCampaign(link_id=link._id,
                           sr_name=sr_name,
                           bid=bid,
                           cpm=cpm,
                           start_date=start_date,
                           end_date=end_date,
                           trans_id=NO_TRANSACTION,
                           owner_id=link.author_id,
                           priority_name=cls.get_priority_name(priority),
                           location_code=location_code)
        pc._commit()
        return pc

    @classmethod
    def _by_link(cls, link_id):
        '''
        Returns an iterable of campaigns associated with link_id or an empty
        list if there are none.
        '''
        return cls._query(PromoCampaign.c.link_id == link_id, data=True)


    @classmethod
    def _by_user(cls, account_id):
        '''
        Returns an iterable of all campaigns owned by account_id or an empty 
        list if there are none.
        '''
        return cls._query(PromoCampaign.c.owner_id == account_id, data=True)

    @property
    def ndays(self):
        return (self.end_date - self.start_date).days

    @property
    def impressions(self):
        # deal with pre-CPM PromoCampaigns
        if not hasattr(self, 'cpm'):
            return -1
        elif not self.priority.cpm:
            return -1
        return calc_impressions(self.bid, self.cpm)

    @property
    def priority(self):
        return PROMOTE_PRIORITIES[self.priority_name]

    @property
    def location(self):
        if self.location_code is not None:
            return Location.from_code(self.location_code)
        else:
            return None

    def is_freebie(self):
        return self.trans_id < 0

    def is_live_now(self):
        now = datetime.now(g.tz)
        return self.start_date < now and self.end_date > now

    def update(self, start_date, end_date, bid, cpm, sr_name, trans_id,
               priority, location, commit=True):
        self.start_date = start_date
        self.end_date = end_date
        self.bid = bid
        self.cpm = cpm
        self.sr_name = sr_name
        self.trans_id = trans_id
        self.priority_name = self.get_priority_name(priority)
        self.location_code = location.to_code() if location else None
        if commit:
            self._commit()

    def delete(self):
        self._deleted = True
        self._commit()

class PromotionLog(tdb_cassandra.View):
    _use_db = True
    _connection_pool = 'main'
    _compare_with = tdb_cassandra.TIME_UUID_TYPE

    @classmethod
    def _rowkey(cls, link):
        return link._fullname

    @classmethod
    def add(cls, link, text):
        name = c.user.name if c.user_is_loggedin else "<AUTOMATED>"
        now = datetime.now(g.tz).strftime("%Y-%m-%d %H:%M:%S")
        text = "[%s: %s] %s" % (name, now, text)
        rowkey = cls._rowkey(link)
        column = {uuid1(): filters._force_utf8(text)}
        cls._set_values(rowkey, column)
        return text

    @classmethod
    def get(cls, link):
        rowkey = cls._rowkey(link)
        try:
            row = cls._byID(rowkey)
        except tdb_cassandra.NotFound:
            return []
        tuples = sorted(row._values().items(), key=lambda t: t[0].time)
        return [t[1] for t in tuples]


class PromotedLinkRoadblock(tdb_cassandra.View):
    _use_db = True
    _connection_pool = 'main'
    _read_consistency_level = tdb_cassandra.CL.ONE
    _write_consistency_level = tdb_cassandra.CL.QUORUM
    _compare_with = CompositeType(
        tdb_cassandra.DateType(),
        tdb_cassandra.DateType(),
    )

    @classmethod
    def _column(cls, start, end):
        start, end = map(to_datetime, [start, end])
        return {(start, end): ''}

    @classmethod
    def _dates_from_key(cls, key):
        start, end = map(to_date, key)
        return start, end

    @classmethod
    def add(cls, sr, start, end):
        rowkey = sr._id36
        column = cls._column(start, end)
        now = datetime.now(g.tz).date()
        ndays = (to_date(end) - now).days + 7
        ttl = timedelta(days=ndays).total_seconds()
        cls._set_values(rowkey, column, ttl=ttl)

    @classmethod
    def remove(cls, sr, start, end):
        rowkey = sr._id36
        column = cls._column(start, end)
        cls._remove(rowkey, column)

    @classmethod
    def is_roadblocked(cls, sr, start, end):
        rowkey = sr._id36
        start, end = map(to_date, [start, end])

        # retrieve columns for roadblocks starting before end
        try:
            columns = cls._cf.get(rowkey, column_finish=(to_datetime(end),),
                                  column_count=tdb_cassandra.max_column_count)
        except tdb_cassandra.NotFoundException:
            return False

        for key in columns.iterkeys():
            rb_start, rb_end = cls._dates_from_key(key)

            # check for overlap, end dates not inclusive
            if (start < rb_end) and (rb_start < end):
                return (rb_start, rb_end)
        return False

    @classmethod
    def get_roadblocks(cls):
        ret = []
        q = cls._cf.get_range()
        rows = list(q)
        srs = Subreddit._byID36([id36 for id36, columns in rows], data=True)
        for id36, columns in rows:
            sr = srs[id36]
            for key in columns.iterkeys():
                start, end = cls._dates_from_key(key)
                ret.append((sr.name, start, end))
        return ret
