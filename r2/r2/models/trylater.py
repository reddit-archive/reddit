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
import json
import uuid

from pycassa.system_manager import TIME_UUID_TYPE, UTF8_TYPE
from pycassa.util import convert_time_to_uuid, convert_uuid_to_time
from pylons import g

from r2.lib.db import tdb_cassandra
from r2.lib.utils import tup


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
    def search(cls, rowkey, when):
        if isinstance(when, uuid.UUID):
            when = convert_uuid_to_time(when)
        try:
            return cls._cf.get(rowkey, column_start=when, column_finish=when)
        except tdb_cassandra.NotFoundException:
            return {}

    @classmethod
    def schedule(cls, system, data, delay=None):
        if delay is None:
            delay = datetime.timedelta(minutes=60)
        key = datetime.datetime.now(g.tz) + delay
        scheduled = {key: data}
        cls._set_values(system, scheduled)
        return scheduled

    @classmethod
    def unschedule(cls, rowkey, column_keys):
        column_keys = tup(column_keys)
        return cls._cf.remove(rowkey, column_keys)


class TryLaterBySubject(tdb_cassandra.View):
    _use_db = True
    _read_consistency_level = tdb_cassandra.CL.QUORUM
    _write_consistency_level = tdb_cassandra.CL.QUORUM
    _compare_with = UTF8_TYPE
    _extra_schema_creation_args = {
        "key_validation_class": UTF8_TYPE,
        "default_validation_class": TIME_UUID_TYPE,
    }
    _value_type = 'date'

    @classmethod
    def schedule(cls, system, subject, data, delay, trylater_rowkey=None):
        if trylater_rowkey is None:
            trylater_rowkey = system
        scheduled = TryLater.schedule(trylater_rowkey, data, delay)
        when = scheduled.keys()[0]

        # TTL 10 minutes after the TryLater runs just in case TryLater
        # is running late.
        ttl = (delay + datetime.timedelta(minutes=10)).total_seconds()
        coldict = {subject: when}
        cls._set_values(system, coldict, ttl=ttl)
        return scheduled

    @classmethod
    def search(cls, rowkey, subjects=None):
        try:
            if subjects:
                subjects = tup(subjects)
                return cls._cf.get(rowkey, subjects)
            else:
                return cls._cf.get(rowkey)
        except tdb_cassandra.NotFoundException:
            return {}

    @classmethod
    def unschedule(cls, rowkey, colkey, schedule_rowkey):
        colkey = tup(colkey)
        victims = cls.search(rowkey, colkey)
        for uu in victims.itervalues():
            keys = TryLater.search(schedule_rowkey, uu).keys()
            TryLater.unschedule(schedule_rowkey, keys)
        cls._cf.remove(rowkey, colkey)
