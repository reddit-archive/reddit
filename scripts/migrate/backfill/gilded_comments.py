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
"""Fill in the gilded comment listing.

This listing is stored in get_gilded_comments and seen on /comments/gilded.

"""

import datetime

from pylons import g

from r2.lib.db.queries import get_gilded_comments
from r2.lib.utils import Storage
from r2.models import GildingsByDay, Thing, Comment
from r2.models.query_cache import MAX_CACHED_ITEMS, CachedQueryMutator


date = datetime.datetime.now(g.tz)
earliest_date = datetime.datetime(2012, 10, 01, tzinfo=g.tz)

already_seen = set()
to_insert = []

while date > earliest_date and len(to_insert) < MAX_CACHED_ITEMS:
    gildings = GildingsByDay.get_gildings(date)
    fullnames = [x["thing"] for x in gildings]
    things = Thing._by_fullname(fullnames, data=True, return_dict=False)
    comments = {t._fullname: t for t in things if isinstance(t, Comment)}

    counter = 0
    for gilding in gildings:
        fullname = gilding["thing"]
        if fullname in comments and fullname not in already_seen:
            gilding["thing"] = comments[fullname]
            to_insert.append(Storage(gilding))
            already_seen.add(fullname)
            counter += 1
    date -= datetime.timedelta(days=1)

with CachedQueryMutator() as m:
    m.insert(get_gilded_comments(), to_insert)
