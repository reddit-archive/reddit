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

from pylons import response

from r2.controllers.reddit_base import MinimalController
from r2.lib.db import tdb_cassandra
from r2.lib.validator import validate, VInt
from r2.models.sitemap import Sitemap

class SitemapController(MinimalController):

    def GET_index(self):
        response.content_type = 'application/xml'
        return Sitemap.sitemap_index()

    @validate(index=VInt('index', 0, 50000))
    def GET_subreddits(self, index):
        response.content_type = 'application/xml'
        try:
            return Sitemap.subreddit_sitemap(index)
        except tdb_cassandra.NotFound:
            return self.abort404()
