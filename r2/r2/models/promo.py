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
# All portions of the code written by reddit are Copyright (c) 2006-2013 reddit
# Inc. All Rights Reserved.
###############################################################################

from collections import namedtuple
from datetime import datetime, timedelta
from uuid import uuid1
import json

from pylons import g, c

from r2.lib import filters
from r2.lib.cache import sgm
from r2.lib.db import tdb_cassandra
from r2.lib.db.thing import Thing, NotFound
from r2.lib.memoize import memoize
from r2.lib.utils import Enum, to_datetime
from r2.models.subreddit import Subreddit


PROMOTE_STATUS = Enum("unpaid", "unseen", "accepted", "rejected",
                      "pending", "promoted", "finished")


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


NO_TRANSACTION = 0

class PromoCampaign(Thing):
    def __getattr__(self, attr):
        val = Thing.__getattr__(self, attr)
        if attr in ('start_date', 'end_date'):
            val = to_datetime(val)
            if not val.tzinfo:
                val = val.replace(tzinfo=g.tz)
        return val

    @classmethod 
    def _new(cls, link, sr_name, bid, start_date, end_date):
        pc = PromoCampaign(link_id=link._id,
                           sr_name=sr_name,
                           bid=bid,
                           start_date=start_date,
                           end_date=end_date,
                           trans_id=NO_TRANSACTION,
                           owner_id=link.author_id)
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

    def is_freebie(self):
        return self.trans_id < 0

    def is_live_now(self):
        now = datetime.now(g.tz)
        return self.start_date < now and self.end_date > now

    def update(self, start_date, end_date, bid, sr_name, trans_id, commit=True):
        self.start_date = start_date
        self.end_date = end_date
        self.bid = bid
        self.sr_name = sr_name
        self.trans_id = trans_id
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


AdWeight = namedtuple('AdWeight', 'link weight campaign')


class LiveAdWeights(object):
    """Data store for per-subreddit lists of currently running ads"""
    __metaclass__ = tdb_cassandra.ThingMeta
    _use_db = True
    _connection_pool = 'main'
    _type_prefix = None
    _cf_name = None
    _compare_with = tdb_cassandra.ASCII_TYPE
    # TTL is 12 hours, to avoid unexpected ads running indefinitely
    # See note in set_all_from_weights() for more information
    _ttl = timedelta(hours=12)

    column = 'adweights'
    cache = g.cache
    cache_prefix = 'live-adweights-'

    ALL_ADS = 'all'
    FRONT_PAGE = 'frontpage'

    def __init__(self):
        raise NotImplementedError()

    @classmethod
    def to_columns(cls, weights):
        """Generate a serializable dict representation weights"""
        return {cls.column: json.dumps(weights)}

    @classmethod
    def from_columns(cls, columns):
        """Given a (serializable) dict, restore the weights"""
        weights = json.loads(columns.get(cls.column, '[]')) if columns else []
        # JSON doesn't have the concept of tuples; this restores the return
        # value to being a list of tuples.
        return [AdWeight(*w) for w in weights]

    @classmethod
    def _load_multi(cls, sr_ids):
        skeys = {sr_id: str(sr_id) for sr_id in sr_ids}
        adweights = cls._cf.multiget(skeys.values(), columns=[cls.column])
        res = {}
        for sr_id in sr_ids:
            # The returned dictionary should include all sr_ids, so
            # that ad-less SRs are inserted into the cache
            res[skeys[sr_id]] = adweights.get(sr_id, {})
        return res

    @classmethod
    def get(cls, sr_ids):
        """Return a dictionary of sr_id -> list of ads for each of sr_ids"""
        # Mangling: Caller convention is to use empty string for FRONT_PAGE
        sr_ids = [(sr_id or cls.FRONT_PAGE) for sr_id in sr_ids]
        adweights = sgm(cls.cache, sr_ids, cls._load_multi,
                        prefix=cls.cache_prefix, stale=True)
        results = {sr_id: cls.from_columns(adweights[sr_id])
                   for sr_id in adweights}
        if cls.FRONT_PAGE in results:
            results[''] = results.pop(cls.FRONT_PAGE)
        return results

    @classmethod
    def get_live_subreddits(cls):
        q = cls._cf.get_range()
        results = []
        empty = {cls.column: '[]'}
        for sr_id, columns in q:
            if sr_id in (cls.ALL_ADS, cls.FRONT_PAGE):
                continue
            if not columns or columns == empty:
                continue
            results.append(int(sr_id))
        return results

    @classmethod
    def set_all_from_weights(cls, all_weights):
        """Given a dictionary with all ads that should currently be running
        (where the dictionary keys are the subreddit IDs, and the paired
        value is the list of ads for that subreddit), update the ad system
        to use those ads on those subreddits.

        Note: Old ads are not cleared out. It is expected that the caller
        include empty-list entries in `all_weights` for any Subreddits
        that should be cleared.

        """
        weights = {}
        all_ads = []
        for sr_id, sr_ads in all_weights.iteritems():
            all_ads.extend(sr_ads)
            weights[str(sr_id)] = cls.to_columns(sr_ads)
        weights[cls.ALL_ADS] = cls.to_columns(all_ads)

        cls._cf.batch_insert(weights, ttl=cls._ttl)

        # Prep the cache!
        cls.cache.set_multi(weights, prefix=cls.cache_prefix)

    @classmethod
    def clear(cls, sr_id):
        """Clear ad information from the Subreddit with ID `sr_id`"""
        cls.set_all_from_weights({sr_id: []})
