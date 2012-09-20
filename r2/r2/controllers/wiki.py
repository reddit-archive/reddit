## The contents of this file are subject to the Common Public Attribution
## License Version 1.0. (the "License"); you may not use this file except in
## compliance with the License. You may obtain a copy of the License at
## http://code.reddit.com/LICENSE. The License is based on the Mozilla Public
## License Version 1.1, but Sections 14 and 15 have been added to cover use of
## software over a computer network and provide for limited attribution for the
## Original Developer. In addition, Exhibit A has been modified to be
## consistent with Exhibit B.
##
## Software distributed under the License is distributed on an "AS IS" basis,
## WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License for
## the specific language governing rights and limitations under the License.
##
## The Original Code is reddit.
##
## The Original Developer is the Initial Developer.  The Initial Developer of
## the Original Code is reddit Inc.
##
## All portions of the code written by reddit are Copyright (c) 2006-2012
## reddit Inc. All Rights Reserved.
###############################################################################

from pylons import request, g, c, Response
from pylons.controllers.util import redirect_to
from reddit_base import RedditController
from r2.lib.utils import url_links
from reddit_base import paginated_listing
from r2.models.wiki import (WikiPage, WikiRevision, ContentLengthError,
                            modactions)
from r2.models.subreddit import Subreddit
from r2.models.modaction import ModAction
from r2.models.builder import WikiRevisionBuilder, WikiRecentRevisionBuilder

from r2.lib.template_helpers import join_urls


from r2.controllers.validator import VMarkdown

from r2.controllers.validator.wiki import (VWikiPage, VWikiPageAndVersion,
                                           VWikiPageRevise, VWikiPageCreate,
                                           this_may_view, wiki_validate)

from r2.lib.pages.wiki import (WikiPageView, WikiNotFound, WikiRevisions,
                              WikiEdit, WikiSettings, WikiRecent,
                              WikiListing, WikiDiscussions)

from r2.config.extensions import set_extension
from r2.lib.template_helpers import add_sr
from r2.lib.db import tdb_cassandra
from r2.controllers.errors import errors
from r2.models.listing import WikiRevisionListing
from r2.lib.pages.things import default_thing_wrapper
from r2.lib.pages import BoringPage
from reddit_base import base_listing
from r2.models import IDBuilder, LinkListing, DefaultSR
from validator.validator import VInt, VExistingUname, VRatelimit
from r2.lib.merge import ConflictException, make_htmldiff
from pylons.i18n import _
from r2.lib.pages import PaneStack
from r2.lib.utils import timesince

from r2.lib.base import abort
from r2.controllers.errors import WikiError

import json

page_descriptions = {'config/stylesheet':_("This page is the subreddit stylesheet, changes here apply to the subreddit css"),
                     'config/sidebar':_("The contents of this page appear on the subreddit sidebar")}

ATTRIBUTE_BY_PAGE = {"config/sidebar": "description",
                     "config/description": "public_description"}

class WikiController(RedditController):
    allow_stylesheets = True
    
    @wiki_validate(pv=VWikiPageAndVersion(('page', 'v', 'v2'), required=False, 
                                                          restricted=False))
    def GET_wiki_page(self, pv):
        page, version, version2 = pv
        message = None
        
        if not page:
            return self.GET_wiki_create(page=c.page, view=True)
        
        if version:
            edit_by = version.author_name()
            edit_date = version.date
        else:
            edit_by = page.author_name()
            edit_date = page._get('last_edit_date')
        
        diffcontent = None
        if not version:
            content = page.content
            if c.is_wiki_mod and page.name in page_descriptions:
                message = page_descriptions[page.name]
        else:
            message = _("viewing revision from %s") % timesince(version.date)
            if version2:
                t1 = timesince(version.date)
                t2 = timesince(version2.date)
                timestamp1 = _("%s ago") % t1
                timestamp2 = _("%s ago") % t2
                message = _("comparing revisions from %(date_1)s and %(date_2)s") \
                          % {'date_1': t1, 'date_2': t2}
                diffcontent = make_htmldiff(version.content, version2.content, timestamp1, timestamp2)
                content = version2.content
            else:
                message = _("viewing revision from %s ago") % timesince(version.date)
                content = version.content
        
        return WikiPageView(content, alert=message, v=version, diff=diffcontent,
                            edit_by=edit_by, edit_date=edit_date).render()
    
    @paginated_listing(max_page_size=100, backend='cassandra')
    @wiki_validate(page=VWikiPage(('page'), restricted=False))
    def GET_wiki_revisions(self, num, after, reverse, count, page):
        revisions = page.get_revisions()
        builder = WikiRevisionBuilder(revisions, num=num, reverse=reverse, count=count, after=after, skip=not c.is_wiki_mod, wrap=default_thing_wrapper())
        listing = WikiRevisionListing(builder).listing()
        return WikiRevisions(listing).render()
    
    @wiki_validate(may_create=VWikiPageCreate('page'))
    def GET_wiki_create(self, may_create, page, view=False):
        api = c.extension == 'json'
        
        if c.error and c.error['reason'] == 'PAGE_EXISTS':
            return self.redirect(join_urls(c.wiki_base_url, page))
        elif not may_create or api:
            if may_create and c.error:
                self.handle_error(403, **c.error)
            else:
                self.handle_error(404, 'PAGE_NOT_FOUND', may_create=may_create)
        elif c.error:
            error = ''
            if c.error['reason'] == 'PAGE_NAME_LENGTH':
                error = _("this wiki cannot handle page names of that magnitude!  please select a page name shorter than %d characters") % c.error['max_length']
            elif c.error['reason'] == 'PAGE_CREATED_ELSEWHERE':
                error = _("this page is a special page, please go into the subreddit settings and save the field once to create this special page")
            elif c.error['reason'] == 'PAGE_NAME_MAX_SEPARATORS':
                error = _('a max of %d separators "/" are allowed in a wiki page name.') % c.error['MAX_SEPARATORS']
            return BoringPage(_("Wiki error"), infotext=error).render()
        elif view:
            return WikiNotFound().render()
        elif may_create:
            WikiPage.create(c.site, page)
            url = join_urls(c.wiki_base_url, '/edit/', page)
            return self.redirect(url)
    
    @wiki_validate(page=VWikiPageRevise('page', restricted=True))
    def GET_wiki_revise(self, page, message=None, **kw):
        page = page[0]
        previous = kw.get('previous', page._get('revision'))
        content = kw.get('content', page.content)
        if not message and page.name in page_descriptions:
            message = page_descriptions[page.name]
        return WikiEdit(content, previous, alert=message).render()
    
    @paginated_listing(max_page_size=100, backend='cassandra')
    def GET_wiki_recent(self, num, after, reverse, count):
        revisions = WikiRevision.get_recent(c.site)
        builder = WikiRecentRevisionBuilder(revisions,  num=num, count=count,
                                            reverse=reverse, after=after,
                                            wrap=default_thing_wrapper(),
                                            skip=not c.is_wiki_mod)
        listing = WikiRevisionListing(builder).listing()
        return WikiRecent(listing).render()
    
    def GET_wiki_listing(self):
        def check_hidden(page):
            g.log.debug("Got here %s" % str(this_may_view(page)))
            return this_may_view(page)
        pages = WikiPage.get_listing(c.site, filter_check=check_hidden)
        return WikiListing(pages).render()
    
    def GET_wiki_redirect(self, page):
        return redirect_to(str("%s/%s" % (c.wiki_base_url, page)), _code=301)
    
    @base_listing
    @wiki_validate(page=VWikiPage('page', restricted=True))
    def GET_wiki_discussions(self, page, num, after, reverse, count):
        page_url = add_sr("%s/%s" % (c.wiki_base_url, page.name))
        links = url_links(page_url)
        builder = IDBuilder([ link._fullname for link in links ],
                            num = num, after = after, reverse = reverse,
                            count = count, skip = False)
        listing = LinkListing(builder).listing()
        return WikiDiscussions(listing).render()
    
    @wiki_validate(page=VWikiPage('page', restricted=True, modonly=True))
    def GET_wiki_settings(self, page):
        settings = {'permlevel': page._get('permlevel', 0)}
        mayedit = page.get_editors()
        return WikiSettings(settings, mayedit, show_settings=not page.special).render()
    
    @wiki_validate(page=VWikiPage('page', restricted=True, modonly=True),\
              permlevel=VInt('permlevel'))
    def POST_wiki_settings(self, page, permlevel):
        oldpermlevel = page.permlevel
        try:
            page.change_permlevel(permlevel)
        except ValueError:
            self.handle_error(403, 'INVALID_PERMLEVEL')
        description = 'Page: %s, Changed from %s to %s' % (page.name, oldpermlevel, permlevel)
        ModAction.create(c.site, c.user, 'wikipermlevel', description=description)
        return self.GET_wiki_settings(page=page.name)
    
    def handle_error(self, code, error=None, **data):
        abort(WikiError(code, error, **data))
    
    def pre(self):
        RedditController.pre(self)
        if g.wiki_disabled and not c.user_is_admin:
            self.handle_error(403, 'WIKI_DOWN')
        if not c.site._should_wiki:
            self.handle_error(404, 'NOT_WIKIABLE') # /r/mod for an example
        frontpage = isinstance(c.site, DefaultSR)
        c.wiki_base_url = '/wiki' if frontpage else '/r/%s/wiki' % c.site.name
        c.wiki_id = g.default_sr if frontpage else c.site.name
        c.page = None
        c.show_wiki_actions = True
        self.editconflict = False
        c.is_wiki_mod = (c.user_is_admin or c.site.is_moderator(c.user)) if c.user_is_loggedin else False
        c.wikidisabled = False
        
        mode = c.site.wikimode
        if not mode or mode == 'disabled':
            if not c.is_wiki_mod:
                self.handle_error(403, 'WIKI_DISABLED')
            else:
                c.wikidisabled = True

class WikiApiController(WikiController):
    @wiki_validate(pageandprevious=VWikiPageRevise(('page', 'previous'), restricted=True),
              content=VMarkdown(('content')))
    def POST_wiki_edit(self, pageandprevious, content):
        page, previous = pageandprevious
        # Use the raw POST value as we need to tell the difference between
        # None/Undefined and an empty string.  The validators use a default
        # value with both of those cases and would need to be changed. 
        # In order to avoid breaking functionality, this was done instead.
        previous = previous._id if previous else request.post.get('previous')
        try:
            if page.name == 'config/stylesheet':
                report, parsed = c.site.parse_css(content, verify=False)
                if report is None: # g.css_killswitch
                    self.handle_error(403, 'STYLESHEET_EDIT_DENIED')
                if report.errors:
                    error_items = [x.message for x in sorted(report.errors)]
                    self.handle_error(415, 'SPECIAL_ERRORS', special_errors=error_items)
                c.site.change_css(content, parsed, previous, reason=request.POST['reason'])
            else:
                try:
                    page.revise(content, previous, c.user.name, reason=request.POST['reason'])
                except ContentLengthError as e:
                    self.handle_error(403, 'CONTENT_LENGTH_ERROR', max_length = e.max_length)

                # continue storing the special pages as data attributes on the subreddit
                # object. TODO: change this to minimize subreddit get sizes.
                if page.special:
                    setattr(c.site, ATTRIBUTE_BY_PAGE[page.name], content)
                    setattr(c.site, "prev_" + ATTRIBUTE_BY_PAGE[page.name] + "_id", str(page.revision))
                    c.site._commit()

                if page.special or c.is_wiki_mod:
                    description = modactions.get(page.name, 'Page %s edited' % page.name)
                    ModAction.create(c.site, c.user, 'wikirevise', details=description)
        except ConflictException as e:
            self.handle_error(409, 'EDIT_CONFLICT', newcontent=e.new, newrevision=page.revision, diffcontent=e.htmldiff)
        return json.dumps({})
    
    @wiki_validate(page=VWikiPage('page'), user=VExistingUname('username'))
    def POST_wiki_allow_editor(self, act, page, user):
        if not c.is_wiki_mod:
            self.handle_error(403, 'MOD_REQUIRED')
        if act == 'del':
            page.remove_editor(c.username)
        else:
            if not user:
                self.handle_error(404, 'UNKNOWN_USER')
            page.add_editor(user.name)
        return json.dumps({})
    
    @wiki_validate(pv=VWikiPageAndVersion(('page', 'revision')))
    def POST_wiki_revision_hide(self, pv, page, revision):
        if not c.is_wiki_mod:
            self.handle_error(403, 'MOD_REQUIRED')
        page, revision = pv
        return json.dumps({'status': revision.toggle_hide()})
   
    @wiki_validate(pv=VWikiPageAndVersion(('page', 'revision')))
    def POST_wiki_revision_revert(self, pv, page, revision):
        if not c.is_wiki_mod:
            self.handle_error(403, 'MOD_REQUIRED')
        page, revision = pv
        content = revision.content
        author = revision._get('author')
        reason = 'reverted back %s' % timesince(revision.date)
        if page.name == 'config/stylesheet':
            report, parsed = c.site.parse_css(content)
            if report.errors:
                self.handle_error(403, 'INVALID_CSS')
            c.site.change_css(content, parsed, prev=None, reason=reason, force=True)
        else:
            try:
                page.revise(content, author=author, reason=reason, force=True)

                # continue storing the special pages as data attributes on the subreddit
                # object. TODO: change this to minimize subreddit get sizes.
                if page.special:
                    setattr(c.site, ATTRIBUTE_BY_PAGE[page.name], content)
                    setattr(c.site, "prev_" + ATTRIBUTE_BY_PAGE[page.name] + "_id", page.revision)
                    c.site._commit()
            except ContentLengthError as e:
                self.handle_error(403, 'CONTENT_LENGTH_ERROR', e.max_length)
        return json.dumps({})
    
    def pre(self):
        WikiController.pre(self)
        c.render_style = 'api'
        set_extension(request.environ, 'json')
