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

from r2.lib import mr_tools
from r2.lib import utils
from r2.lib.utils import to36
from r2.lib.db import sorts

# dumps | sort | join_comments() | combine_links | sort | store_sorts()

# just use the comment-dump query from mr_permacache with the link_id
# data field
def join_comments():
    return mr_tools.join_things(('link_id',))

def combine_links():
    @mr_tools.dataspec_m_thing(('link_id', int))
    def _process(t):
        thing_id = t.thing_id
        id36 = to36(thing_id)

        link_id = t.link_id
        link_id36 = to36(link_id)

        ups, downs, timestamp = t.ups, t.downs, t.timestamp

        yield link_id36+'_controversy', id36, sorts.controversy(ups, downs)
        yield link_id36+'_hot',         id36, sorts._hot(ups, downs, timestamp)
        yield link_id36+'_confidence',  id36, sorts.confidence(ups, downs)
        yield link_id36+'_score',       id36, sorts.score(ups, downs)
        yield link_id36+'_date',        id36, timestamp

    return mr_tools.mr_map(_process)

def store_sorts():
    from r2.models import CommentSortsCache
    from r2.lib.db.tdb_cassandra import CL

    # we're going to do our own Cassandra work here, skipping the
    # tdb_cassandra layer
    cf = CommentSortsCache._cf

    def _process(key, vals):
        vals = dict(vals)

        # this has already been serialised to strings
        cf.insert(key, vals, write_consistency_level = CL.ANY)

        return []

    return mr_tools.mr_reduce(_process)

