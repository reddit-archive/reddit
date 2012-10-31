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
# All portions of the code written by reddit are Copyright (c) 2006-2012 reddit
# Inc. All Rights Reserved.
###############################################################################

from datetime import datetime
from uuid import uuid1

from pylons import g, c

from r2.lib import filters
from r2.lib.db import tdb_cassandra
from r2.lib.db.thing import Thing, NotFound
from r2.lib.memoize import memoize
from r2.lib.utils import Enum
from r2.models import Link


PROMOTE_STATUS = Enum("unpaid", "unseen", "accepted", "rejected",
                      "pending", "promoted", "finished")


@memoize("get_promote_srid")
def get_promote_srid(name = 'promos'):
    from r2.models.subreddit import Subreddit
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


