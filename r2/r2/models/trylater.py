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
# All portions of the code written by reddit are Copyright (c) 2006-2014 reddit
# Inc. All Rights Reserved.
###############################################################################

import contextlib
import datetime

from pycassa.system_manager import TIME_UUID_TYPE

from r2.lib.db import tdb_cassandra


class TryLater(tdb_cassandra.View):
    _use_db = True
    _read_consistency_level = tdb_cassandra.CL.QUORUM
    _write_consistency_level = tdb_cassandra.CL.QUORUM
    _compare_with = TIME_UUID_TYPE

    @classmethod
    def multi_ready(cls, rowkeys, cutoff=None):
        if cutoff is None:
            cutoff = datetime.datetime.utcnow()
        return cls._cf.multiget(rowkeys,
                                column_finish=cutoff,
                                column_count=tdb_cassandra.max_column_count)

    @classmethod
    @contextlib.contextmanager
    def multi_handle(cls, rowkeys, cutoff=None):
        if cutoff is None:
            cutoff = datetime.datetime.utcnow()
        ready = cls.multi_ready(rowkeys, cutoff)
        yield ready
        for system, items in ready.iteritems():
            cls._remove(system, items.keys())

    @classmethod
    def schedule(cls, system, data, delay=None):
        if delay is None:
            delay = datetime.timedelta(minutes=60)
        key = datetime.datetime.utcnow() + delay
        cls._set_values(system, {key: data})
