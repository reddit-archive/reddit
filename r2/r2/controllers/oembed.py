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

from datetime import datetime

from pylons import g, response
from pylons.i18n import _

from r2.controllers.reddit_base import MinimalController
from r2.lib import embeds
from r2.lib.base import abort
from r2.lib.errors import ForbiddenError
from r2.lib.filters import scriptsafe_dumps, websafe
from r2.lib.utils import url_to_thing
from r2.lib.template_helpers import format_html, make_url_https
from r2.lib.validator import can_view_link_comments, validate, VBoolean, VUrl
from r2.models import Comment

_OEMBED_BASE = {
    "version": "1.0",
    "provider_name": "reddit",
    "provider_url": make_url_https('/'),
}


def _oembed_for(thing, **embed_options):
    """Given a Thing, return a dict of oEmbed data for that thing.

    Raises NotImplementedError if this Thing type does not yet support oEmbeds.
    """

    if isinstance(thing, Comment):
        return _oembed_comment(thing, **embed_options)

    raise NotImplementedError("Unable to render oembed for thing '%r'", thing)


def _oembed_comment(thing, **embed_options):
    link = thing.link_slow

    if not can_view_link_comments(link):
        raise ForbiddenError("Cannot access this comment.")

    if not thing._deleted:
        author = thing.author_slow
        if author._deleted:
            author_name = _("[account deleted]")
        else:
            author_name = author.name

        title = _('%(author)s\'s comment from discussion "%(title)s"') % {
            "author": author_name,
            "title": link.title,
        }
    else:
        author_name = ""
        title = ""

    html = format_html(embeds.get_inject_template(),
                       media=g.media_domain,
                       parent="true" if embed_options.get('parent') else "false",
                       live="true" if embed_options.get('live') else "false",
                       created=datetime.now(g.tz).isoformat(),
                       comment=thing.make_permalink_slow(force_domain=True),
                       link=link.make_permalink_slow(force_domain=True),
                       title=websafe(title),
                       )

    oembed_response = dict(_OEMBED_BASE,
                           type="rich",
                           title=title,
                           author_name=author_name,
                           html=html,
                           )

    if author_name:
        oembed_response['author_url'] = make_url_https('/user/' + author_name)

    return oembed_response


class OEmbedController(MinimalController):
    def try_pagecache(self):
        pass

    @validate(
        url=VUrl('url'),
        parent=VBoolean("parent", default=False),
        live=VBoolean("live", default=False),
    )
    def GET_oembed(self, url, parent, live):
        """Get the oEmbed response for a URL, if any exists.

        Spec: http://www.oembed.com/

        Optional parameters (parent, live) are passed through as embed options
        to oEmbed renderers.
        """
        response.content_type = "application/json"

        thing = url_to_thing(url)
        if not thing:
            abort(404)

        embed_options = {
            "parent": parent,
            "live": live,
        }

        try:
            return scriptsafe_dumps(_oembed_for(thing, **embed_options))
        except ForbiddenError:
            abort(403)
        except NotImplementedError:
            abort(404)
