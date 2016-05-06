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


from datetime import datetime, timedelta
import uuid

from pycassa.system_manager import ASCII_TYPE, UTF8_TYPE, DATE_TYPE

from r2.lib.db import tdb_cassandra
from r2.lib.db.operators import desc

TTL = timedelta(days=10)

class Sitemap(tdb_cassandra.View):
    """Sitemaps that store the current state of the reddits.

    See: http://www.sitemaps.org/protocol.html

    We use a method of indirection to store the actual sitemaps. Even
    though `Sitemap._retrieve_sitemap(Sitemap.INDEX_KEY)` can be used to get
    the sitemap index, it's not the same as `Sitemap._byID(Sitemap.INDEX_KEY)`.

    Instead for every batch update we create a unique subkey.
    `Sitemap._byID(Sitemap.INDEX_KEY)`. Then returns the INDEX_KEY appended
    to the current subkey. We then use that to retrieve the actual sitemap.
    """

    _use_db = True
    _ttl = TTL

    INDEX_KEY = 'key'
    SUBREDDIT_KEY = 'subreddit_{0}'

    @classmethod
    def sitemap_index(cls):
        """Find the current sitemap index."""
        return cls._retrieve_sitemap(cls.INDEX_KEY)

    @classmethod
    def subreddit_sitemap(cls, index):
        """Find one of the sitemaps dedicated to subreddit links."""
        return cls._retrieve_sitemap(cls._subreddit_key(index))

    @classmethod
    def add_subreddit_sitemap(cls, sitemap, index, subkey):
        key = cls._subreddit_key(index)
        joined_key = cls._joined_key(key, subkey)
        cls._set_values(joined_key, {'sitemap': sitemap})
        cls._set_values(key, {'latest': joined_key})

    @classmethod
    def add_sitemap_index(cls, sitemap_index, subkey):
        joined_key = cls._joined_key(cls.INDEX_KEY, subkey)
        cls._set_values(joined_key, {'sitemap': sitemap_index})
        cls._set_values(cls.INDEX_KEY, {'latest': joined_key})

    @staticmethod
    def generate_subkey():
        return datetime.now().strftime('%y%m%d%H%M%S')

    @classmethod
    def _retrieve_sitemap(cls, sitemap_key):
        joined_key = cls._byID(sitemap_key).latest
        return cls._byID(joined_key).sitemap

    @classmethod
    def _subreddit_key(cls, index):
        return cls.SUBREDDIT_KEY.format(index)

    @staticmethod
    def _joined_key(key, subkey):
        return '_'.join((key, subkey))


class SitemapUpdater(object):
    """A class that facilitates the saving of many sitemaps.

    This minimal helper class maintains the state of the subkey as well as the
    indices of the various sitemap types.

    Usage:

    >>> su = SitemapUpdater()
    >>> su.add_subreddit_sitemap(subreddit_sitemap_1)
    >>> su.add_subreddit_sitemap(subreddit_sitemap_2)
    >>> su.add_comment_page_sitemap(comment_page_sitemap)
    >>> su.add_sitemap_index(create_sitemap_index(su.count))
    >>> su.count # evaluates to 3
    """

    def __init__(self):
        self._subkey = Sitemap.generate_subkey()
        self._subreddit_count = 0

    def add_subreddit_sitemap(self, sitemap):
        Sitemap.add_subreddit_sitemap(
            sitemap, self._subreddit_count, self._subkey)
        self._subreddit_count += 1

    def add_sitemap_index(self, sitemap_index):
        Sitemap.add_sitemap_index(sitemap_index, self._subkey)

    @property
    def count(self):
        # note that sitemap indices don't count towards this count.
        return self._subreddit_count
