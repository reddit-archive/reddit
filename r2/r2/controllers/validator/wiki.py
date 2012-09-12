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
# All portions of the code written by reddit are Copyright (c) 2006-2012 reddit
# Inc. All Rights Reserved.
###############################################################################

from os.path import normpath
import datetime
import re

from pylons.controllers.util import redirect_to
from pylons import c, g, request

from r2.models.wiki import WikiPage, WikiRevision
from r2.controllers.validator import Validator, validate, make_validated_kw
from r2.lib.db import tdb_cassandra


MAX_PAGE_NAME_LENGTH = g.wiki_max_page_name_length

MAX_SEPARATORS = g.wiki_max_page_separators

def wiki_validate(*simple_vals, **param_vals):
    def val(fn):
        def newfn(self, *a, **env):
            kw = make_validated_kw(fn, simple_vals, param_vals, env)
            for e in c.errors:
                e = c.errors[e]
                if e.code:
                    self.handle_error(e.code, e.name)
            return fn(self, *a, **kw)
        return newfn
    return val

def this_may_revise(page=None):
    if not c.user_is_loggedin:
        return False
    
    if c.user_is_admin:
        return True
    
    return may_revise(c.site, c.user, page)

def this_may_view(page):
    user = c.user if c.user_is_loggedin else None
    return may_view(c.site, user, page)

def may_revise(sr, user, page=None):    
    if sr.is_moderator(user):
        # Mods may always contribute
        return True
    elif sr.wikimode != 'anyone':
        # If the user is not a mod and the mode is not anyone,
        # then the user may not edit.
        return False
    
    if page and page.restricted and not page.special:
        # People may not contribute to restricted pages
        # (Except for special pages)
        return False

    if sr.is_wikibanned(user):
        # Users who are wiki banned in the subreddit may not contribute
        return False
    
    if page and not may_view(sr, user, page):
        # Users who are not allowed to view the page may not contribute to the page
        return False
    
    if not user.can_wiki():
        # Global wiki contributute ban
        return False
    
    if page and page.has_editor(user.name):
        # If the user is an editor on the page, they may edit
        return True
    
    if not sr.can_submit(user):
        # If the user can not submit to the subreddit
        # They should not be able to contribute
        return False
    
    if page and page.special:
        # If this is a special page
        # (and the user is not a mod or page editor)
        # They should not be allowed to revise
        return False
    
    if page and page.permlevel > 0:
        # If the page is beyond "anyone may contribute"
        # A normal user should not be allowed to revise
        return False
    
    if sr.is_wikicontributor(user):
        # If the user is a wiki contributor, they may revise
        return True
    
    karma = max(user.karma('link', sr), user.karma('comment', sr))
    if karma < sr.wiki_edit_karma:
        # If the user has too few karma, they should not contribute
        return False
    
    age = (datetime.datetime.now(g.tz) - user._date).days
    if age < sr.wiki_edit_age:
        # If they user's account is too young
        # They should not contribute
        return False
    
    # Otherwise, allow them to contribute
    return True

def may_view(sr, user, page):
    # User being None means not logged in
    mod = sr.is_moderator(user) if user else False
    
    if mod:
        # Mods may always view
        return True
    
    if page.special:
        # Special pages may always be viewed
        # (Permission level ignored)
        return True
    
    level = page.permlevel
    
    if level < 2:
        # Everyone may view in levels below 2
        return True
    
    if level == 2:
        # Only mods may view in level 2
        return mod
    
    # In any other obscure level,
    # (This should not happen but just in case)
    # nobody may view.
    return False

def normalize_page(page):
    # Case insensitive page names
    page = page.lower()
    
    # Normalize path
    page = normpath(page)
    
    # Chop off initial "/", just in case it exists
    page = page.lstrip('/')
    
    return page

class AbortWikiError(Exception):
    pass

page_match_regex = re.compile(r'^[\w_/]+\Z')

class VWikiPage(Validator):
    def __init__(self, param, required=True, restricted=True, modonly=False, **kw):
        self.restricted = restricted
        self.modonly = modonly
        self.required = required
        Validator.__init__(self, param, **kw)
    
    def run(self, page):
        if not page:
            # If no page is specified, give the index page
            page = "index"
        
        try:
            page = str(page)
        except UnicodeEncodeError:
            return self.set_error('INVALID_PAGE_NAME', code=400)
        
        if ' ' in page:
            new_name = page.replace(' ', '_')
            url = '%s/%s' % (c.wiki_base_url, new_name)
            redirect_to(url)
        
        if not page_match_regex.match(page):
            return self.set_error('INVALID_PAGE_NAME', code=400)
        
        page = normalize_page(page)
        
        c.page = page
        if (not c.is_wiki_mod) and self.modonly:
            return self.set_error('MOD_REQUIRED', code=403)
        
        try:
            wp = self.validpage(page)
        except AbortWikiError:
            return
        
        # TODO: MAKE NOT REQUIRED
        c.page_obj = wp
        
        return wp
    
    def validpage(self, page):
        try:
            wp = WikiPage.get(c.site, page)
            if self.restricted and wp.restricted:
                if not wp.special:
                    self.set_error('RESTRICTED_PAGE', code=403)
                    raise AbortWikiError
            if not this_may_view(wp):
                self.set_error('MAY_NOT_VIEW', code=403)
                raise AbortWikiError
            return wp
        except tdb_cassandra.NotFound:
            if self.required:
                self.set_error('PAGE_NOT_FOUND', code=404)
                raise AbortWikiError
            return None
    
    def validversion(self, version, pageid=None):
        if not version:
            return
        try:
            r = WikiRevision.get(version, pageid)
            if r.is_hidden and not c.is_wiki_mod:
                self.set_error('HIDDEN_REVISION', code=403)
                raise AbortWikiError
            return r
        except (tdb_cassandra.NotFound, ValueError):
            self.set_error('INVALID_REVISION', code=404)
            raise AbortWikiError

class VWikiPageAndVersion(VWikiPage):    
    def run(self, page, *versions):
        wp = VWikiPage.run(self, page)
        if c.errors:
            return
        validated = []
        for v in versions:
            try:
                validated += [self.validversion(v, wp._id) if v and wp else None]
            except AbortWikiError:
                return
        return tuple([wp] + validated)

class VWikiPageRevise(VWikiPage):
    def run(self, page, previous=None):
        wp = VWikiPage.run(self, page)
        if c.errors:
            return
        if not wp:
            return self.set_error('INVALID_PAGE', code=404)
        if not this_may_revise(wp):
            return self.set_error('MAY_NOT_REVISE', code=403)
        if previous:
            try:
                prev = self.validversion(previous, wp._id)
            except AbortWikiError:
                return
            return (wp, prev)
        return (wp, None)

class VWikiPageCreate(VWikiPage):
    def __init__(self, param, **kw):
        VWikiPage.__init__(self, param, required=False, **kw)
    
    def run(self, page):
        wp = VWikiPage.run(self, page)
        if c.errors:
            return
        if wp:
            c.error = {'reason': 'PAGE_EXISTS'}
        elif c.is_wiki_mod and WikiPage.is_special(page):
            c.error = {'reason': 'PAGE_CREATED_ELSEWHERE'}
        elif WikiPage.is_restricted(page):
            self.set_error('RESTRICTED_PAGE', code=403)
            return
        elif page.count('/') > MAX_SEPARATORS:
            c.error = {'reason': 'PAGE_NAME_MAX_SEPARATORS', 'MAX_SEPARATORS': MAX_SEPARATORS}
        elif len(page) > MAX_PAGE_NAME_LENGTH:
            c.error = {'reason': 'PAGE_NAME_LENGTH', 'max_length': MAX_PAGE_NAME_LENGTH}
        return this_may_revise()
               
