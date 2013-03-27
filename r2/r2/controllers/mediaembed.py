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

from pylons import request, g
from pylons.controllers.util import abort

from r2.controllers.reddit_base import MinimalController
from r2.lib.pages import MediaEmbedBody
from r2.lib.scraper import get_media_embed
from r2.lib.validator import validate, VLink


class MediaembedController(MinimalController):
    @validate(link = VLink('link'))
    def GET_mediaembed(self, link):
        if request.host != g.media_domain:
            # don't serve up untrusted content except on our
            # specifically untrusted domain
            abort(404)

        if not link or not link.media_object:
            abort(404)

        if isinstance(link.media_object, basestring):
            # it's an old-style string
            content = link.media_object

        elif isinstance(link.media_object, dict):
            # otherwise it's the new style, which is a dict(type=type, **args)
            media_embed = get_media_embed(link.media_object)
            content = media_embed.content

        return MediaEmbedBody(body = content).render()


class AdController(MinimalController):
    def try_pagecache(self):
        pass

    def GET_ad(self):
        return "This is a placeholder ad."
