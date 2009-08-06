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
# All portions of the code written by CondeNet are Copyright (c) 2006-2009
# CondeNet, Inc. All Rights Reserved.
################################################################################
from r2.lib.wrapped import Wrapped, Templated, NoTemplateFound, CachedTemplate
from r2.models import Account, Default
from r2.models import FakeSubreddit, Subreddit
from r2.models import Friends, All, Sub, NotFound, DomainSR
from r2.models import Link, Printable
from r2.config import cache
from r2.lib.jsonresponse import json_respond
from r2.lib.jsontemplates import is_api
from pylons.i18n import _, ungettext
from pylons import c, request, g
from pylons.controllers.util import abort

from r2.lib.traffic import load_traffic, load_summary
from r2.lib.captcha import get_iden
from r2.lib.filters import spaceCompress, _force_unicode, _force_utf8, unsafe
from r2.lib.menus import NavButton, NamedButton, NavMenu, PageNameNav, JsButton
from r2.lib.menus import SubredditButton, SubredditMenu
from r2.lib.menus import OffsiteButton, menu, JsNavMenu
from r2.lib.strings import plurals, rand_strings, strings, Score
from r2.lib.utils import title_to_url, query_string, UrlParser, to_js, vote_hash
from r2.lib.utils import link_duplicates
from r2.lib.template_helpers import add_sr, get_domain
from r2.lib.subreddit_search import popular_searches
from r2.lib.scraper import scrapers

import sys, random, datetime, locale, calendar, simplejson, re
import graph
from itertools import chain
from urllib import quote

from things import wrap_links, default_thing_wrapper

datefmt = _force_utf8(_('%d %b %Y'))

def get_captcha():
    if not c.user_is_loggedin or c.user.needs_captcha():
        return get_iden()

class Reddit(Templated):
    '''Base class for rendering a page on reddit.  Handles toolbar creation,
    content of the footers, and content of the corner buttons.

    Constructor arguments:

        space_compress -- run r2.lib.filters.spaceCompress on render
        loginbox -- enable/disable rendering of the small login box in the right margin
          (only if no user is logged in; login box will be disabled for a logged in user)
        show_sidebar -- enable/disable content in the right margin
        
        infotext -- text to display in a <p class="infotext"> above the content
        nav_menus -- list of Menu objects to be shown in the area below the header
        content -- renderable object to fill the main content well in the page.

    settings determined at class-declaration time

        create_reddit_box  -- enable/disable display of the "Creat a reddit" box
        submit_box         -- enable/disable display of the "Submit" box
        searcbox           -- enable/disable display of the "search" box in the header
        extension_handling -- enable/disable rendering using non-html templates
          (e.g. js, xml for rss, etc.)
    '''

    create_reddit_box  = True
    submit_box         = True
    footer             = True
    searchbox          = True
    extension_handling = True
    enable_login_cover = True
    site_tracking      = True
    show_firsttext     = True
    additional_css     = None

    def __init__(self, space_compress = True, nav_menus = None, loginbox = True,
                 infotext = '', content = None, title = '', robots = None, 
                 show_sidebar = True, footer = True, **context):
        Templated.__init__(self, **context)
        self.title          = title
        self.robots         = robots
        self.infotext       = infotext
        self.loginbox       = True
        self.show_sidebar   = show_sidebar
        self.space_compress = space_compress
        # instantiate a footer
        self.footer         = RedditFooter() if footer else None
        
        #put the sort menus at the top
        self.nav_menu = MenuArea(menus = nav_menus) if nav_menus else None

        #add the infobar
        self.infobar = None
        if self.show_firsttext and not infotext:
            if c.firsttime == 'iphone':
                infotext = strings.iphone_first
            elif c.firsttime and c.site.firsttext:
                infotext = c.site.firsttext
        if infotext:
            self.infobar = InfoBar(message = infotext)

        self.srtopbar = None
        if not c.cname:
            self.srtopbar = SubredditTopBar()

        if c.user_is_loggedin and self.show_sidebar and not is_api():
            self._content = PaneStack([ShareLink(), content])
        else:
            self._content = content
        
        self.toolbars = self.build_toolbars()

    def rightbox(self):
        """generates content in <div class="rightbox">"""
        
        ps = PaneStack(css_class='spacer')

        if self.searchbox:
            ps.append(SearchForm())

        if not c.user_is_loggedin and self.loginbox:
            ps.append(LoginFormWide())

        #don't show the subreddit info bar on cnames
        if not isinstance(c.site, FakeSubreddit) and not c.cname:
            ps.append(SubredditInfoBar())

        if self.submit_box:
            ps.append(SideBox(_('Submit a link'),
                              '/submit', 'submit',
                              sr_path = True,
                              subtitles = [strings.submit_box_text],
                              show_cover = True))
            
        if self.create_reddit_box:
           ps.append(SideBox(_('Create your own reddit'),
                              '/reddits/create', 'create',
                              subtitles = rand_strings.get("create_reddit", 2),
                              show_cover = True, nocname=True))

        #we should do this here, but unless we move the ads into a
        #template of its own, it will render above the ad
        #ps.append(ClickGadget())

        return ps

    def render(self, *a, **kw):
        """Overrides default Templated.render with two additions
           * support for rendering API requests with proper wrapping
           * support for space compression of the result
        In adition, unlike Templated.render, the result is in the form of a pylons
        Response object with it's content set.
        """
        try:
            res = Templated.render(self, *a, **kw)
            if is_api():
                res = json_respond(res)
            elif self.space_compress:
                res = spaceCompress(res)
            c.response.content = res
        except NoTemplateFound, e:
            # re-raise the error -- development environment
            if g.debug:
                s = sys.exc_info()
                raise s[1], None, s[2]
            # die gracefully -- production environment
            else:
                abort(404, "not found")
        return c.response
    
    def corner_buttons(self):
        """set up for buttons in upper right corner of main page."""
        buttons = []
        if c.user_is_loggedin:
            if c.user.name in g.admins:
                if c.user_is_admin:
                   buttons += [NamedButton("adminoff", False,
                                           nocname=not c.authorized_cname,
                                           target = "_self")]
                else:
                   buttons += [NamedButton("adminon",  False,
                                           nocname=not c.authorized_cname,
                                           target = "_self")]
            buttons += [NamedButton("prefs", False,
                                  css_class = "pref-lang")]
        else:
            lang = c.lang.split('-')[0] if c.lang else ''
            buttons += [JsButton(g.lang_name.get(lang, lang),  
                                  onclick = "return showlang();",
                                  css_class = "pref-lang")]
        return NavMenu(buttons, base_path = "/", type = "flatlist")

    def build_toolbars(self):
        """Sets the layout of the navigation topbar on a Reddit.  The result
        is a list of menus which will be rendered in order and
        displayed at the top of the Reddit."""
        main_buttons = [NamedButton('hot', dest='', aliases=['/hot']),
                        NamedButton('new'), 
                        NamedButton('controversial'),
                        NamedButton('top'),
                        NamedButton('saved', False)
                        ]

        more_buttons = []

        if c.user_is_loggedin:
            if c.user_is_admin:
                more_buttons.append(NamedButton('admin'))

            if c.user_is_sponsor:
                more_buttons.append(NamedButton('promote'))

        #if there's only one button in the dropdown, get rid of the dropdown
        if len(more_buttons) == 1:
            main_buttons.append(more_buttons[0])
            more_buttons = []

        toolbar = [NavMenu(main_buttons, type='tabmenu')]
        if more_buttons:
            toolbar.append(NavMenu(more_buttons, title=menu.more, type='tabdrop'))
        
        if c.site != Default and not c.cname:
            toolbar.insert(0, PageNameNav('subreddit'))

        return toolbar
                
    def __repr__(self):
        return "<Reddit>"

    @staticmethod
    def content_stack(panes, css_class = None):
        """Helper method for reordering the content stack."""
        return PaneStack(filter(None, panes), css_class = css_class)

    def content(self):
        """returns a Wrapped (or renderable) item for the main content div."""
        return self.content_stack((self.infobar, self.nav_menu, self._content))

class RedditHeader(Templated):
    def __init__(self):
        pass

class RedditFooter(CachedTemplate):
    def cachable_attrs(self):
        return [('path', request.path)]
    
    def nav(self):
        return [NavMenu([NamedButton("toplinks", False),
                         NamedButton("mobile", False, nocname=True),
                         OffsiteButton("rss", dest = '/.rss'),
                         NamedButton("store", False, nocname=True),
                         NamedButton("stats", False, nocname=True),
                         NamedButton('random', False, nocname=False),
                         NamedButton("feedback", False),],
                        title = _('site links'), type = 'flat_vert',
                        separator = ''),
                
                NavMenu([NamedButton("help", False, nocname=True),
                         OffsiteButton(_("FAQ"), dest = '/help/faq',
                                       nocname=True),
                         OffsiteButton(_("reddiquette"), nocname=True,
                                       dest = '/help/reddiquette')],
                        title = _('help'), type = 'flat_vert',
                        separator = ''),
                
                NavMenu([NamedButton("bookmarklets", False),
                         NamedButton("buttons", True),
                         NamedButton("code", False, nocname=True),
                         NamedButton("socialite", False),
                         NamedButton("widget", True),
                         NamedButton("iphone", False),],
                        title = _('reddit tools'), type = 'flat_vert',
                        separator = ''),
                
                NavMenu([NamedButton("blog", False, nocname=True),
                         NamedButton("ad_inq", False, nocname=True),
                         OffsiteButton('reddit.tv', "http://www.reddit.tv"),
                         OffsiteButton('redditall', "http://www.redditall.com"),
                         OffsiteButton(_('job board'),
                                       "http://www.redditjobs.com")],
                        title = _('about us'), type = 'flat_vert',
                        separator = ''),
                NavMenu([OffsiteButton('BaconBuzz',
                                       "http://www.baconbuzz.com"),
                         OffsiteButton('Destructoid reddit',
                                       "http://reddit.destructoid.com"),
                         OffsiteButton('TheCuteList',
                                       "http://www.thecutelist.com"),
                         OffsiteButton('The Independent reddit',
                                       "http://reddit.independent.co.uk"),
                         OffsiteButton('redditGadgetGuide',
                                       "http://www.redditgadgetguide.com"),
                         OffsiteButton('WeHeartGossip',
                                       "http://www.weheartgossip.com"),
                         OffsiteButton('idealistNews',
                                       "http://www.idealistnews.com"),],
                        title = _('brothers'), type = 'flat_vert',
                        separator = ''),
                NavMenu([OffsiteButton('Wired.com',
                                       "http://www.wired.com"),
                         OffsiteButton('Ars Technica',
                                       "http://www.arstechnica.com"),
                         OffsiteButton('Style.com',
                                       "http://www.style.com"),
                         OffsiteButton('Epicurious.com',
                                       "http://www.epicurious.com"),
                         OffsiteButton('Concierge.com',
                                       "http://www.concierge.com")],
                        title = _('sisters'), type = 'flat_vert',
                        separator = '')
                    ]


class ClickGadget(Templated):
    def __init__(self, links, *a, **kw):
        self.links = links
        self.content = ''
        if c.user_is_loggedin and self.links:
            self.content = self.make_content()
        Templated.__init__(self, *a, **kw)

    def make_content(self):
        #this will disable the hardcoded widget styles
        request.get.style = "off"
        wrapper = default_thing_wrapper(embed_voting_style = 'votable',
                                        style = "htmllite")
        content = wrap_links(self.links, wrapper = wrapper)

        return content.render(style = "htmllite")


class RedditMin(Reddit):
    """a version of Reddit that has no sidebar, toolbar, footer,
       etc"""
    footer       = False
    show_sidebar = False
    show_firsttext = False

class LoginFormWide(CachedTemplate):
    """generates a login form suitable for the 300px rightbox."""
    def __init__(self):
        self.cname = c.cname
        self.auth_cname = not c.frameless_cname or c.authorized_cname
        CachedTemplate.__init__(self)

class SubredditInfoBar(CachedTemplate):
    """When not on Default, renders a sidebox which gives info about
    the current reddit, including links to the moderator and
    contributor pages, as well as links to the banning page if the
    current user is a moderator."""

    def __init__(self, site = None):
        site = site or c.site
        self.spam = site._spam
        self.name = site.name
        self.type = site.type
        self.is_fake = isinstance(site, FakeSubreddit)
        self.is_loggedin = c.user_is_loggedin
        self.is_admin  = c.user_is_admin
        self.fullname = site._fullname
        self.is_subscriber = bool(c.user_is_loggedin and \
                                  site.is_subscriber_defaults(c.user))
        self.is_moderator = bool(c.user_is_loggedin and \
                                 site.is_moderator(c.user))
        self.is_contributor = bool(site.type in ("private", "restricted") and \
                                   c.user_is_loggedin and \
                                   site.is_contributor(c.user))
        self.subscribers = site._ups
        self.date = site._date
        self.banner = getattr(site, "banner", None)

        #so the menus cache properly
        self.path = request.path
        CachedTemplate.__init__(self)
    
    def nav(self):
        buttons = [NavButton(plurals.moderators, 'moderators')]
        if self.type != 'public':
            buttons.append(NavButton(plurals.contributors, 'contributors'))

        if self.is_moderator or self.is_admin:
            buttons.extend([
                    NamedButton('spam'),
                    NamedButton('reports'),
                    NavButton(menu.banusers, 'banned'),
                    NamedButton('traffic'),
                    NamedButton('edit'),
                    ])
        return [NavMenu(buttons, type = "flat_vert", base_path = "/about/",
                        separator = '')]

class SideBox(CachedTemplate):
    """
    Generic sidebox used to generate the 'submit' and 'create a reddit' boxes.
    """
    def __init__(self, title, link, css_class='', subtitles = [],
                 show_cover = False, nocname=False, sr_path = False):
        Templated.__init__(self, link = link, target = '_top',
                           title = title, css_class = css_class,
                           sr_path = sr_path, subtitles = subtitles,
                           show_cover = show_cover, nocname=nocname)


class PrefsPage(Reddit):
    """container for pages accessible via /prefs.  No extension handling."""
    
    extension_handling = False

    def __init__(self, show_sidebar = False, *a, **kw):
        Reddit.__init__(self, show_sidebar = show_sidebar,
                        title = "%s (%s)" %(_("preferences"), c.site.name.strip(' ')),
                        *a, **kw)

    def build_toolbars(self):
        buttons = [NavButton(menu.options, ''),
                   NamedButton('friends'),
                   NamedButton('update'),
                   NamedButton('delete')]
        return [PageNameNav('nomenu', title = _("preferences")), 
                NavMenu(buttons, base_path = "/prefs", type="tabmenu")]

class PrefOptions(Templated):
    """Preference form for updating language and display options"""
    def __init__(self, done = False):
        Templated.__init__(self, done = done)

class PrefUpdate(Templated):
    """Preference form for updating email address and passwords"""
    pass

class PrefDelete(Templated):
    """preference form for deleting a user's own account."""
    pass


class MessagePage(Reddit):
    """Defines the content for /message/*"""
    def __init__(self, *a, **kw):
        if not kw.has_key('show_sidebar'):
            kw['show_sidebar'] = False
        Reddit.__init__(self, *a, **kw)
        if is_api():
            self.replybox = None
        else:
            self.replybox = UserText(item = None, creating = True,
                                     post_form = 'comment', display = False,
                                     cloneable = True)
            

    def content(self):
        return self.content_stack((self.replybox,
                                   self.infobar,
                                   self.nav_menu,
                                   self._content))

    def build_toolbars(self):
        buttons =  [NamedButton('compose'),
                    NamedButton('inbox'),
                    NamedButton('sent')]
        return [PageNameNav('nomenu', title = _("message")), 
                NavMenu(buttons, base_path = "/message", type="tabmenu")]

class MessageCompose(Templated):
    """Compose message form."""
    def __init__(self,to='', subject='', message='', success='', 
                 captcha = None):
        Templated.__init__(self, to = to, subject = subject,
                         message = message, success = success, 
                         captcha = captcha)

    
class BoringPage(Reddit):
    """parent class For rendering all sorts of uninteresting,
    sortless, navless form-centric pages.  The top navmenu is
    populated only with the text provided with pagename and the page
    title is 'reddit.com: pagename'"""
    
    extension_handling= False
    
    def __init__(self, pagename, **context):
        self.pagename = pagename
        name = c.site.name or g.default_sr
        Reddit.__init__(self, title = "%s: %s" % (name, pagename),
                        **context)

    def build_toolbars(self):
        return [PageNameNav('nomenu', title = self.pagename)]

class HelpPage(BoringPage):
    def build_toolbars(self):
        return [PageNameNav('help', title = self.pagename)]

class FormPage(BoringPage):
    """intended for rendering forms with no rightbox needed or wanted"""
    def __init__(self, pagename, show_sidebar = False, *a, **kw):
        BoringPage.__init__(self, pagename,  show_sidebar = show_sidebar,
                            *a, **kw)
        

class LoginPage(BoringPage):
    enable_login_cover = False

    """a boring page which provides the Login/register form"""
    def __init__(self, **context):
        context['loginbox'] = False
        self.dest = context.get('dest', '')
        context['show_sidebar'] = False
        BoringPage.__init__(self,  _("login or register"), **context)

    def content(self):
        kw = {}
        for x in ('user_login', 'user_reg'):
            kw[x] = getattr(self, x) if hasattr(self, x) else ''
        return Login(dest = self.dest, **kw)

class Login(Templated):
    """The two-unit login and register form."""
    def __init__(self, user_reg = '', user_login = '', dest=''):
        Templated.__init__(self, user_reg = user_reg, user_login = user_login,
                           dest = dest, captcha = Captcha())
    
class SearchPage(BoringPage):
    """Search results page"""
    searchbox = False

    def __init__(self, pagename, prev_search, elapsed_time, num_results, *a, **kw):
        self.searchbar = SearchBar(prev_search = prev_search,
                                   elapsed_time = elapsed_time,
                                   num_results = num_results)
        BoringPage.__init__(self, pagename, robots='noindex', *a, **kw)

    def content(self):
        return self.content_stack((self.searchbar, self.infobar,
                                   self.nav_menu, self._content))

class CommentsPanel(Templated):
    """the side-panel on the reddit toolbar frame that shows the top
       comments of a link"""

    def __init__(self, link = None, listing = None, expanded = False, *a, **kw):
        self.link = link
        self.listing = listing
        self.expanded = expanded

        Templated.__init__(self, *a, **kw)

class LinkInfoPage(Reddit):
    """Renders the varied /info pages for a link.  The Link object is
    passed via the link argument and the content passed to this class
    will be rendered after a one-element listing consisting of that
    link object.

    In addition, the rendering is reordered so that any nav_menus
    passed to this class will also be rendered underneath the rendered
    Link.
    """
    
    create_reddit_box = False

    def __init__(self, link = None, comment = None,
                 link_title = '', subtitle = None, duplicates = None,
                 *a, **kw):
        wrapper = default_thing_wrapper(expand_children = True)

        # link_listing will be the one-element listing at the top
        self.link_listing = wrap_links(link, wrapper = wrapper)

        # link is a wrapped Link object
        self.link = self.link_listing.things[0]

        link_title = ((self.link.title) if hasattr(self.link, 'title') else '')
        if comment:
            if comment._deleted and not c.user_is_admin:
                author = _("[deleted]")
            else:
                author = Account._byID(comment.author_id, data=True).name

            params = {'author' : author, 'title' : _force_unicode(link_title)}
            title = strings.permalink_title % params
        else:
            params = {'title':_force_unicode(link_title), 'site' : c.site.name}
            title = strings.link_info_title % params

        self.subtitle = subtitle

        # if we're already looking at the 'duplicates' page, we can
        # avoid doing this lookup twice
        if duplicates is None:
            self.duplicates = link_duplicates(self.link)
        else:
            self.duplicates = duplicates

        Reddit.__init__(self, title = title, *a, **kw)

    def build_toolbars(self):
        base_path = "/%s/%s/" % (self.link._id36, title_to_url(self.link.title))
        base_path = _force_utf8(base_path)
        def info_button(name, **fmt_args):
            return NamedButton(name, dest = '/%s%s' % (name, base_path),
                               aliases = ['/%s/%s' % (name, self.link._id36)],
                               fmt_args = fmt_args)

        buttons = [info_button('comments'),
                   info_button('related')]

        if not self.link.is_self and self.duplicates:
            buttons.append(info_button('duplicates', num = len(self.duplicates)))
        if c.user_is_admin:
            buttons += [info_button('details')]
        if c.user_is_sponsor:
            if self.link.promoted is not None:
                buttons += [info_button('traffic')]
        if len(self.link.title) < 200 and g.spreadshirt_url:
            buttons += [info_button('shirt')]
            

        toolbar = [NavMenu(buttons, base_path = "", type="tabmenu")]

        if c.site != Default and not c.cname:
            toolbar.insert(0, PageNameNav('subreddit'))

        return toolbar
    
    def content(self):
        return self.content_stack((self.infobar, self.link_listing,
                                   PaneStack([PaneStack((self.nav_menu,
                                                         self._content))],
                                             title = self.subtitle,
                                             css_class = "commentarea")))

    def rightbox(self):
        rb = Reddit.rightbox(self)
        if not (self.link.promoted and not c.user_is_sponsor):
            rb.insert(1, LinkInfoBar(a = self.link))
        return rb

class LinkInfoBar(Templated):
    """Right box for providing info about a link."""
    def __init__(self, a = None):
        if a:
            a = Wrapped(a)
        Templated.__init__(self, a = a, datefmt = datefmt)

class EditReddit(Reddit):
    """Container for the about page for a reddit"""
    extension_handling= False

    def __init__(self, *a, **kw):
        is_moderator = c.user_is_loggedin and \
            c.site.is_moderator(c.user) or c.user_is_admin

        title = _('manage your reddit') if is_moderator else \
                _('about %(site)s') % dict(site=c.site.name)

        Reddit.__init__(self, title = title, *a, **kw)
    
    def build_toolbars(self):
        if not c.cname:
            return [PageNameNav('subreddit')]
        else:
            return []

class SubredditsPage(Reddit):
    """container for rendering a list of reddits.  The corner
    searchbox is hidden and its functionality subsumed by an in page
    SearchBar for searching over reddits.  As a result this class
    takes the same arguments as SearchBar, which it uses to construct
    self.searchbar"""
    searchbox    = False
    submit_box   = False
    def __init__(self, prev_search = '', num_results = 0, elapsed_time = 0,
                 title = '', loginbox = True, infotext = None, *a, **kw):
        Reddit.__init__(self, title = title, loginbox = loginbox, infotext = infotext,
                        *a, **kw)
        self.searchbar = SearchBar(prev_search = prev_search,
                                   elapsed_time = elapsed_time,
                                   num_results = num_results,
                                   header = _('search reddits')
                                   )
        self.sr_infobar = InfoBar(message = strings.sr_subscribe)

    def build_toolbars(self):
        buttons =  [NavButton(menu.popular, ""),
                    NamedButton("new")]
        if c.user_is_admin:
            buttons.append(NamedButton("banned"))

        #removing the 'my reddits' listing for now
        #if c.user_is_loggedin:
        #    #add the aliases to "my reddits" stays highlighted
        #    buttons.append(NamedButton("mine", aliases=['/reddits/mine/subscriber',
        #                                                '/reddits/mine/contributor',
        #                                                '/reddits/mine/moderator']))
               

        return [PageNameNav('reddits'),
                NavMenu(buttons, base_path = '/reddits', type="tabmenu")]

    def content(self):
        return self.content_stack((self.searchbar, self.nav_menu,
                                   self.sr_infobar, self._content))

    def rightbox(self):
        ps = Reddit.rightbox(self)
        ps.append(SubscriptionBox())
        return ps

class MySubredditsPage(SubredditsPage):
    """Same functionality as SubredditsPage, without the search box."""
    
    def content(self):
        return self.content_stack((self.nav_menu, self.infobar, self._content))


def votes_visible(user):
    """Determines whether to show/hide a user's votes.  They are visible:
     * if the current user is the user in question
     * if the user has a preference showing votes
     * if the current user is an administrator
    """
    return ((c.user_is_loggedin and c.user.name == user.name) or
            user.pref_public_votes or
            c.user_is_admin)

class ProfilePage(Reddit):
    """Container for a user's profile page.  As such, the Account
    object of the user must be passed in as the first argument, along
    with the current sub-page (to determine the title to be rendered
    on the page)"""
    
    searchbox         = False
    create_reddit_box = False
    submit_box        = False

    def __init__(self, user, *a, **kw):
        self.user     = user
        Reddit.__init__(self, *a, **kw)

    def build_toolbars(self):
        path = "/user/%s/" % self.user.name
        main_buttons = [NavButton(menu.overview, '/', aliases = ['/overview']),
                   NavButton(plurals.comments, 'comments'),
                   NamedButton('submitted')]
        
        if votes_visible(self.user):
            main_buttons += [NamedButton('liked'),
                        NamedButton('disliked'),
                        NamedButton('hidden')]

            
        toolbar = [PageNameNav('nomenu', title = self.user.name),
                   NavMenu(main_buttons, base_path = path, type="tabmenu")]

        if c.user_is_admin:
            from admin_pages import AdminProfileMenu
            toolbar.append(AdminProfileMenu(path))
        return toolbar
    

    def rightbox(self):
        rb = Reddit.rightbox(self)
        rb.push(ProfileBar(self.user))
        if c.user_is_admin:
            from admin_pages import AdminSidebar
            rb.append(AdminSidebar(self.user))
        return rb

class ProfileBar(Templated): 
    """Draws a right box for info about the user (karma, etc)"""
    def __init__(self, user):
        Templated.__init__(self, user = user)
        self.isFriend = self.user._id in c.user.friends \
            if c.user_is_loggedin else False
        self.isMe = (self.user == c.user)

class MenuArea(Templated):
    """Draws the gray box at the top of a page for sort menus"""
    def __init__(self, menus = []):
        Templated.__init__(self, menus = menus)

class InfoBar(Templated):
    """Draws the yellow box at the top of a page for info"""
    def __init__(self, message = ''):
        Templated.__init__(self, message = message)


class RedditError(BoringPage):
    site_tracking = False
    def __init__(self, title, message = None):
        if not message:
            message = title
        BoringPage.__init__(self, title, loginbox=False,
                            show_sidebar = False, 
                            content=ErrorPage(message))

class Reddit404(BoringPage):
    site_tracking = False
    def __init__(self):
        ch=random.choice(['a','b','c','d','e'])
        BoringPage.__init__(self, _("page not found"), loginbox=False,
                            show_sidebar = False, 
                            content=UnfoundPage(ch))
        
class UnfoundPage(Templated):
    """Wrapper for the 404 page"""
    def __init__(self, choice):
        Templated.__init__(self, choice = choice)
    
class ErrorPage(Templated):
    """Wrapper for an error message"""
    def __init__(self, message = _("you aren't allowed to do that.")):
        Templated.__init__(self, message = message)
    
class Profiling(Templated):
    """Debugging template for code profiling using built in python
    library (only used in middleware)"""
    def __init__(self, header = '', table = [], caller = [], callee = [], path = ''):
        Templated.__init__(self, header = header, table = table, caller = caller,
                         callee = callee, path = path)

class Over18(Templated):
    """The creepy 'over 18' check page for nsfw content."""
    pass

class SubredditTopBar(Templated):
    """The horizontal strip at the top of most pages for navigating
    user-created reddits."""
    def __init__(self):
        Templated.__init__(self)

        self.my_reddits = Subreddit.user_subreddits(c.user, ids = False)

        self.pop_reddits = Subreddit.default_subreddits(ids = False,
                                                   limit = Subreddit.sr_limit)

# This doesn't actually work.
#        self.reddits = c.recent_reddits
#        for sr in pop_reddits:
#            if sr not in c.recent_reddits:
#                self.reddits.append(sr)

    def my_reddits_dropdown(self):
        drop_down_buttons = []    
        for sr in sorted(self.my_reddits, key = lambda sr: sr.name.lower()):
            drop_down_buttons.append(SubredditButton(sr))
        drop_down_buttons.append(NamedButton('edit', sr_path = False,
                                             css_class = 'bottom-option',
                                             dest = '/reddits/'))
        return SubredditMenu(drop_down_buttons,
                             title = _('my reddits'),
                             type = 'srdrop')
        
    def subscribed_reddits(self):
        return NavMenu([SubredditButton(sr) for sr in
                        sorted(self.my_reddits,
                               key = lambda sr: sr._downs,
                               reverse=True)
                        ],
                       type='flatlist', separator = '-',
                       _id = 'sr-bar')

    def popular_reddits(self, exclude=[]):
        exclusions = set(exclude)
        buttons = [SubredditButton(sr)
                   for sr in self.pop_reddits if sr not in exclusions]
    
        return NavMenu(buttons,
                       type='flatlist', separator = '-',
                       _id = 'sr-bar')

    def sr_bar (self):
        menus = []

        if not c.user_is_loggedin:
            menus.append(self.popular_reddits())
        else:
            if len(self.my_reddits) > g.sr_dropdown_threshold:
                menus.append(self.my_reddits_dropdown())

            menus.append(self.subscribed_reddits())

            sep = '<span class="separator">&nbsp;&ndash;&nbsp;</span>'
            menus.append(RawString(sep))

            menus.append(self.popular_reddits(exclude=self.my_reddits))

        return menus

class SubscriptionBox(Templated):
    """The list of reddits a user is currently subscribed to to go in
    the right pane."""
    def __init__(self):
        srs = Subreddit.user_subreddits(c.user, ids = False)
        srs.sort(key = lambda sr: sr.name.lower())
        self.reddits = wrap_links(srs)
        Templated.__init__(self)

class CreateSubreddit(Templated):
    """reddit creation form."""
    def __init__(self, site = None, name = ''):
        Templated.__init__(self, site = site, name = name)

class SubredditStylesheet(Templated):
    """form for editing or creating subreddit stylesheets"""
    def __init__(self, site = None,
                 stylesheet_contents = ''):
        Templated.__init__(self, site = site,
                         stylesheet_contents = stylesheet_contents)

class CssError(Templated):
    """Rendered error returned to the stylesheet editing page via ajax"""
    def __init__(self, error):
        # error is an instance of cssutils.py:ValidationError
        Templated.__init__(self, error = error)

class UploadedImage(Templated):
    "The page rendered in the iframe during an upload of a header image"
    def __init__(self,status,img_src, name="", errors = {}):
        self.errors = list(errors.iteritems())
        Templated.__init__(self, status=status, img_src=img_src, name = name)

class Password(Templated):
    """Form encountered when 'recover password' is clicked in the LoginFormWide."""
    def __init__(self, success=False):
        Templated.__init__(self, success = success)

class PasswordReset(Templated):
    """Template for generating an email to the user who wishes to
    reset their password (step 2 of password recovery, after they have
    entered their user name in Password.)"""
    pass

class ResetPassword(Templated):
    """Form for actually resetting a lost password, after the user has
    clicked on the link provided to them in the Password_Reset email
    (step 3 of password recovery.)"""
    pass


class Captcha(Templated):
    """Container for rendering robot detection device."""
    def __init__(self, error=None):
        self.error = _('try entering those letters again') if error else ""
        self.iden = get_captcha()
        Templated.__init__(self)

class PermalinkMessage(Templated):
    """renders the box on comment pages that state 'you are viewing a
    single comment's thread'"""
    def __init__(self, comments_url):
        Templated.__init__(self, comments_url = comments_url)

class PaneStack(Templated):
    """Utility class for storing and rendering a list of block elements."""
    
    def __init__(self, panes=[], div_id = None, css_class=None, div=False,
                 title=""):
        div = div or div_id or css_class or False
        self.div_id    = div_id
        self.css_class = css_class
        self.div       = div
        self.stack     = list(panes)
        self.title = title
        Templated.__init__(self)

    def append(self, item):
        """Appends an element to the end of the current stack"""
        self.stack.append(item)
    
    def push(self, item):
        """Prepends an element to the top of the current stack"""
        self.stack.insert(0, item)

    def insert(self, *a):
        """inerface to list.insert on the current stack"""
        return self.stack.insert(*a)


class SearchForm(Templated):
    """The simple search form in the header of the page.  prev_search
    is the previous search."""
    def __init__(self, prev_search = ''):
        Templated.__init__(self, prev_search = prev_search)


class SearchBar(Templated):
    """More detailed search box for /search and /reddits pages.
    Displays the previous search as well as info of the elapsed_time
    and num_results if any."""
    def __init__(self, num_results = 0, prev_search = '', elapsed_time = 0, **kw):

        # not listed explicitly in args to ensure it translates properly
        self.header = kw.get('header', _("previous search"))

        self.prev_search  = prev_search
        self.elapsed_time = elapsed_time

        # All results are approximate unless there are fewer than 10.
        if num_results > 10:
            self.num_results = (num_results / 10) * 10
        else:
            self.num_results = num_results

        Templated.__init__(self)


class Frame(Templated):
    """Frameset for the FrameToolbar used when a user hits /tb/. The
    top 30px of the page are dedicated to the toolbar, while the rest
    of the page will show the results of following the link."""
    def __init__(self, url='', title='', fullname=None):
        if title:
            title = (_('%(site_title)s via %(domain)s')
                     % dict(site_title = _force_unicode(title),
                            domain     = g.domain))
        else:
            title = g.domain
        Templated.__init__(self, url = url, title = title, fullname = fullname)

dorks_re = re.compile(r"https?://?([-\w.]*\.)?digg\.com/\w+\.\w+(/|$)")
class FrameToolbar(Wrapped):
    """The reddit voting toolbar used together with Frame."""

    cachable = True
    extension_handling = False
    cache_ignore = Link.cache_ignore
    def __init__(self, link, title = None, url = None, expanded = False, **kw):
        if link:
            self.title = link.title
            self.url = link.url
        else:
            self.title = title
            self.url = url

        self.expanded = expanded
        self.user_is_loggedin = c.user_is_loggedin
        self.have_messages = c.have_messages
        self.user_name = c.user.name if self.user_is_loggedin else ""
        self.cname = c.cname
        self.site_name = c.site.name
        self.site_description = c.site.description
        self.default_sr = c.default_sr

        self.dorks = bool( dorks_re.match(self.url) )
        Wrapped.__init__(self, link)
        if link is None:
            self.add_props(c.user, [self])
    
    @classmethod
    def add_props(cls, user, wrapped):
        # unlike most wrappers we can guarantee that there is a link
        # that this wrapper is wrapping.
        nonempty = [w for w in wrapped if hasattr(w, "_fullname")]
        Link.add_props(user, nonempty)
        for w in wrapped:
            w.score_fmt = Score.points
            if not hasattr(w, '_fullname'):
                w._fullname = None
                w.tblink = add_sr("/s/"+quote(w.url))
                submit_url_options = dict(url  = _force_unicode(w.url),
                                          then = 'tb')
                if w.title:
                    submit_url_options['title'] = _force_unicode(w.title)
                w.submit_url = add_sr('/submit' +
                                         query_string(submit_url_options))
            else:
                w.tblink = add_sr("/tb/"+w._id36)
    
                w.upstyle = "mod" if w.likes else ""
                w.downstyle = "mod" if w.likes is False else ""
            if not c.user_is_loggedin:
                w.loginurl = add_sr("/login?dest="+quote(w.tblink))
        # run to set scores with current score format (for example)
        Printable.add_props(user, nonempty)



class NewLink(Templated):
    """Render the link submission form"""
    def __init__(self, captcha = None, url = '', title= '', subreddits = (),
                 then = 'comments'):
        tabs = (('link', ('link-desc', 'url-field')),
                ('text', ('text-desc', 'text-field')))
        all_fields = set(chain(*(parts for (tab, parts) in tabs)))
    
        buttons = []
        self.default_tabs = tabs[0][1]
        self.default_tab = tabs[0][0]
        for tab_name, parts in tabs:
            to_show = ','.join('#' + p for p in parts)
            to_hide = ','.join('#' + p for p in all_fields if p not in parts)
            onclick = "return select_form_tab(this, '%s', '%s');"
            onclick = onclick % (to_show, to_hide)
            
            if tab_name == self.default_tab:
                self.default_show = to_show
                self.default_hide = to_hide

            buttons.append(JsButton(tab_name, onclick=onclick, css_class=tab_name))

        self.formtabs_menu = JsNavMenu(buttons, type = 'formtab')
        self.default_tabs = tabs[0][1]

        self.sr_searches = simplejson.dumps(popular_searches())

        if isinstance(c.site, FakeSubreddit):
            self.default_sr = subreddits[0] if subreddits else g.default_sr
        else:
            self.default_sr = c.site.name

        Templated.__init__(self, captcha = captcha, url = url,
                         title = title, subreddits = subreddits,
                         then = then)

class ShareLink(CachedTemplate):
    def __init__(self, link_name = "", emails = None):
        self.captcha = c.user.needs_captcha()
        self.email = getattr(c.user, 'email', "")
        self.username = c.user.name
        Templated.__init__(self, link_name = link_name,
                           emails = c.user.recent_share_emails())

        

class Share(Templated):
    pass

class Mail_Opt(Templated):
    pass

class OptOut(Templated):
    pass

class OptIn(Templated):
    pass


class UserStats(Templated):
    """For drawing the stats page, which is fetched from the cache."""
    def __init__(self):
        Templated.__init__(self)
        cache_stats = cache.get('stats')
        if cache_stats:
            top_users, top_day, top_week = cache_stats

            #lookup user objs
            uids = []
            uids.extend(u    for u in top_users)
            uids.extend(u[0] for u in top_day)
            uids.extend(u[0] for u in top_week)
            users = Account._byID(uids, data = True)

            self.top_users = (users[u]            for u in top_users)
            self.top_day   = ((users[u[0]], u[1]) for u in top_day)
            self.top_week  = ((users[u[0]], u[1]) for u in top_week)
        else:
            self.top_users = self.top_day = self.top_week = ()


class ButtonEmbed(Templated):
    """Generates the JS wrapper around the buttons for embedding."""
    def __init__(self, button = None, width = 100,
                 height=100, referer = "", url = "", **kw):
        Templated.__init__(self, button = button,
                           width = width, height = height,
                           referer=referer, url = url, **kw)
        
class Button(Wrapped):
    cachable = True
    extension_handling = False
    def __init__(self, link, **kw):
        Wrapped.__init__(self, link, **kw)
        if link is None:
            self.add_props(c.user, [self])
            
    
    @classmethod
    def add_props(cls, user, wrapped):
        # unlike most wrappers we can guarantee that there is a link
        # that this wrapper is wrapping.
        Link.add_props(user, [w for w in wrapped if hasattr(w, "_fullname")])
        for w in wrapped:
            if not hasattr(w, '_fullname'):
                w._fullname = None

class ButtonLite(Button):
    pass
            

class ButtonNoBody(Button):
    """A button page that just returns the raw button for direct embeding"""
    pass

class ButtonDemoPanel(Templated):
    """The page for showing the different styles of embedable voting buttons"""
    pass


class Feedback(Templated):
    """The feedback and ad inquery form(s)"""
    def __init__(self, title, action):
        email = name = ''
        if c.user_is_loggedin:
            email = getattr(c.user, "email", "")
            name = c.user.name

        captcha = None
        if not c.user_is_loggedin or c.user.needs_captcha():
            captcha = Captcha()

        Templated.__init__(self,
                         captcha = captcha,
                         title = title,
                         action = action,
                         email = email,
                         name = name)


class WidgetDemoPanel(Templated):
    """Demo page for the .embed widget."""
    pass

class Bookmarklets(Templated):
    """The bookmarklets page."""
    def __init__(self, buttons=None):
        if buttons is None:
            buttons = ["submit", "serendipity!"]
            # only include the toolbar link if we're not on an
            # unathorised cname. See toolbar.py:GET_s for discussion
            if not (c.cname and c.site.domain not in g.authorized_cnames):
                buttons.insert(0, "reddit toolbar")
        Templated.__init__(self, buttons = buttons)



class AdminTranslations(Templated):
    """The translator control interface, used for determining which
    user is allowed to edit which translation file and for providing a
    summary of what translation files are done and/or in use."""
    def __init__(self):
        from r2.lib.translation import list_translations
        Templated.__init__(self)
        self.translations = list_translations()
        

class Embed(Templated):
    """wrapper for embedding /help into reddit as if it were not on a separate wiki."""
    def __init__(self,content = ''):
        Templated.__init__(self, content = content)


class Page_down(Templated):
    def __init__(self, **kw):
        message = kw.get('message', _("This feature is currently unavailable. Sorry"))
        Templated.__init__(self, message = message)

# Classes for dealing with friend/moderator/contributor/banned lists


class UserTableItem(Templated):
    """A single row in a UserList of type 'type' and of name
    'container_name' for a given user.  The provided list of 'cells'
    will determine what order the different columns are rendered in.
    Currently, this list can consist of 'user', 'sendmessage' and
    'remove'."""
    def __init__(self, user, type, cellnames, container_name, editable):
        self.user, self.type, self.cells = user, type, cellnames
        self.container_name = container_name
        self.editable       = editable
        Templated.__init__(self)

    def __repr__(self):
        return '<UserTableItem "%s">' % self.user.name

class UserList(Templated):
    """base class for generating a list of users"""    
    form_title     = ''
    table_title    = ''
    type           = ''
    container_name = ''
    cells          = ('user', 'sendmessage', 'remove')
    _class         = ""

    def __init__(self, editable = True):
        self.editable = editable
        Templated.__init__(self)

    def user_row(self, user):
        """Convenience method for constructing a UserTableItem
        instance of the user with type, container_name, etc. of this
        UserList instance"""
        return UserTableItem(user, self.type, self.cells, self.container_name,
                             self.editable)

    @property
    def users(self, site = None):
        """Generates a UserTableItem wrapped list of the Account
        objects which should be present in this UserList."""
        uids = self.user_ids()
        if uids:
            users = Account._byID(uids, True, return_dict = False) 
            return [self.user_row(u) for u in users]
        else:
            return []

    def user_ids(self):
        """virtual method for fetching the list of ids of the Accounts
        to be listing in this UserList instance"""
        raise NotImplementedError

    @property
    def container_name(self):
        return c.site._fullname

class FriendList(UserList):
    """Friend list on /pref/friends"""
    type = 'friend'

    @property
    def form_title(self):
        return _('add a friend')

    @property
    def table_title(self):
        return _('your friends')

    def user_ids(self):
        return c.user.friends

    @property
    def container_name(self):
        return c.user._fullname

class ContributorList(UserList):
    """Contributor list on a restricted/private reddit."""
    type = 'contributor'

    @property
    def form_title(self):
        return _('add contributor')

    @property
    def table_title(self):
        return _("contributors to %(reddit)s") % dict(reddit = c.site.name)

    def user_ids(self):
        return c.site.contributors

class ModList(UserList):
    """Moderator list for a reddit."""
    type = 'moderator'

    @property
    def form_title(self):
        return _('add moderator')

    @property
    def table_title(self):
        return _("moderators to %(reddit)s") % dict(reddit = c.site.name)

    def user_ids(self):
        return c.site.moderators

class BannedList(UserList):
    """List of users banned from a given reddit"""
    type = 'banned'

    @property
    def form_title(self):
        return _('ban users')

    @property
    def table_title(self):
        return  _('banned users')

    def user_ids(self):
        return c.site.banned


class DetailsPage(LinkInfoPage):
    extension_handling= False

    def content(self):
        # TODO: a better way?
        from admin_pages import Details
        return self.content_stack((self.link_listing, Details(link = self.link)))

class Cnameframe(Templated):
    """The frame page."""
    def __init__(self, original_path, subreddit, sub_domain):
        Templated.__init__(self, original_path=original_path)
        if sub_domain and subreddit and original_path:
            self.title = "%s - %s" % (subreddit.title, sub_domain)
            u = UrlParser(subreddit.path + original_path)
            u.hostname = get_domain(cname = False, subreddit = False)
            u.update_query(**request.get.copy())
            u.put_in_frame()
            self.frame_target = u.unparse()
        else:
            self.title = ""
            self.frame_target = None

class FrameBuster(Templated):
    pass

class PromotePage(Reddit):
    create_reddit_box  = False
    submit_box         = False
    extension_handling = False

    def __init__(self, title, nav_menus = None, *a, **kw):
        buttons = [NamedButton('current_promos', dest = ''),
                   NamedButton('new_promo')]

        menu  = NavMenu(buttons, base_path = '/promote', type='flatlist')

        if nav_menus:
            nav_menus.insert(0, menu)
        else:
            nav_menus = [menu]

        Reddit.__init__(self, title, nav_menus = nav_menus, *a, **kw)


class PromotedLinks(Templated):
    def __init__(self, current_list, *a, **kw):
        self.things = current_list
        
        self.recent =  dict(load_summary("thing"))

        if self.recent:
            link_listing = wrap_links(self.recent.keys())
            for t in link_listing:
                self.recent[t._fullname].insert(0, t)

            self.recent = self.recent.values()
            self.recent.sort(key = lambda x: x[0]._date)
        Templated.__init__(self, datefmt = datefmt, *a, **kw)

class PromoteLinkForm(Templated):
    def __init__(self, sr = None, link = None, listing = '',
                 timedeltatext = '', *a, **kw):
        Templated.__init__(self, sr = sr, link = link,
                         datefmt = datefmt,
                         timedeltatext = timedeltatext,
                         listing = listing,
                         *a, **kw)

class TabbedPane(Templated):
    def __init__(self, tabs):
        """Renders as tabbed area where you can choose which tab to
        render. Tabs is a list of tuples (tab_name, tab_pane)."""
        buttons = []
        for tab_name, title, pane in tabs:
            buttons.append(JsButton(title, onclick="return select_tab_menu(this, '%s');" % tab_name))

        self.tabmenu = JsNavMenu(buttons, type = 'tabpane')
        self.tabs = tabs

        Templated.__init__(self)

class LinkChild(object):
    def __init__(self, link, load = False, expand = False, nofollow = False):
        self.link = link
        self.expand = expand
        self.load = load or expand
        self.nofollow = nofollow
    
    def content(self):
        return ''

class MediaChild(LinkChild):
    """renders when the user hits the expando button to expand media
       objects, like embedded videos"""
    css_style = "video"

    def content(self):
        if isinstance(self.link.media_object, basestring):
            return self.link.media_object

        scraper = scrapers[self.link.media_object['type']]
        media_embed = scraper.media_embed(**self.link.media_object)
        return MediaEmbed(media_domain = g.media_domain,
                          height = media_embed.height+10,
                          width = media_embed.width+10,
                          scrolling = media_embed.scrolling,
                          id36 = self.link._id36).render()

class MediaEmbed(Templated):
    """The actual rendered iframe for a media child"""
    pass

class SelfTextChild(LinkChild):
    css_style = "selftext"
    def content(self):
        u = UserText(self.link, self.link.selftext,
                     editable = c.user == self.link.author,
                     nofollow = self.nofollow)
        return u.render()

class UserText(CachedTemplate):
    def __init__(self,
                 item,
                 text = '',
                 have_form = True,
                 editable = False,
                 creating = False,
                 nofollow = False,
                 target = None,
                 display = True,
                 post_form = 'editusertext',
                 cloneable = False,
                 extra_css = ''):

        css_class = "usertext"
        if cloneable:
            css_class += " cloneable"
        if extra_css:
            css_class += " " + extra_css

        CachedTemplate.__init__(self,
                                fullname = item._fullname if item else "", 
                                text = text,
                                have_form = have_form,
                                editable = editable,
                                creating = creating,
                                nofollow = nofollow,
                                target = target,
                                display = display,
                                post_form = post_form,
                                cloneable = cloneable,
                                css_class = css_class)

class MediaEmbedBody(CachedTemplate):
    """What's rendered inside the iframe that contains media objects"""
    pass

class Traffic(Templated):
    @staticmethod
    def slice_traffic(traffic, *indices):
        return [[a] + [b[i] for i in indices] for a, b in traffic]


class PromotedTraffic(Traffic):
    """
    Traffic page for a promoted link, including 2 graphs (one for
    impressions and one for clicks with uniques on each plotted in
    multiy format) and a table of the data.
    """
    def __init__(self, thing):
        self.thing = thing
        d = thing._date.astimezone(g.tz) 
        d = d.replace(minute = 0, second = 0, microsecond = 0)
        
        until = thing.promote_until
        now = datetime.datetime.now(g.tz)
        if not until:
            until = d + datetime.timedelta(1)
        if until > now:
            until - now
            
        self.traffic = load_traffic('hour', "thing", thing._fullname,
                                    start_time = d, stop_time = until)

        self.totals =  load_traffic('month', "thing", thing._fullname)
        if not self.totals:
            self.totals = load_traffic('day', "thing", thing._fullname)
        if self.totals:
            self.totals = map(sum, zip(*zip(*self.totals)[1]))
               
        imp = self.slice_traffic(self.traffic, 0, 1)

        if len(imp) > 2:
            imp_total = locale.format('%d', sum(x[2] for x in imp), True)
            chart = graph.LineGraph(imp)
            self.imp_graph = chart.google_chart(ylabels = ['uniques', 'total'],
                                                title = ("impressions (%s)" %
                                                         imp_total))
            
            cli = self.slice_traffic(self.traffic, 2, 3)
            cli_total = locale.format('%d', sum(x[2] for x in cli), True)
            chart = graph.LineGraph(cli)
            self.cli_graph = chart.google_chart(ylabels = ['uniques', 'total'],
                                                title = ("clicks (%s)" %
                                                         cli_total))
        else:
            self.imp_graph = self.cli_graph = None
        Templated.__init__(self)

class RedditTraffic(Traffic):
    """
    fetches hourly and daily traffic for the current reddit.  If the
    current reddit is a default subreddit, fetches the site-wide
    uniques and includes monthly totals.  In this latter case, getter
    methods are available for computing breakdown of site trafffic by
    reddit.
    """
    def __init__(self):
        self.has_data = False
        ivals = ["hour", "day"]
        if c.default_sr:
            ivals.append("month")

        for ival in ivals:
            if c.default_sr:
                data = load_traffic(ival, "total", "")
            else:
                data = load_traffic(ival, "reddit", c.site.name)
            if not data:
                break
            slices = [("uniques",     (0, 2) if c.site.domain else (0,),
                       "FF4500"),
                      ("impressions", (1, 3) if c.site.domain else (1,),
                       "336699")]
            if not c.default_sr and ival == 'day':
                slices.append(("subscriptions", (4,), "00FF00"))
            setattr(self, ival + "_data", data)
            for name, indx, color in slices:
                data2 = self.slice_traffic(data, *indx)
                chart = graph.LineGraph(data2, colors = [color, "B0B0B0"])
                setattr(self, name + "_" + ival + "_chart", chart)
                title = "%s by %s" % (name, ival)
                res = chart.google_chart(ylabels = [name],
                                         multiy = False, 
                                         title = title)
                setattr(self, name + "_" + ival, res)
        else:
            self.has_data = True
        if self.has_data:
            imp_by_day = [[] for i in range(7)]
            uni_by_day = [[] for i in range(7)]
            dates  = self.uniques_day_chart.xdata
            uniques = self.uniques_day_chart.ydata[0]
            imps    = self.impressions_day_chart.ydata[0]
            self.uniques_mean     = sum(map(float, uniques))/len(uniques)
            self.impressions_mean = sum(map(float, imps))/len(imps)
            for i, d in enumerate(dates):
                imp_by_day[d.weekday()].append(float(imps[i]))
                uni_by_day[d.weekday()].append(float(uniques[i]))
            self.uniques_by_dow     = [sum(x)/max(len(x),1)
                                       for x in uni_by_day]
            self.impressions_by_dow = [sum(x)/max(len(x),1)
                                       for x in imp_by_day]
        Templated.__init__(self)

    def reddits_summary(self):
        if c.default_sr:
            data = map(list, load_summary("reddit"))
            data.sort(key = lambda x: x[1][1], reverse = True)
            for d in data:
                name = d[0]
                for sr in (Default, Friends, All, Sub):
                    if name == sr.name:
                        name = sr
                        break
                else:
                    try:
                        name = Subreddit._by_name(name)
                    except NotFound:
                        name = DomainSR(name)
                d[0] = name
            return data
        return res
        
    def monthly_summary(self):
        """
        Convenience method b/c it is bad form to do this much math
        inside of a template.b
        """
        res = []
        if c.default_sr:
            data = self.month_data
            for x, (date, d) in enumerate(data):
                res.append([("date", date.strftime("%Y-%m")),
                            ("", locale.format("%d", d[0], True)),
                            ("", locale.format("%d", d[1], True))])
                last_d = data[x-1][1] if x else None
                for i in range(2):
                    if x == 0:
                        res[-1].append(("",""))
                    elif x == len(data) - 1:
                        # project based on traffic so far
                        # totals are going to be up to yesterday
                        month_len = calendar.monthrange(date.year,
                                                        date.month)[1]
                        yday = (datetime.datetime.utcnow()
                                -datetime.timedelta(1)).day
                        scaled = float(d[i] * month_len) / yday
                        res[-1].append(("gray",
                                        locale.format("%d", scaled, True)))
                    elif last_d and d[i] and last_d[i]:
                        f = 100 * (float(d[i])/last_d[i] - 1)
                        
                        res[-1].append(("up" if f > 0 else "down", 
                                        "%5.2f%%" % f))
        return res

class InnerToolbarFrame(Templated):
    def __init__(self, link, expanded = False):
        Templated.__init__(self, link = link, expanded = expanded)

class RawString(Templated):
   def __init__(self, s):
       self.s = s

   def render(self, *a, **kw):
       return unsafe(self.s)
