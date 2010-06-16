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

from r2.models import Account, Link, Comment, Trial, Vote, SaveHide
from r2.lib import amqp
from time import sleep
from r2.lib.db.operators import asc, desc
from pylons import g

def run(verbose=True, sleep_time = 60, num_items = 1):
    key = "indextank_cursor"
    cursor = g.cache.get(key)
    if cursor is None:
        raise ValueError("%s is not set!" % key)
    cursor = int(cursor)

    while True:
        if verbose:
            print "Looking for %d items with _id < %d" % (num_items, cursor)
        q = Link._query(sort = desc('_id'),
                        limit = num_items)
        q._after(Link._byID(cursor))
        last_date = None
        for item in q:
            cursor = item._id
            last_date = item._date
            amqp.add_item('indextank_changes', item._fullname,
                      message_id = item._fullname,
                      delivery_mode = amqp.DELIVERY_TRANSIENT)
        g.cache.set(key, cursor)

        if verbose:
            if last_date:
                last_date = last_date.strftime("%Y-%m-%d")
            print ("Just enqueued %d items. New cursor=%s (%s). Sleeping %d seconds."
                   % (num_items, cursor, last_date, sleep_time))

        sleep(sleep_time)
