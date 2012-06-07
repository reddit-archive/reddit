import datetime

from pylons import g
from pycassa.system_manager import ASCII_TYPE, DATE_TYPE

from r2.lib.db import tdb_cassandra
from r2.lib.utils import tup


class LastModified(tdb_cassandra.View):
    _use_db = True
    _value_type = "date"
    _connection_pool = "main"
    _read_consistency_level = tdb_cassandra.CL.ONE
    _extra_schema_creation_args = dict(key_validation_class=ASCII_TYPE,
                                       default_validation_class=DATE_TYPE)

    @classmethod
    def touch(cls, fullname, names):
        names = tup(names)
        now = datetime.datetime.now(g.tz)
        values = dict.fromkeys(names, now)
        cls._set_values(fullname, values)
        return now

    @classmethod
    def get(cls, fullname, name, touch_if_not_set=False):
        try:
            obj = cls._byID(fullname)
        except tdb_cassandra.NotFound:
            if touch_if_not_set:
                time = cls.touch(fullname, name)
                return time
            else:
                return None

        return getattr(obj, name, None)

    @classmethod
    def get_multi(cls, fullnames, name):
        res = cls._byID(fullnames, return_dict=True)

        return dict((k, getattr(v, name, None))
                    for k, v in res.iteritems())
