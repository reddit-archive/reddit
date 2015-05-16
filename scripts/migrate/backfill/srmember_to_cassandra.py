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

from datetime import datetime

from pylons import g

from r2.lib.db.operators import desc
from r2.lib.utils import fetch_things2, to36
from r2.models.subreddit import SRMember, SubscribedSubredditsByAccount


def migrate_srmember_subscribers():
    DUAL_WRITE_START = datetime(2015, 5, 20, 0 ,0, tzinfo=g.tz)

    q = SRMember._query(
        SRMember.c._name == "subscriber",
        SRMember.c._date < DUAL_WRITE_START,
        sort=desc("_date"),
    )

    with SubscribedSubredditsByAccount._cf.batch() as b:
        for rel in fetch_things2(q):
            sr_id = rel._thing1_id
            user_id = rel._thing2_id
            action_date = rel._date

            rowkey = to36(user_id)
            column = {to36(sr_id): action_date}
            b.insert(rowkey, column, timestamp=DUAL_WRITE_START)
