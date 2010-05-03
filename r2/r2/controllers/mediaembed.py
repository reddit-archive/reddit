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
# The Original Code is Reddit.
#
# The Original Developer is the Initial Developer.  The Initial Developer of the
# Original Code is CondeNet, Inc.
#
# All portions of the code written by CondeNet are Copyright (c) 2006-2010
# CondeNet, Inc. All Rights Reserved.
################################################################################
from validator import *
from reddit_base import RedditController

from r2.lib.scraper import scrapers
from r2.lib.pages import MediaEmbedBody

from pylons import request

class MediaembedController(RedditController):
    @validate(link = VLink('link'))
    def GET_mediaembed(self, link):
        if request.host != g.media_domain:
            # don't serve up untrusted content except on our
            # specifically untrusted domain
            return self.abort404()

        if not link or not link.media_object:
            return self.abort404()

        if isinstance(link.media_object, basestring):
            # it's an old-style string
            content = link.media_object

        elif isinstance(link.media_object, dict):
            # otherwise it's the new style, which is a dict(type=type, **args)
            media_object_type = link.media_object['type']
            scraper = scrapers[media_object_type]
            media_embed = scraper.media_embed(**link.media_object)
            content = media_embed.content

        return MediaEmbedBody(body = content).render()
