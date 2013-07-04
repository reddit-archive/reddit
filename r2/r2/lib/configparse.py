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

import re

from r2.lib.utils import timeinterval_fromstr


class ConfigValue(object):
    _bool_map = dict(true=True, false=False)

    @staticmethod
    def str(v, key=None, data=None):
        return str(v)

    @staticmethod
    def int(v, key=None, data=None):
        return int(v)

    @staticmethod
    def float(v, key=None, data=None):
        return float(v)

    @staticmethod
    def bool(v, key=None, data=None):
        if v in (True, False, None):
            return bool(v)
        try:
            return ConfigValue._bool_map[v.lower()]
        except KeyError:
            raise ValueError("Unknown value for %r: %r" % (key, v))

    @staticmethod
    def tuple(v, key=None, data=None):
        return tuple(ConfigValue.to_iter(v))

    @staticmethod
    def dict(key_type, value_type):
        def parse(v, key=None, data=None):
            return {key_type(x): value_type(y)
                    for x, y in (
                        i.split(':', 1) for i in ConfigValue.to_iter(v))}
        return parse

    @staticmethod
    def choice(v, key, data):
        if v not in data:
            raise ValueError("Unknown option for %r: %r not in %r" % (key, v, data))
        return data[v]

    @staticmethod
    def to_iter(v, delim = ','):
        return (x.strip() for x in v.split(delim) if x)

    @staticmethod
    def timeinterval(v, key=None, data=None):
        return timeinterval_fromstr(v)

    messages_re = re.compile(r'"([^"]+)"')
    @staticmethod
    def messages(v, key=None, data=None):
        return ConfigValue.messages_re.findall(v.decode("string_escape"))


class ConfigValueParser(dict):
    def __init__(self, raw_data):
        dict.__init__(self, raw_data)
        self.config_keys = {}
        self.raw_data = raw_data

    def add_spec(self, spec):
        new_keys = []
        for parser, keys in spec.iteritems():
            # keys can be either a list or a dict
            for key in keys:
                assert key not in self.config_keys
                # if keys is a dict, the value is passed as extra data to the parser.
                extra_data = keys[key] if type(keys) is dict else None
                self.config_keys[key] = (parser, extra_data)
                new_keys.append(key)
        self._update_values(new_keys)

    def _update_values(self, keys):
        for key in keys:
            if key not in self.raw_data:
                continue

            value = self.raw_data[key]
            if key in self.config_keys:
                parser, extra_data = self.config_keys[key]
                value = parser(value, key, extra_data)
            self[key] = value
