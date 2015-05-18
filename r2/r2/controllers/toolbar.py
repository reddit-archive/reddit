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
import re
import string

from pylons import c

from reddit_base import RedditController
from r2.lib import utils
from r2.lib.filters import spaceCompress, safemarkdown
from r2.lib.menus import CommentSortMenu
from r2.lib.pages import *
from r2.lib.pages.things import hot_links_by_url_listing, wrap_links
from r2.lib.template_helpers import add_sr
from r2.lib.validator import *
from r2.models import *
from r2.models.admintools import is_shamed_domain

# strips /r/foo/, /s/, or both
strip_sr          = re.compile('\A/r/[a-zA-Z0-9_-]+')
strip_s_path      = re.compile('\A/s/')
leading_slash     = re.compile('\A/+')
has_protocol      = re.compile('\A[a-zA-Z_-]+:')
allowed_protocol  = re.compile('\Ahttps?:')
need_insert_slash = re.compile('\Ahttps?:/[^/]')
def demangle_url(path):
    # there's often some URL mangling done by the stack above us, so
    # let's clean up the URL before looking it up
    path = strip_sr.sub('', path)
    path = strip_s_path.sub('', path)
    path = leading_slash.sub("", path)

    if has_protocol.match(path):
        if not allowed_protocol.match(path):
            return None
    else:
        path = 'http://%s' % path

    if need_insert_slash.match(path):
        path = string.replace(path, '/', '//', 1)

    path = utils.sanitize_url(path)

    return path

def match_current_reddit_subdomain(url):
    # due to X-Frame-Options: SAMEORIGIN headers, we can't frame mismatched
    # reddit subdomains
    parsed = UrlParser(url)
    if parsed.is_reddit_url():
        parsed.hostname = request.host
        return parsed.unparse()
    else:
        return url

def force_html():
    """Because we can take URIs like /s/http://.../foo.png, and we can
       guarantee that the toolbar will never be used with a non-HTML
       render style, we don't want to interpret the extension from the
       target URL. So here we rewrite Middleware's interpretation of
       the extension to force it to be HTML
    """

    c.render_style = 'html'
    c.extension = None
    c.content_type = 'text/html; charset=UTF-8'

def auto_expand_panel(link):
    if not link.num_comments or link.is_self:
        return False
    else:
        return c.user.pref_frame_commentspanel

class ToolbarController(RedditController):

    allow_stylesheets = True

    @validate(link1 = VByName('id'),
              link2 = VLink('id', redirect = False))
    def GET_goto(self, link1, link2):
        """Support old /goto?id= urls. deprecated"""
        link = link2 if link2 else link1
        if link:
            return self.redirect(add_sr("/tb/" + link._id36))
        return self.abort404()

    @validate(link = VLink('id'))
    def GET_tb(self, link):
        '''/tb/$id36, show a given link with the toolbar
        If the user doesn't have the toolbar enabled, redirect to comments
        page.
        
        '''
        from r2.lib.media import thumbnail_url
        redirect_url = None
        query_params = dict(request.GET)
        if not link:
            return self.abort404()
        elif not link.subreddit_slow.can_view(c.user):
            # don't disclose the subreddit/title of a post via the redirect url
            self.abort403()
        elif link.is_self:
            redirect_url = link.url
        elif not (c.user_is_loggedin and c.user.uses_toolbar):
            redirect_url = link.make_permalink_slow(force_domain=True)
        
        if redirect_url:
            if query_params:
                url = UrlParser(redirect_url)
                url.update_query(**query_params)
                redirect_url =  url.unparse()
            return self.redirect(redirect_url)

        # if the domain is shame-banned, bail out.
        if is_shamed_domain(link.url)[0]:
            self.abort404()

        if link.has_thumbnail:
            thumbnail = thumbnail_url(link)
        else:
            thumbnail = None

        res = Frame(
            title=link.title,
            url=match_current_reddit_subdomain(link.url),
            thumbnail=thumbnail,
            fullname=link._fullname,
        )
        return spaceCompress(res.render())

    @validate(urloid=nop('urloid'))
    def GET_s(self, urloid):
        """/s/http://..., show a given URL with the toolbar. if it's
           submitted, redirect to /tb/$id36"""
        force_html()
        path = demangle_url(request.fullpath)

        if not path:
            # it was malformed
            self.abort404()

        # if the domain is shame-banned, bail out.
        if is_shamed_domain(path)[0]:
            self.abort404()

        listing = hot_links_by_url_listing(path, sr=c.site, num=1)
        link = listing.things[0] if listing.things else None

        if c.cname and not c.authorized_cname:
            # In this case, we make some bad guesses caused by the
            # cname frame on unauthorised cnames. 
            # 1. User types http://foo.com/http://myurl?cheese=brie
            #    (where foo.com is an unauthorised cname)
            # 2. We generate a frame that points to
            #    http://www.reddit.com/r/foo/http://myurl?cnameframe=0.12345&cheese=brie
            # 3. Because we accept everything after the /r/foo/, and
            #    we've now parsed, modified, and reconstituted that
            #    URL to add cnameframe, we really can't make any good
            #    assumptions about what we've done to a potentially
            #    already broken URL, and we can't assume that we've
            #    rebuilt it in the way that it was originally
            #    submitted (if it was)
            # We could try to work around this with more guesses (by
            # having demangle_url try to remove that param, hoping
            # that it's not already a malformed URL, and that we
            # haven't re-ordered the GET params, removed
            # double-slashes, etc), but for now, we'll just refuse to
            # do this operation
            return self.abort404()

        if link:
            # we were able to find it, let's send them to the
            # toolbar (if enabled) or comments (if not)
            return self.redirect(add_sr("/tb/" + link._id36))
        else:
            # It hasn't been submitted yet. Give them a chance to
            qs = utils.query_string({"url": path})
            return self.redirect(add_sr("/submit" + qs))

    @validate(link = VLink('id'))
    def GET_comments(self, link):
        if not link:
            self.abort404()
        if not link.subreddit_slow.can_view(c.user):
            abort(403, 'forbidden')

        links = list(wrap_links(link))
        if not links:
            # they aren't allowed to see this link
            return abort(403, 'forbidden')
        link = links[0]

        wrapper = make_wrapper(render_class = StarkComment,
                               target = "_top")
        b = TopCommentBuilder(link, CommentSortMenu.operator('confidence'),
                              num=10, wrap=wrapper)

        listing = NestedListing(b, parent_name=link._fullname)

        raw_bar = strings.comments_panel_text % dict(
            fd_link=link.permalink)

        md_bar = safemarkdown(raw_bar, target="_top")

        res = RedditMin(content=CommentsPanel(link=link,
                                              listing=listing.listing(),
                                              expanded=auto_expand_panel(link),
                                              infobar=md_bar))

        return res.render()

    @validate(link = VByName('id'),
              url = nop('url'))
    def GET_toolbar(self, link, url):
        """The visible toolbar, with voting buttons and all"""
        if url:
            url = demangle_url(url)

        if link:
            wrapped = wrap_links(link, wrapper=FrameToolbar, num=1)
        else:
            return self.abort404()

        return spaceCompress(wrapped.render())

    @validate(link = VByName('id'))
    def GET_inner(self, link):
        """The intermediate frame that displays the comments side-bar
           on one side and the link on the other"""
        if not link:
            return self.abort404()

        res = InnerToolbarFrame(
            link=link,
            url=match_current_reddit_subdomain(link.url),
            expanded=auto_expand_panel(link),
        )
        return spaceCompress(res.render())

    @validate(link = VLink('linkoid'))
    def GET_linkoid(self, link):
        if not link:
            return self.abort404()
        return self.redirect(add_sr("/tb/" + link._id36))

