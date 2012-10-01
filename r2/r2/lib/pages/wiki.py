from r2.lib.pages.pages import Reddit
from pylons import c
from r2.lib.wrapped import Templated
from r2.lib.menus import PageNameNav
from r2.controllers.validator.wiki import this_may_revise
from pylons.i18n import _

class WikiView(Templated):
    def __init__(self, content, edit_by, edit_date, may_revise=False, page=None, diff=None):
        self.page_content_md = content
        self.page = page
        self.diff = diff
        self.edit_by = edit_by
        self.may_revise = may_revise
        self.edit_date = edit_date
        self.base_url = c.wiki_base_url
        Templated.__init__(self)

class WikiPageListing(Templated):
    def __init__(self, pages, linear_pages, page=None):
        self.pages = pages
        self.page = page
        self.linear_pages = linear_pages
        self.base_url = c.wiki_base_url
        Templated.__init__(self)

class WikiEditPage(Templated):
    def __init__(self, page_content='', previous='', page=None, show_reason_field=True):
        self.page_content = page_content
        self.page = page
        self.previous = previous
        self.base_url = c.wiki_base_url
        self.show_reason_field = show_reason_field
        Templated.__init__(self)

class WikiPageSettings(Templated):
    def __init__(self, settings, mayedit, show_settings=True, page=None, **context):
        self.permlevel = settings['permlevel']
        self.show_settings = show_settings
        self.page = page
        self.base_url = c.wiki_base_url
        self.mayedit = mayedit
        Templated.__init__(self)

class WikiPageRevisions(Templated):
    def __init__(self, revisions, page=None):
        self.listing = revisions
        self.page = page
        Templated.__init__(self)

class WikiPageDiscussions(Templated):
    def __init__(self, listing, page=None):
        self.listing = listing
        self.page = page
        Templated.__init__(self)

class WikiBasePage(Templated):
    def __init__(self, content, action, pageactions, page=None, showtitle=False,
                description=None, **context):
        self.pageactions = pageactions
        self.page = page
        self.base_url = c.wiki_base_url
        self.action = action
        self.description = description
        if showtitle:
            self.title = action[1]
        else:
            self.title = None
        self.content = content
        Templated.__init__(self)

class WikiBase(Reddit):
    extra_page_classes = ['wiki-page']
    
    def __init__(self, content, page=None, may_revise=False, actionless=False, alert=None, **context):
        pageactions = []
        title = c.site.name
        if not actionless and page:
            title = '%s - %s' % (title, page)
            pageactions += [(page, _("view"), False)]
            if may_revise:
                pageactions += [('edit', _("edit"), True)]
            pageactions += [('revisions/%s' % page, _("history"), False)]
            pageactions += [('discussions', _("talk"), True)]
            if c.is_wiki_mod:
                pageactions += [('settings', _("settings"), True)]

        action = context.get('wikiaction', (page, 'wiki'))
        context['title'] = title
        
        if alert:
            context['infotext'] = alert
        elif c.wikidisabled:
            context['infotext'] = _("this wiki is currently disabled, only mods may interact with this wiki")
        context['content'] = WikiBasePage(content, action, pageactions, page=page, **context)
        Reddit.__init__(self, show_wiki_actions=True, **context)

class WikiPageView(WikiBase):
    def __init__(self, content, page, diff=None, **context):
        may_revise = context.get('may_revise')
        if not content and not context.get('alert'):
            if may_revise:
                context['alert'] = _("this page is empty, edit it to add some content.")
        content = WikiView(content, context.get('edit_by'), context.get('edit_date'), 
                           may_revise=may_revise, page=page, diff=diff)
        WikiBase.__init__(self, content, page=page, **context)

class WikiNotFound(WikiBase):
    def __init__(self, page, **context):
        context['alert'] = _("page %s does not exist in this subreddit") % page
        context['actionless'] = True
        content = WikiEditPage(show_reason_field=False, page=page)
        WikiBase.__init__(self, content, page, **context)

class WikiEdit(WikiBase):
    def __init__(self, content, previous, page, **context):
        content = WikiEditPage(content, previous, page)
        context['wikiaction'] = ('edit', _("editing"))
        WikiBase.__init__(self, content, page=page, **context)

class WikiSettings(WikiBase):
    def __init__(self, settings, mayedit, page, **context):
        content = WikiPageSettings(settings, mayedit, page=page, **context)
        context['wikiaction'] = ('settings', _("settings"))
        WikiBase.__init__(self, content, page=page, **context)

class WikiRevisions(WikiBase):
    def __init__(self, revisions, page, **context):
        content = WikiPageRevisions(revisions, page)
        context['wikiaction'] = ('revisions/%s' % page, _("revisions"))
        WikiBase.__init__(self, content, page=page, **context)

class WikiRecent(WikiBase):
    def __init__(self, revisions, **context):
        content = WikiPageRevisions(revisions)
        context['wikiaction'] = ('revisions', _("Viewing recent revisions for /r/%s") % c.wiki_id)
        WikiBase.__init__(self, content, showtitle=True, **context)

class WikiListing(WikiBase):
    def __init__(self, pages, linear_pages, **context):
        content = WikiPageListing(pages, linear_pages)
        context['wikiaction'] = ('pages', _("Viewing pages for /r/%s") % c.wiki_id)
        description = [_("Below is a list of pages in this wiki visible to you in this subreddit.")]
        WikiBase.__init__(self, content, description=description, showtitle=True, **context)

class WikiDiscussions(WikiBase):
    def __init__(self, listing, page, **context):
        content = WikiPageDiscussions(listing, page)
        context['wikiaction'] = ('discussions', _("discussions"))
        description = [_("Discussions are site-wide links to this wiki page."),
                       _("Submit a link to this wiki page or see other discussions about this wiki page.")]
        WikiBase.__init__(self, content, page=page, description=description, **context)

