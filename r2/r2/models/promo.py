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

from r2.lib.db.thing import Thing, NotFound
from r2.lib.utils import Enum
from r2.models import Link

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

