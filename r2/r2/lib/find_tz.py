# "The contents of this file are subject to the Common Public Attribution
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
# All portions of the code written by CondeNet are Copyright (c) 2006-2008
# CondeNet, Inc. All Rights Reserved.
################################################################################
from r2.models.link import Link
from r2.lib.db import tdb_sql
import pytz
import sqlalchemy as sa
from r2.lib.db.operators import desc
import r2.lib.db.sorts as sorts
from datetime import datetime

def find_tz():
    q = Link._query(sort = desc('_hot'), limit = 1)
    link = list(q)[0]
    t = tdb_sql.types_id[Link._type_id].thing_table

    s = sa.select([sa.func.hot(t.c.ups, t.c.downs, t.c.date),
                   t.c.thing_id],
                  t.c.thing_id == link._id)
    db_hot = s.execute().fetchall()[0].hot.__float__()

    db_hot == round(db_hot, 7)

    for tz_name in pytz.common_timezones:
        tz = pytz.timezone(tz_name)
        sorts.epoch = datetime(1970, 1, 1, tzinfo = tz)
        
        if db_hot == link._hot:
            print tz_name

if __name__ == '__main__':
    find_tz()
