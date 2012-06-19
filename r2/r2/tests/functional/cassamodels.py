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

def test_cassasavehide():
    from r2.models import Account, Link, CassandraSave, SavesByAccount
    from r2.lib.db import tdb_cassandra

    a = list(Account._query(sort=desc('_date'),
                            limit=1))[0]
    l = list(Link._query(sort=desc('_date'),
                         limit=1))[0]

    try:
        csh = CassandraSave._fast_query(a._id36, l._id36)
        print "Warning! Deleting!", csh
        CassandraSave._fast_query(a._id36, l._id36)._destroy()
    except tdb_cassandra.NotFound:
        pass

    csh = CassandraSave._save(a, l)
    csh._commit()
    assert CassandraSave._fast_query(a._id36, l._id36) == csh

    # check for the SavesByAccount object too
    assert SavesByAccount._byID(a._id36)[csh._id] == csh._id

    csh._destroy()

    try:
        CassandraSave._fast_query(a._id36, l._id36) == csh
        raise Exception("shouldn't exist after destroying")
    except tdb_cassandra.NotFound:
        pass

    try:
        assert csh._id not in SavesByAccount._byID(a._id36, properties = csh._id)._values()
    except tdb_cassandra.NotFound:
        pass
