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
# The Original Developer is the Initial Developer.  The Initial Developer of the
# Original Code is reddit.
#
# All portions of the code written by reddit are Copyright (c) 2006-2012
# reddit, Inc. All Rights Reserved.
################################################################################
from r2.lib.db.thing import Thing, NotFound
from r2.lib.utils import Enum
from r2.models import Link

PaymentState = Enum('UNPAID', 'PAID', 'FREEBIE')
TransactionCode = Enum('NEW', 'FREEBIE')

class PromoCampaign(Thing):
    
    _defaults = dict(link_id=None,
                     sr_name='',
                     owner_id=None,
                     payment_state=PaymentState.UNPAID,
                     trans_id=TransactionCode.NEW,
                     trans_error=None,
                     bid=None,
                     start_date=None,
                     end_date=None)
    
    @classmethod 
    def _new(cls, link, sr_name, bid, start_date, end_date):
        pc = PromoCampaign(link_id=link._id,
                           sr_name=sr_name,
                           bid=bid,
                           start_date=start_date,
                           end_date=end_date,
                           owner_id=link.author_id)
        pc._commit()
        return pc

    def set_bid(self, sr_name, bid, start_date, end_date):
        self.sr_name = sr_name
        self.bid = bid
        self.start_date = start_date
        self.end_date = end_date 

    def mark_paid(self, trans_id):
        self.trans_id = trans_id
        self.payment_state = PaymentState.PAID

    def mark_freebie(self, trans_id):
        self.trans_id = trans_id
        self.payment_state = PaymentState.FREEBIE

    def mark_payment_error(self, error_msg):
        self.trans_id = TransactionCode.ERROR
        self.trans_error = error_msg

    def delete(self):
        self._deleted = True
        self._commit()

