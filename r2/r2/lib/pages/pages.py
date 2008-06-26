# "The contents of this file are subject to the Common Public Attribution
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
# All portions of the code written by CondeNet are Copyright (c) 2006-2008
# CondeNet, Inc. All Rights Reserved.
################################################################################
from r2.lib.wrapped import Wrapped
from r2.models import IDBuilder, LinkListing, Account, Default, FakeSubreddit, Subreddit
from r2.config import cache
from r2.lib.jsonresponse import json_respond
from r2.lib.jsontemplates import is_api
from pylons.i18n import _
from pylons import c, request, g

from r2.lib.captcha import get_iden
from r2.lib.filters import spaceCompress
from r2.lib.menus import NavButton, NamedButton, NavMenu, PageNameNav, JsButton, menu
from r2.lib.strings import plurals, rand_strings, strings

def get_captcha():
    if not c.user_is_loggedin or c.user.needs_captcha():
        return get_iden()

class Reddit(Wrapped):
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
    searchbox          = True
    extension_handling = True

    def __init__(self, space_compress = True, nav_menus = None, loginbox = True,
                 infotext = '', content = None, title = '', show_sidebar = True,
                 **context):
        Wrapped.__init__(self, **context)
        self.title          = title
        self.infotext       = infotext
        self.loginbox       = True
        self.show_sidebar   = show_sidebar
        self.space_compress = space_compress

        #put the sort menus at the top
        self.nav_menu = MenuArea(menus = nav_menus) if nav_menus else None

        #add the infobar
        self.infobar = None
        if c.firsttime and c.site.firsttext and not infotext:
            infotext = c.site.firsttext
        if infotext:
            self.infobar = InfoBar(message = infotext)

        #c.subredditbox is set by VSRMask
        self.subreddit_sidebox = False
        if c.subreddit_sidebox:
            self.subreddit_sidebox = True
            self.subreddit_checkboxes = c.site == Default

        self._content = content
        self.toolbars = self.build_toolbars()

    def rightbox(self):
        """generates content in <div class="rightbox">"""
        
        ps = PaneStack(css_class='spacer')

        if not c.user_is_loggedin and self.loginbox:
            ps.append(LoginFormWide())

        if not isinstance(c.site, FakeSubreddit):
            ps.append(SubredditInfoBar())

        if self.subreddit_sidebox:
            ps.append(SubredditBox(self.subreddit_checkboxes))

        if self.submit_box:
            ps.append(SideBox(_('Submit a link'),
                              c.site.path + 'submit', 'submit',
                              subtitles = [_('to anything interesting: news article, blog entry, video, picture...')],
                              show_cover = True))
            
        if self.create_reddit_box:
            ps.append(SideBox(_('Create your own reddit'),
                              '/reddits/create', 'create',
                              subtitles = rand_strings.get("create_reddit", 2),
                              show_cover = True))
        return ps

    def render(self, *a, **kw):
        """Overrides default Wrapped.render with two additions
           * support for rendering API requests with proper wrapping
           * support for space compression of the result
        In adition, unlike Wrapped.render, the result is in the form of a pylons
        Response object with it's content set.
        """
        res = Wrapped.render(self, *a, **kw)
        if is_api():
            res = json_respond(res)
        elif self.space_compress:
            res = spaceCompress(res)
        c.response.content = res
        return c.response
    
    def corner_buttons(self):
        """set up for buttons in upper right corner of main page."""
        buttons = []
        if c.user_is_loggedin:
            if c.user.name in g.admins:
                if c.user_is_admin:
                   buttons += [NamedButton("adminoff", False)]
                else:
                   buttons += [NamedButton("adminon",  False)]
            buttons += [NamedButton("prefs", False,
                                  css_class = "pref-lang")]
        else:
            lang = c.lang.split('-')[0] if c.lang else ''
            buttons += [JsButton(g.lang_name.get(lang, lang),  
                                  onclick = "return showlang();",
                                  css_class = "pref-lang")]
        buttons += [NamedButton("stats", False)]
        buttons += [NamedButton("help", False),
                    NamedButton("blog", False)]                    
        
        if c.user_is_loggedin:
            buttons += [NamedButton("logout", False)]
        
        return NavMenu(buttons, base_path = "/", type = "flatlist")

    def footer_nav(self):
        """navigation buttons in the footer."""
        buttons = [NamedButton("feedback",     False),
                   NamedButton("bookmarklets", False),
                   NamedButton("buttons",      False),
                   NamedButton("widget",       False),
                   NamedButton("store",        False),
                   NamedButton("ad_inq",       False),
                   ]

        return NavMenu(buttons, base_path = "/", type = "flatlist")

    def build_toolbars(self):
        """Sets the layout of the navigation topbar on a Reddit.  The result
        is a list of menus which will be rendered in order and
        displayed at the top of the Reddit."""
        main_buttons = [NamedButton('hot', dest='', aliases=['/hot']),
                        NamedButton('new'), 
                        NamedButton('controversial'),
                        NamedButton('top'),
                        ]

        more_buttons = []

        if c.user_is_loggedin:
            more_buttons.append(NamedButton('saved', False))
            more_buttons.append(NamedButton('recommended', False))

        if c.user_is_loggedin and c.user_is_admin:
            more_buttons.append(NamedButton('admin'))
        elif c.user_is_loggedin and c.site.is_moderator(c.user):
            more_buttons.append(NavButton(menu.admin, 'about/edit'))

        toolbar = [NavMenu(main_buttons, type='tabmenu')]
        if more_buttons:
            toolbar.append(NavMenu(more_buttons, title=menu.more, type='tabdrop'))
        if c.site != Default:
            toolbar.insert(0, PageNameNav('subreddit'))

        return toolbar
                
    def __repr__(self):
        return "<Reddit>"

    @staticmethod
    def content_stack(*a):
        """Helper method for reordering the content stack."""
        return PaneStack(filter(None, a))

    def content(self):
        """returns a Wrapped (or renderable) item for the main content div."""
        return self.content_stack(self.infobar, self.nav_menu, self._content)

class LoginFormWide(Wrapped):
    """generates a login form suitable for the 300px rightbox."""
    pass

class SubredditInfoBar(Wrapped):
    """When not on Default, renders a sidebox which gives info about
    the current reddit, including links to the moderator and
    contributor pages, as well as links to the banning page if the
    current user is a moderator."""
    def nav(self):
        is_moderator = c.user_is_loggedin and \
            c.site.is_moderator(c.user) or c.user_is_admin

        buttons = [NavButton(plurals.moderators, 'moderators')]
        if is_moderator:
            buttons.append(NamedButton('edit'))
            if c.site.type != 'public':
                buttons.append(NavButton(plurals.contributors, 'contributors'))
            buttons.extend([NavButton(menu.banusers, 'banned'),
                            NamedButton('spam')])
        return [NavMenu(buttons, type = "flatlist", base_path = "/about/")]

class SideBox(Wrapped):
    """Generic sidebox used to generate the 'submit' and 'create a reddit' boxes."""
    def __init__(self, title, link, css_class='', subtitles = [],
                 show_cover = False):
        Wrapped.__init__(self, link = link, 
                         title = title, css_class = css_class,
                         subtitles = subtitles, show_cover = show_cover)


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

class PrefOptions(Wrapped):
    """Preference form for updating language and display options"""
    def __init__(self, done = False):
        Wrapped.__init__(self, done = done)

class PrefUpdate(Wrapped):
    """Preference form for updating email address and passwords"""
    pass

class PrefDelete(Wrapped):
    """preference form for deleting a user's own account."""
    pass


class MessagePage(Reddit):
    """Defines the content for /message/*"""
    def __init__(self, *a, **kw):
        Reddit.__init__(self, *a, **kw)
        self.replybox = CommentReplyBox()

    def content(self):
        return self.content_stack(self.replybox, self.infobar,
                                  self.nav_menu, self._content)

    def build_toolbars(self):
        buttons =  [NamedButton('compose'),
                    NamedButton('inbox'),
                    NamedButton('sent')]
        return [PageNameNav('nomenu', title = _("message")), 
                NavMenu(buttons, base_path = "/message", type="tabmenu")]

class MessageCompose(Wrapped):
    """Compose message form."""
    def __init__(self,to='', subject='', message='', success=''):
        Wrapped.__init__(self, to = to, subject = subject,
                         message = message, success = success)

    
class BoringPage(Reddit):
    """parent class For rendering all sorts of uninteresting,
    sortless, navless form-centric pages.  The top navmenu is
    populated only with the text provided with pagename and the page
    title is 'reddit.com: pagename'"""
    
    extension_handling= False
    
    def __init__(self, pagename, **context):
        self.pagename = pagename
        Reddit.__init__(self, title = "%s: %s" % (c.site.name, pagename),
                        **context)

    def build_toolbars(self):
        return [PageNameNav('nomenu', title = self.pagename)]


class FormPage(BoringPage):
    """intended for rendering forms with no rightbox needed or wanted"""
    def __init__(self, pagename, show_sidebar = False, *a, **kw):
        BoringPage.__init__(self, pagename,  show_sidebar = show_sidebar, *a, **kw)
        

class LoginPage(BoringPage):
    """a boring page which provides the Login/register form"""
    def __init__(self, **context):
        context['loginbox'] = False
        self.dest = context.get('dest', '')
        context['show_sidebar'] = False
        BoringPage.__init__(self,  _("login or register"), **context)

    def content(self):
        return Login(dest = self.dest)


class Login(Wrapped):
    """The two-unit login and register form."""
    def __init__(self, user_reg = '', user_login = '', dest=''):
        Wrapped.__init__(self, user_reg = user_reg, user_login = user_login, dest = dest)

    
class SearchPage(BoringPage):
    """Search results page"""
    searchbox = False

    def __init__(self, pagename, prev_search, elapsed_time, num_results, *a, **kw):
        self.searchbar = SearchBar(prev_search = prev_search,
                                   elapsed_time = elapsed_time,
                                   num_results = num_results)
        BoringPage.__init__(self, pagename, *a, **kw)

    def content(self):
        return self.content_stack(self.searchbar, self.nav_menu, self._content)

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

    def __init__(self, link = None, title = '', *a, **kw):
        # TODO: temp hack until we find place for builder_wrapper
        from r2.controllers.listingcontroller import ListingController
        link_builder = IDBuilder(link._fullname, wrap = ListingController.builder_wrapper)

        # link_listing will be the one-element listing at the top
        self.link_listing = LinkListing(link_builder, nextprev=False).listing()

        # link is a wrapped Link object
        self.link = self.link_listing.things[0]

        title = c.site.name + ((': ' + self.link.title) \
                               if hasattr(self.link, 'title') else '')
         
        Reddit.__init__(self, title = title, *a, **kw)

    def build_toolbars(self):
        base_path = "/info/%s/" % self.link._id36
        
        buttons = [NavButton(plurals.comments, 'comments'),
                   NamedButton('related')]

        if c.user_is_admin:
            buttons += [NamedButton('details')]

        toolbar = [NavMenu(buttons, base_path = base_path, type="tabmenu")]

        if c.site != Default:
            toolbar.insert(0, PageNameNav('subreddit'))

        return toolbar
    
    def content(self):
        return self.content_stack(self.infobar, self.link_listing,
                                  self.nav_menu, self._content)

    def rightbox(self):
        rb = Reddit.rightbox(self)
        rb.insert(1, LinkInfoBar(a = self.link))
        return rb

class LinkInfoBar(Wrapped):
    """Right box for providing info about a link."""
    def __init__(self, a = None):
        Wrapped.__init__(self, a = a)


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
        return [PageNameNav('subreddit')]



class SubredditsPage(Reddit):
    """container for rendering a list of reddits.  The corner
    searchbox is hidden and its functionality subsumed by an in page
    SearchBar for searching over reddits.  As a result this class
    takes the same arguments as SearchBar, which it uses to construct
    self.searchbar"""
    searchbox    = False

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
        if c.user_is_loggedin:
            #add the aliases to "my reddits" stays highlighted
            buttons.append(NamedButton("mine", aliases=['/reddits/mine/subscriber',
                                                        '/reddits/mine/contributor',
                                                        '/reddits/mine/moderator']))
               

        return [PageNameNav('reddits'),
                NavMenu(buttons, base_path = '/reddits', type="tabmenu")]

    def content(self):
        return self.content_stack(self.searchbar, self.nav_menu,
                                  self.sr_infobar, self._content)

class MySubredditsPage(SubredditsPage):
    """Same functionality as SubredditsPage, without the search box."""
    
    def content(self):
        return self.content_stack(self.nav_menu, self.infobar, self._content)


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

class ProfileBar(Wrapped): 
    """Draws a right box for info about the user (karma, etc)"""
    def __init__(self, user):
        Wrapped.__init__(self, user = user)
        self.isFriend = self.user._id in c.user.friends \
            if c.user_is_loggedin else False
        self.isMe = (self.user == c.user)

class MenuArea(Wrapped):
    """Draws the gray box at the top of a page for sort menus"""
    def __init__(self, menus = []):
        Wrapped.__init__(self, menus = menus)

class InfoBar(Wrapped):
    """Draws the yellow box at the top of a page for info"""
    def __init__(self, message = ''):
        Wrapped.__init__(self, message = message)

class UnfoundPage(Wrapped):
    """Wrapper for the 404 page"""
    def __init__(self, choice='a'):
        Wrapped.__init__(self, choice=choice)

class ErrorPage(Wrapped):
    """Wrapper for an error message"""
    def __init__(self, message = _("you aren't allowed to do that.")):
        Wrapped.__init__(self, message = message)
    
class Profiling(Wrapped):
    """Debugging template for code profiling using built in python
    library (only used in middleware)"""
    def __init__(self, header = '', table = [], caller = [], callee = [], path = ''):
        Wrapped.__init__(self, header = header, table = table, caller = caller,
                         callee = callee, path = path)

class Over18(Wrapped):
    """The creepy 'over 18' check page for nsfw content."""
    pass

class SubredditBox(Wrapped):
    """A content pane that has the lists of subreddits that go in the
    right pane by default"""
    def __init__(self, checkboxes = True):
        Wrapped.__init__(self)

        self.checkboxes = checkboxes
        if checkboxes:
            self.title = _('Customize your reddit')
            self.subtitle = _('Select which communities you want to see')
        else:
            self.title = _('Other reddit communities')
            self.subtitle = 'Visit your subscribed reddits (in bold) or explore new ones'
        self.create_link = ('/reddits/', menu.more)
        self.more_link   = ('/reddits/create', _('create'))

        my_reddits = []
        sr_ids = Subreddit.user_subreddits(c.user if c.user_is_loggedin else None)
        if sr_ids:
            my_reddits = Subreddit._byID(sr_ids, True,
                                         return_dict = False)
            my_reddits.sort(key = lambda sr: sr._downs, reverse = True)

        display_reddits = my_reddits[:g.num_side_reddits]
        
        #remove the current reddit
        display_reddits = filter(lambda x: x != c.site, display_reddits)

        pop_reddits = Subreddit.default_srs(c.content_langs, limit = g.num_side_reddits)
        #add english reddits to the list
        if c.content_langs != 'all' and 'en' not in c.content_langs:
            en_reddits = Subreddit.default_srs(['en'])
            pop_reddits += [sr for sr in en_reddits if sr not in pop_reddits]

        for sr in pop_reddits:
            if len(display_reddits) >= g.num_side_reddits:
                break

            if sr != c.site and sr not in display_reddits:
                display_reddits.append(sr)

        col1, col2 = [], []
        cur_col, other = col1, col2
        for sr in display_reddits:
            cur_col.append((sr, sr in my_reddits))
            cur_col, other = other, cur_col

        self.cols = ((col1, col2))
        self.mine = my_reddits

class CreateSubreddit(Wrapped):
    """reddit creation form."""
    def __init__(self, site = None, name = ''):
        Wrapped.__init__(self, site = site, name = name)


class Password(Wrapped):
    """Form encountered when 'recover password' is clicked in the LoginFormWide."""
    def __init__(self, success=False):
        Wrapped.__init__(self, success = success)

class PasswordReset(Wrapped):
    """Template for generating an email to the user who wishes to
    reset their password (step 2 of password recovery, after they have
    entered their user name in Password.)"""
    pass

class ResetPassword(Wrapped):
    """Form for actually resetting a lost password, after the user has
    clicked on the link provided to them in the Password_Reset email
    (step 3 of password recovery.)"""
    pass


class Captcha(Wrapped):
    """Container for rendering robot detection device."""
    def __init__(self, error=None):
        self.error = _('try entering those letters again') if error else ""
        self.iden = get_captcha()
        Wrapped.__init__(self)

class CommentReplyBox(Wrapped):
    """Used on LinkInfoPage to render the comment reply form at the
    top of the comment listing as well as the template for the forms
    which are JS inserted when clicking on 'reply' in either a comment
    or message listing."""
    def __init__(self, link_name='', captcha=None, action = 'comment'):
        Wrapped.__init__(self, link_name = link_name, captcha = captcha,
                         action = action)

class PermalinkMessage(Wrapped):
    """renders the box on comment pages that state 'you are viewing a
    single comment's thread'"""
    def __init__(self, comments_url):
        self.comments_url = comments_url


class PaneStack(Wrapped):
    """Utility class for storing and rendering a list of block elements."""
    
    def __init__(self, panes=[], div_id = None, css_class=None, div=False):
        div = div or div_id or css_class or False
        self.div_id    = div_id
        self.css_class = css_class
        self.div       = div
        self.stack     = list(panes)
        Wrapped.__init__(self)

    def append(self, item):
        """Appends an element to the end of the current stack"""
        self.stack.append(item)
    
    def push(self, item):
        """Prepends an element to the top of the current stack"""
        self.stack.insert(0, item)

    def insert(self, *a):
        """inerface to list.insert on the current stack"""
        return self.stack.insert(*a)


class SearchForm(Wrapped):
    """The simple search form in the header of the page.  prev_search
    is the previous search."""
    def __init__(self, prev_search = ''):
        Wrapped.__init__(self, prev_search = prev_search)


class SearchBar(Wrapped):
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

        Wrapped.__init__(self)


class Frame(Wrapped):
    """Frameset for the FrameToolbar used when a user hits /goto and
    has pref_toolbar set.  The top 30px of the page are dedicated to
    the toolbar, while the rest of the page will show the results of
    following the link."""
    def __init__(self, url='', title='', fullname=''):
        Wrapped.__init__(self, url = url, title = title, fullname = fullname)

class FrameToolbar(Wrapped):
    """The reddit voting toolbar used together with Frame."""
    pass


class NewLink(Wrapped):
    """Render the link submission form"""
    def __init__(self, captcha = None, url = '', title= '', subreddits = ()):
        Wrapped.__init__(self, captcha = captcha, url = url,
                         title = title, subreddits = subreddits)

class UserStats(Wrapped):
    """For drawing the stats page, which is fetched from the cache."""
    def __init__(self):
        Wrapped.__init__(self)
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


class ButtonEmbed(Wrapped):
    """Generates the JS wrapper around the buttons for embedding."""
    def __init__(self, button = None, width = 100, height=100, referer = ""):
        Wrapped.__init__(self, button = button, width = width, height = height,
                         referer=referer)

class Button(Wrapped):
    """the voting buttons, embedded with the ButtonEmbed wrapper, shown on /buttons"""
    def __init__(self, link = None, likes = None, 
                 button = None, css=None,
                 url = None, title = '', score_fmt = None):
        Wrapped.__init__(self, link = link, likes = likes, score_fmt = score_fmt,
                         button = button, css = css, url = url, title = title)


class ButtonDemoPanel(Wrapped):
    """The page for showing the different styles of embedable voting buttons"""
    pass


class Feedback(Wrapped):
    """The feedback and ad inquery form(s)"""
    def __init__(self, captcha=None, title=None, action='/feedback',
                    message='', name='', email='', replyto='', success = False):
        Wrapped.__init__(self, captcha = captcha, title = title, action = action,
                         message = message, name = name, email = email, replyto = replyto,
                         success = success)


class WidgetDemoPanel(Wrapped):
    """Demo page for the .embed widget."""
    pass

class Bookmarklets(Wrapped):
    """The bookmarklets page."""
    def __init__(self, buttons=["reddit", "like", "dislike",
                             "save", "serendipity!"]):
        Wrapped.__init__(self, buttons = buttons)



class AdminTranslations(Wrapped):
    """The translator control interface, used for determining which
    user is allowed to edit which translation file and for providing a
    summary of what translation files are done and/or in use."""
    def __init__(self):
        from r2.lib.translation import list_translations
        Wrapped.__init__(self)
        self.translations = list_translations()
        

class Embed(Wrapped):
    """wrapper for embedding /help into reddit as if it were not on a separate wiki."""
    def __init__(self,content = ''):
        Wrapped.__init__(self, content = content)


class Page_down(Wrapped):
    def __init__(self, **kw):
        message = kw.get('message', _("This feature is currently unavailable. Sorry"))
        Wrapped.__init__(self, message = message)

# Classes for dealing with friend/moderator/contributor/banned lists

# TODO: if there is time, we could roll these Ajaxed classes into the
# JsonTemplates framework...
class Ajaxed():
    """Base class for allowing simple interaction of UserTableItem and
    UserItem classes to be edited via JS and AJax requests.  In
    analogy with Wrapped, this class provides an interface for
    'rendering' dictionary representations of the data which can be
    passed to the client via JSON over AJAX"""
    __slots__ = ['kind', 'action', 'data']
    
    def __init__(self, kind, action):
        self._ajax = dict(kind=kind,
                          action = None,
                          data = {})

    def for_ajax(self, action = None):
        self._ajax['action'] = action
        self._ajax['data'] = self.ajax_render()
        return self._ajax

    def ajax_render(self, style="html"):
        return {}


class UserTableItem(Wrapped, Ajaxed):
    """A single row in a UserList of type 'type' and of name
    'container_name' for a given user.  The provided list of 'cells'
    will determine what order the different columns are rendered in.
    Currently, this list can consist of 'user', 'sendmessage' and
    'remove'."""
    def __init__(self, user, type, cellnames, container_name, editable):
        self.user, self.type, self.cells = user, type, cellnames
        self.container_name = container_name
        self.name           = "tr_%s_%s" % (user.name, type)
        self.editable       = editable
        Wrapped.__init__(self)
        Ajaxed.__init__(self, 'UserTable', 'add')

    def ajax_render(self, style="html"):
        """Generates a 'rendering' of this item suitable for
        processing by JS for insert or removal from an existing
        UserList"""
        cells = []
        for cell in self.cells:
            r = Wrapped.part_render(self, 'cell_type', cell)
            cells.append(spaceCompress(r))
        return dict(cells=cells, id=self.type, name=self.name)

    def __repr__(self):
        return '<UserTableItem "%s">' % self.user.name

class UserList(Wrapped):
    """base class for generating a list of users"""    
    form_title     = ''
    table_title    = ''
    type           = ''
    container_name = ''
    cells          = ('user', 'sendmessage', 'remove')
    _class         = ""

    def __init__(self, editable = True):
        self.editable = editable
        Wrapped.__init__(self)

    def ajax_user(self, user):
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
            return [self.ajax_user(u) for u in users]
        else:
            return ()

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
        return  plurals.contributors

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
        return plurals.moderators

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
        return self.content_stack(self.link_listing, Details(link = self.link))
        
