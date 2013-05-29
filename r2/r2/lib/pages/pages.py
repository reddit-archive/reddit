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

from collections import OrderedDict

from r2.lib.wrapped import Wrapped, Templated, CachedTemplate
from r2.models import Account, FakeAccount, DefaultSR, make_feedurl
from r2.models import FakeSubreddit, Subreddit, SubSR, AllMinus, AllSR
from r2.models import Friends, All, Sub, NotFound, DomainSR, Random, Mod, RandomNSFW, RandomSubscription, MultiReddit, ModSR, Frontpage
from r2.models import Link, Printable, Trophy, bidding, PromoCampaign, PromotionWeights, Comment
from r2.models import Flair, FlairTemplate, FlairTemplateBySubredditIndex
from r2.models import USER_FLAIR, LINK_FLAIR
from r2.models import GoldPartnerDealCode
from r2.models.promo import NO_TRANSACTION, PromotionLog
from r2.models.token import OAuth2Client, OAuth2AccessToken
from r2.models import traffic
from r2.models import ModAction
from r2.models import Thing
from r2.models.wiki import WikiPage
from r2.lib.db import tdb_cassandra
from r2.config import cache
from r2.config.extensions import is_api
from r2.lib.menus import CommentSortMenu
from pylons.i18n import _, ungettext
from pylons import c, request, g
from pylons.controllers.util import abort

from r2.lib import media, inventory
from r2.lib import promote, tracking
from r2.lib.captcha import get_iden
from r2.lib.filters import (
    spaceCompress,
    _force_unicode,
    _force_utf8,
    unsafe,
    websafe,
    SC_ON,
    SC_OFF,
    websafe_json,
    wikimarkdown,
)
from r2.lib.menus import NavButton, NamedButton, NavMenu, PageNameNav, JsButton
from r2.lib.menus import SubredditButton, SubredditMenu, ModeratorMailButton
from r2.lib.menus import OffsiteButton, menu, JsNavMenu
from r2.lib.strings import plurals, rand_strings, strings, Score
from r2.lib.utils import title_to_url, query_string, UrlParser, vote_hash
from r2.lib.utils import url_links_builder, make_offset_date, median, to36
from r2.lib.utils import trunc_time, timesince, timeuntil, weighted_lottery
from r2.lib.template_helpers import add_sr, get_domain, format_number
from r2.lib.subreddit_search import popular_searches
from r2.lib.scraper import get_media_embed
from r2.lib.log import log_text
from r2.lib.memoize import memoize
from r2.lib.utils import trunc_string as _truncate, to_date
from r2.lib.filters import safemarkdown

from babel.numbers import format_currency
from collections import defaultdict
import csv
import cStringIO
import pytz
import sys, random, datetime, calendar, simplejson, re, time
import time
from itertools import chain, product
from urllib import quote, urlencode

# the ip tracking code is currently deeply tied with spam prevention stuff
# this will be open sourced as soon as it can be decoupled
try:
    from r2admin.lib.ip_events import ips_by_account_id
except ImportError:
    def ips_by_account_id(account_id):
        return []

from things import wrap_links, default_thing_wrapper

datefmt = _force_utf8(_('%d %b %Y'))

MAX_DESCRIPTION_LENGTH = 150

def get_captcha():
    if not c.user_is_loggedin or c.user.needs_captcha():
        return get_iden()

def responsive(res, space_compress = False):
    """
    Use in places where the template is returned as the result of the
    controller so that it becomes compatible with the page cache.
    """
    if is_api():
        res = websafe_json(simplejson.dumps(res or ''))
        if c.allowed_callback:
            res = "%s(%s)" % (websafe_json(c.allowed_callback), res)
    elif space_compress:
        res = spaceCompress(res)
    return res

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

      create_reddit_box -- enable/disable display of the "Create a reddit" box
      submit_box        -- enable/disable display of the "Submit" box
      searchbox         -- enable/disable the "search" box in the header
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
    show_infobar       = True
    content_id         = None
    css_class          = None
    extra_page_classes = None
    extra_stylesheets  = []

    def __init__(self, space_compress = True, nav_menus = None, loginbox = True,
                 infotext = '', content = None, short_description='', title = '', robots = None, 
                 show_sidebar = True, footer = True, srbar = True, page_classes = None,
                 show_wiki_actions = False, extra_js_config = None, **context):
        Templated.__init__(self, **context)
        self.title          = title
        self.short_description = short_description
        self.robots         = robots
        self.infotext       = infotext
        self.extra_js_config = extra_js_config
        self.show_wiki_actions = show_wiki_actions
        self.loginbox       = True
        self.show_sidebar   = show_sidebar
        self.space_compress = space_compress and not g.template_debug
        # instantiate a footer
        self.footer         = RedditFooter() if footer else None
        self.supplied_page_classes = page_classes or []

        #put the sort menus at the top
        self.nav_menu = MenuArea(menus = nav_menus) if nav_menus else None

        #add the infobar
        self.welcomebar = None
        self.infobar = None
        # generate a canonical link for google
        self.canonical_link = request.fullpath
        if c.render_style != "html":
            u = UrlParser(request.fullpath)
            u.set_extension("")
            u.hostname = g.domain
            if g.domain_prefix:
                u.hostname = "%s.%s" % (g.domain_prefix, u.hostname)
            self.canonical_link = u.unparse()

        if self.show_infobar:
            if not infotext:
                if g.heavy_load_mode:
                    # heavy load mode message overrides read only
                    infotext = strings.heavy_load_msg
                elif g.read_only_mode:
                    infotext = strings.read_only_msg
                elif g.live_config.get("announcement_message"):
                    infotext = g.live_config["announcement_message"]

            if infotext:
                self.infobar = InfoBar(message=infotext)
            elif (isinstance(c.site, DomainSR) and
                    c.site.domain.endswith("imgur.com")):
                self.infobar = InfoBar(message=
                    _("imgur.com domain listings (including this one) are "
                      "currently disabled to speed up vote processing.")
                )
            elif isinstance(c.site, AllMinus) and not c.user.gold:
                self.infobar = InfoBar(message=strings.all_minus_gold_only,
                                       extra_class="gold")

            if not c.user_is_loggedin:
                self.welcomebar = WelcomeBar()

        self.srtopbar = None
        if srbar and not c.cname and not is_api():
            self.srtopbar = SubredditTopBar()

        if (c.user_is_loggedin and self.show_sidebar
            and not is_api() and not self.show_wiki_actions):
            # insert some form templates for js to use
            # TODO: move these to client side templates
            gold = GoldPayment("gift",
                               "monthly",
                               months=1,
                               signed=False,
                               recipient="",
                               giftmessage=None,
                               passthrough=None,
                               comment=None,
                               clone_template=True,
                              )
            self._content = PaneStack([ShareLink(), content, gold])
        else:
            self._content = content

        self.toolbars = self.build_toolbars()
    
    def wiki_actions_menu(self, moderator=False):
        buttons = []
        
        buttons.append(NamedButton("wikirecentrevisions", 
                                   css_class="wikiaction-revisions",
                                   dest="/wiki/revisions"))
        
        buttons.append(NamedButton("wikipageslist", 
                           css_class="wikiaction-pages",
                           dest="/wiki/pages"))
        if moderator:
            buttons += [NamedButton('wikibanned', css_class='reddit-ban', 
                                    dest='/about/wikibanned'),
                        NamedButton('wikicontributors', 
                                    css_class='reddit-contributors', 
                                    dest='/about/wikicontributors')
                        ]
                           
        return SideContentBox(_('wiki tools'),
                      [NavMenu(buttons,
                               type="flat_vert",
                               css_class="icon-menu",
                               separator="")],
                      _id="wikiactions",
                      collapsible=True)
    
    def sr_admin_menu(self):
        buttons = []
        is_single_subreddit = not isinstance(c.site, (ModSR, MultiReddit))
        is_admin = c.user_is_loggedin and c.user_is_admin
        is_moderator_with_perms = lambda *perms: (
            is_admin or c.site.is_moderator_with_perms(c.user, *perms))

        if is_single_subreddit and is_moderator_with_perms('config'):
            buttons.append(NavButton(menu.community_settings,
                                     css_class="reddit-edit",
                                     dest="edit"))

        if is_moderator_with_perms('mail'):
            buttons.append(NamedButton("modmail",
                                    dest="message/inbox",
                                    css_class="moderator-mail"))

        if is_single_subreddit:
            if is_moderator_with_perms('access'):
                buttons.append(NamedButton("moderators",
                                           css_class="reddit-moderators"))

                if c.site.type != "public":
                    buttons.append(NamedButton("contributors",
                                               css_class="reddit-contributors"))
                else:
                    buttons.append(NavButton(menu.contributors,
                                             "contributors",
                                             css_class="reddit-contributors"))

            buttons.append(NamedButton("traffic", css_class="reddit-traffic"))

        if is_moderator_with_perms('posts'):
            buttons += [NamedButton("modqueue", css_class="reddit-modqueue"),
                        NamedButton("reports", css_class="reddit-reported"),
                        NamedButton("spam", css_class="reddit-spam")]

        if is_single_subreddit:
            if is_moderator_with_perms('access'):
                buttons.append(NamedButton("banned", css_class="reddit-ban"))
            if is_moderator_with_perms('flair'):
                buttons.append(NamedButton("flair", css_class="reddit-flair"))

        buttons.append(NamedButton("log", css_class="reddit-moderationlog"))
        if is_moderator_with_perms('posts'):
            buttons.append(
                NamedButton("unmoderated", css_class="reddit-unmoderated"))

        return SideContentBox(_('moderation tools'),
                              [NavMenu(buttons,
                                       type="flat_vert",
                                       base_path="/about/",
                                       css_class="icon-menu",
                                       separator="")],
                              _id="moderation_tools",
                              collapsible=True)

    def sr_moderators(self, limit = 10):
        accounts = Account._byID([uid
                                  for uid in c.site.moderators[:limit]],
                                 data=True, return_dict=False)
        return [WrappedUser(a) for a in accounts if not a._deleted]

    def rightbox(self):
        """generates content in <div class="rightbox">"""

        ps = PaneStack(css_class='spacer')

        if self.searchbox:
            ps.append(SearchForm())

        sidebar_message = g.live_config.get("sidebar_message")
        if sidebar_message and isinstance(c.site, DefaultSR):
            ps.append(SidebarMessage(sidebar_message[0]))

        gold_sidebar_message = g.live_config.get("gold_sidebar_message")
        if (c.user_is_loggedin and c.user.gold and
                gold_sidebar_message and isinstance(c.site, DefaultSR)):
            ps.append(SidebarMessage(gold_sidebar_message[0],
                                     extra_class="gold"))

        if not c.user_is_loggedin and self.loginbox and not g.read_only_mode:
            ps.append(LoginFormWide())

        if c.user.pref_show_sponsorships or not c.user.gold:
            ps.append(SponsorshipBox())

        user_banned = c.user_is_loggedin and c.site.is_banned(c.user)

        if (self.submit_box
                and (c.user_is_loggedin or not g.read_only_mode)
                and not user_banned):
            if (not isinstance(c.site, FakeSubreddit)
                    and c.site.type in ("archived", "restricted")
                    and not (c.user_is_loggedin
                             and c.site.can_submit(c.user))):
                if c.site.type == "archived":
                    subtitle = _('this subreddit is archived '
                                 'and no longer accepting submissions.')
                    ps.append(SideBox(title=_('Submissions disabled'),
                                      css_class="submit",
                                      disabled=True,
                                      subtitles=[subtitle],
                                      show_icon=False))
                else:
                    subtitle = _('submission in this subreddit '
                                 'is restricted to approved submitters.')
                    ps.append(SideBox(title=_('Submissions restricted'),
                                      css_class="submit",
                                      disabled=True,
                                      subtitles=[subtitle],
                                      show_icon=False))
            else:
                fake_sub = isinstance(c.site, FakeSubreddit)
                if c.site.link_type != 'self':
                    ps.append(SideBox(title=c.site.submit_link_label or
                                            strings.submit_link_label,
                                      css_class="submit submit-link",
                                      link="/submit",
                                      sr_path=not fake_sub,
                                      show_cover=True))
                if c.site.link_type != 'link':
                    ps.append(SideBox(title=c.site.submit_text_label or
                                            strings.submit_text_label,
                                      css_class="submit submit-text",
                                      link="/submit?selftext=true",
                                      sr_path=not fake_sub,
                                      show_cover=True))

        no_ads_yet = True
        show_adbox = (c.user.pref_show_adbox or not c.user.gold) and not g.disable_ads
        if isinstance(c.site, (MultiReddit, ModSR)) and c.user_is_loggedin:
            srs = Subreddit._byID(c.site.sr_ids, data=True,
                                  return_dict=False)
            if c.user_is_admin or c.site.is_moderator(c.user):
                ps.append(self.sr_admin_menu())

            if srs:
                if isinstance(c.site, ModSR):
                    box = SubscriptionBox(srs, multi_text=strings.mod_multi)
                else:
                    box = SubscriptionBox(srs)
                ps.append(SideContentBox(_('these subreddits'), [box]))

        if isinstance(c.site, AllSR):
            ps.append(AllInfoBar(c.site, c.user))

        # don't show the subreddit info bar on cnames unless the option is set
        if not isinstance(c.site, FakeSubreddit) and (not c.cname or c.site.show_cname_sidebar):
            ps.append(SubredditInfoBar())
            moderator = c.user_is_loggedin and (c.user_is_admin or 
                                          c.site.is_moderator(c.user))
            wiki_moderator = c.user_is_loggedin and (
                c.user_is_admin
                or c.site.is_moderator_with_perms(c.user, 'wiki'))
            if self.show_wiki_actions:
                menu = self.wiki_actions_menu(moderator=wiki_moderator)
                ps.append(menu)
            if moderator:
                ps.append(self.sr_admin_menu())
            if show_adbox:
                ps.append(Ads())
            no_ads_yet = False
        elif self.show_wiki_actions:
            ps.append(self.wiki_actions_menu())

        if self.create_reddit_box and c.user_is_loggedin:
            delta = datetime.datetime.now(g.tz) - c.user._date
            if delta.days >= g.min_membership_create_community:
                ps.append(SideBox(_('Create your own subreddit'),
                           '/subreddits/create', 'create',
                           subtitles = rand_strings.get("create_reddit", 2),
                           show_cover = True, nocname=True))

        if not isinstance(c.site, FakeSubreddit) and not c.cname:
            moderators = self.sr_moderators()
            if moderators:
                total = len(c.site.moderators)
                more_text = mod_href = ""
                if total > len(moderators):
                    more_text = "...and %d more" % (total - len(moderators))
                    mod_href = "http://%s/about/moderators" % get_domain()

                if '/r/%s' % c.site.name == g.admin_message_acct:
                    label = _('message the admins')
                else:
                    label = _('message the moderators')
                helplink = ("/message/compose?to=%%2Fr%%2F%s" % c.site.name,
                            label)
                ps.append(SideContentBox(_('moderators'), moderators,
                                         helplink = helplink, 
                                         more_href = mod_href,
                                         more_text = more_text))

        if no_ads_yet and show_adbox:
            ps.append(Ads())
            if g.live_config["goldvertisement_blurbs"]:
                ps.append(Goldvertisement())

        if c.user.pref_clickgadget and c.recent_clicks:
            ps.append(SideContentBox(_("Recently viewed links"),
                                     [ClickGadget(c.recent_clicks)]))

        if c.user_is_loggedin:
            activity_link = AccountActivityBox()
            ps.append(activity_link)

        return ps

    def render(self, *a, **kw):
        """Overrides default Templated.render with two additions
           * support for rendering API requests with proper wrapping
           * support for space compression of the result
        In adition, unlike Templated.render, the result is in the form of a pylons
        Response object with it's content set.
        """
        res = Templated.render(self, *a, **kw)
        return responsive(res, self.space_compress)
    
    def corner_buttons(self):
        """set up for buttons in upper right corner of main page."""
        buttons = []
        if c.user_is_loggedin:
            if c.user.name in g.admins:
                if c.user_is_admin:
                    buttons += [OffsiteButton(
                        _("turn admin off"),
                        dest="%s/adminoff?dest=%s" %
                            (g.https_endpoint, quote(request.fullpath)),
                        target = "_self",
                    )]
                else:
                    buttons += [OffsiteButton(
                        _("turn admin on"),
                        dest="%s/adminon?dest=%s" %
                            (g.https_endpoint, quote(request.fullpath)),
                        target = "_self",
                    )]
            buttons += [NamedButton("prefs", False,
                                  css_class = "pref-lang")]
        else:
            lang = c.lang.split('-')[0] if c.lang else ''
            lang_name = g.lang_name.get(lang) or [lang, '']
            lang_name = "".join(lang_name)
            buttons += [JsButton(lang_name,
                                 onclick = "return showlang();",
                                 css_class = "pref-lang")]
        return NavMenu(buttons, base_path = "/", type = "flatlist")

    def build_toolbars(self):
        """Sets the layout of the navigation topbar on a Reddit.  The result
        is a list of menus which will be rendered in order and
        displayed at the top of the Reddit."""
        if c.site == Friends:
            main_buttons = [NamedButton('new', dest='', aliases=['/hot']),
                            NamedButton('comments')]
        else:
            main_buttons = [NamedButton('hot', dest='', aliases=['/hot']),
                            NamedButton('new'), 
                            NamedButton('rising'),
                            NamedButton('controversial'),
                            NamedButton('top'),
                            ]

            if c.user_is_loggedin:
                main_buttons.append(NamedButton('saved', False))

            mod = False
            if c.user_is_loggedin:
                mod = bool(c.user_is_admin
                           or c.site.is_moderator_with_perms(c.user, 'wiki'))
            if c.site._should_wiki and (c.site.wikimode != 'disabled' or mod):
                if not g.disable_wiki:
                    main_buttons.append(NavButton('wiki', 'wiki'))

        more_buttons = []

        if c.user_is_loggedin:
            if c.user.pref_show_promote or c.user_is_sponsor:
                more_buttons.append(NavButton(menu.promote, 'promoted', False))

        #if there's only one button in the dropdown, get rid of the dropdown
        if len(more_buttons) == 1:
            main_buttons.append(more_buttons[0])
            more_buttons = []

        toolbar = [NavMenu(main_buttons, type='tabmenu')]
        if more_buttons:
            toolbar.append(NavMenu(more_buttons, title=menu.more, type='tabdrop'))

        if not isinstance(c.site, DefaultSR) and not c.cname:
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
        return self.content_stack((
            self.welcomebar, self.infobar, self.nav_menu, self._content))

    def page_classes(self):
        classes = set()

        if c.user_is_loggedin:
            classes.add('loggedin')
            if not isinstance(c.site, FakeSubreddit):
                if c.site.is_subscriber(c.user):
                    classes.add('subscriber')
                if c.site.is_contributor(c.user):
                    classes.add('contributor')
                if c.cname:
                    classes.add('cname')
            if c.site.is_moderator(c.user):
                classes.add('moderator')
            if c.user.gold:
                classes.add('gold')

        if isinstance(c.site, MultiReddit):
            classes.add('multi-page')

        if self.extra_page_classes:
            classes.update(self.extra_page_classes)
        if self.supplied_page_classes:
            classes.update(self.supplied_page_classes)

        return classes

class AccountActivityBox(Templated):
    def __init__(self):
        super(AccountActivityBox, self).__init__()

class RedditHeader(Templated):
    def __init__(self):
        pass

class RedditFooter(CachedTemplate):
    def cachable_attrs(self):
        return [('path', request.path),
                ('buttons', [[(x.title, x.path) for x in y] for y in self.nav])]

    def __init__(self):
        self.nav = [
            NavMenu([
                    NamedButton("blog", False, nocname=True),
                    NamedButton("about", False, nocname=True),
                    NamedButton("team", False, nocname=True, dest="/about/team"),
                    NamedButton("code", False, nocname=True),
                    NamedButton("ad_inq", False, nocname=True),
                ],
                title = _("about"),
                type = "flat_vert",
                separator = ""),

            NavMenu([
                    NamedButton("wiki", False, nocname=True),
                    OffsiteButton(_("FAQ"), dest = "/wiki/faq", nocname=True),
                    OffsiteButton(_("reddiquette"), nocname=True, dest = "/wiki/reddiquette"),
                    NamedButton("rules", False, nocname=True),
                    NamedButton("feedback", False),
                ],
                title = _("help"),
                type = "flat_vert",
                separator = ""),

            NavMenu([
                    OffsiteButton("mobile", "http://i.reddit.com"),
                    OffsiteButton(_("firefox extension"), "https://addons.mozilla.org/firefox/addon/socialite/"),
                    OffsiteButton(_("chrome extension"), "https://chrome.google.com/webstore/detail/algjnflpgoopkdijmkalfcifomdhmcbe"),
                    NamedButton("buttons", True),
                    NamedButton("widget", True),
                ],
                title = _("tools"),
                type = "flat_vert",
                separator = ""),

            NavMenu([
                    NamedButton("gold", False, nocname=True, dest = "/gold/about", css_class = "buygold"),
                    NamedButton("store", False, nocname=True),
                    OffsiteButton(_("redditgifts"), "http://redditgifts.com"),
                    OffsiteButton(_("reddit.tv"), "http://reddit.tv"),
                    OffsiteButton(_("radio reddit"), "http://radioreddit.com"),
                ],
                title = _("<3"),
                type = "flat_vert",
                separator = "")
        ]
        CachedTemplate.__init__(self)

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
    show_infobar = False

    def page_classes(self):
        return ('min-body',)


class LoginFormWide(CachedTemplate):
    """generates a login form suitable for the 300px rightbox."""
    def __init__(self):
        self.cname = c.cname
        self.auth_cname = c.authorized_cname
        CachedTemplate.__init__(self)

class SubredditInfoBar(CachedTemplate):
    """When not on Default, renders a sidebox which gives info about
    the current reddit, including links to the moderator and
    contributor pages, as well as links to the banning page if the
    current user is a moderator."""

    def __init__(self, site = None):
        site = site or c.site

        # hackity hack. do i need to add all the others props?
        self.sr = list(wrap_links(site))[0]

        # we want to cache on the number of subscribers
        self.subscribers = self.sr._ups

        # so the menus cache properly
        self.path = request.path

        self.accounts_active, self.accounts_active_fuzzed = self.sr.get_accounts_active()

        if c.user_is_loggedin and c.user.pref_show_flair:
            self.flair_prefs = FlairPrefs()
        else:
            self.flair_prefs = None

        CachedTemplate.__init__(self)

    def nav(self):
        buttons = [NavButton(plurals.moderators, 'moderators')]
        if self.type != 'public':
            buttons.append(NavButton(getattr(plurals, "approved submitters"), 'contributors'))

        if self.is_moderator or self.is_admin:
            buttons.extend([
                    NamedButton('spam'),
                    NamedButton('reports'),
                    NavButton(menu.banusers, 'banned'),
                    NamedButton('traffic'),
                    NavButton(menu.community_settings, 'edit'),
                    NavButton(menu.flair, 'flair'),
                    NavButton(menu.modactions, 'modactions'),
                    ])
        return [NavMenu(buttons, type = "flat_vert", base_path = "/about/",
                        separator = '')]

class SponsorshipBox(Templated):
    pass

class SideContentBox(Templated):
    def __init__(self, title, content, helplink=None, _id=None, extra_class=None,
                 more_href = None, more_text = "more", collapsible=False):
        Templated.__init__(self, title=title, helplink = helplink,
                           content=content, _id=_id, extra_class=extra_class,
                           more_href = more_href, more_text = more_text,
                           collapsible=collapsible)

class SideBox(CachedTemplate):
    """
    Generic sidebox used to generate the 'submit' and 'create a reddit' boxes.
    """
    def __init__(self, title, link=None, css_class='', subtitles = [],
                 show_cover = False, nocname=False, sr_path = False,
                 disabled=False, show_icon=True):
        CachedTemplate.__init__(self, link = link, target = '_top',
                           title = title, css_class = css_class,
                           sr_path = sr_path, subtitles = subtitles,
                           show_cover = show_cover, nocname=nocname,
                           disabled=disabled, show_icon=show_icon)


class PrefsPage(Reddit):
    """container for pages accessible via /prefs.  No extension handling."""

    extension_handling = False

    def __init__(self, show_sidebar = False, *a, **kw):
        Reddit.__init__(self, show_sidebar = show_sidebar,
                        title = "%s (%s)" %(_("preferences"),
                                            c.site.name.strip(' ')),
                        *a, **kw)

    def build_toolbars(self):
        buttons = [NavButton(menu.options, ''),
                   NamedButton('apps')]

        if c.user.pref_private_feeds:
            buttons.append(NamedButton('feeds'))

        buttons.extend([NamedButton('friends'),
                        NamedButton('update')])

        if c.user_is_loggedin and c.user.name in g.admins:
            buttons += [NamedButton('otp')]

        #if CustomerID.get_id(user):
        #    buttons += [NamedButton('payment')]
        buttons += [NamedButton('delete')]
        return [PageNameNav('nomenu', title = _("preferences")), 
                NavMenu(buttons, base_path = "/prefs", type="tabmenu")]

class PrefOptions(Templated):
    """Preference form for updating language and display options"""
    def __init__(self, done = False):
        Templated.__init__(self, done = done)

class PrefFeeds(Templated):
    pass

class PrefOTP(Templated):
    pass

class PrefUpdate(Templated):
    """Preference form for updating email address and passwords"""
    def __init__(self, email = True, password = True, verify = False):
        self.email = email
        self.password = password
        self.verify = verify
        Templated.__init__(self)

class PrefApps(Templated):
    """Preference form for managing authorized third-party applications."""

    def __init__(self, my_apps, developed_apps):
        self.my_apps = my_apps
        self.developed_apps = developed_apps
        super(PrefApps, self).__init__()

class PrefDelete(Templated):
    """Preference form for deleting a user's own account."""
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
        buttons =  [NamedButton('compose', sr_path = False),
                    NamedButton('inbox', aliases = ["/message/comments",
                                                    "/message/uread",
                                                    "/message/messages",
                                                    "/message/selfreply"],
                                sr_path = False),
                    NamedButton('sent', sr_path = False)]
        if c.show_mod_mail:
            buttons.append(ModeratorMailButton(menu.modmail, "moderator",
                                               sr_path = False))
        if not c.default_sr:
            buttons.append(ModeratorMailButton(
                _("%(site)s mail") % {'site': c.site.name}, "moderator",
                aliases = ["/about/message/inbox",
                           "/about/message/unread"]))
        return [PageNameNav('nomenu', title = _("message")), 
                NavMenu(buttons, base_path = "/message", type="tabmenu")]

class MessageCompose(Templated):
    """Compose message form."""
    def __init__(self,to='', subject='', message='', success='', 
                 captcha = None):
        from r2.models.admintools import admintools

        Templated.__init__(self, to = to, subject = subject,
                         message = message, success = success,
                         captcha = captcha,
                         admins = admintools.admin_list())

    
class BoringPage(Reddit):
    """parent class For rendering all sorts of uninteresting,
    sortless, navless form-centric pages.  The top navmenu is
    populated only with the text provided with pagename and the page
    title is 'reddit.com: pagename'"""
    
    extension_handling= False
    
    def __init__(self, pagename, css_class=None, **context):
        self.pagename = pagename
        name = c.site.name or g.default_sr
        if css_class:
            self.css_class = css_class
        if "title" not in context:
            context['title'] = "%s: %s" % (name, pagename)

        Reddit.__init__(self, **context)

    def build_toolbars(self):
        if not isinstance(c.site, (DefaultSR, SubSR)) and not c.cname:
            return [PageNameNav('subreddit', title = self.pagename)]
        else:
            return [PageNameNav('nomenu', title = self.pagename)]

class HelpPage(BoringPage):
    def build_toolbars(self):
        return [PageNameNav('help', title = self.pagename)]

class FormPage(BoringPage):
    create_reddit_box  = False
    submit_box         = False
    """intended for rendering forms with no rightbox needed or wanted"""
    def __init__(self, pagename, show_sidebar = False, *a, **kw):
        BoringPage.__init__(self, pagename,  show_sidebar = show_sidebar,
                            *a, **kw)
        

class LoginPage(BoringPage):
    enable_login_cover = False
    short_title = "login"

    """a boring page which provides the Login/register form"""
    def __init__(self, **context):
        self.dest = context.get('dest', '')
        context['loginbox'] = False
        context['show_sidebar'] = False
        if c.render_style == "compact":
            title = self.short_title
        else:
            title = _("login or register")
        BoringPage.__init__(self,  title, **context)

        if self.dest:
            u = UrlParser(self.dest)
            # Display a preview message for OAuth2 client authorizations
            if u.path == '/api/v1/authorize':
                client_id = u.query_dict.get("client_id")
                self.client = client_id and OAuth2Client.get_token(client_id)
                if self.client:
                    self.infobar = ClientInfoBar(self.client,
                                                 strings.oauth_login_msg)
                else:
                    self.infobar = None

    def content(self):
        kw = {}
        for x in ('user_login', 'user_reg'):
            kw[x] = getattr(self, x) if hasattr(self, x) else ''
        login_content = self.login_template(dest = self.dest, **kw)
        return self.content_stack((self.infobar, login_content))

    @classmethod
    def login_template(cls, **kw):
        return Login(**kw)

class RegisterPage(LoginPage):
    short_title = "register"
    @classmethod
    def login_template(cls, **kw):
        return Register(**kw)

class AdminModeInterstitial(BoringPage):
    def __init__(self, dest, *args, **kwargs):
        self.dest = dest
        BoringPage.__init__(self, _("turn admin on"),
                            show_sidebar=False,
                            *args, **kwargs)

    def content(self):
        return PasswordVerificationForm(dest=self.dest)

class PasswordVerificationForm(Templated):
    def __init__(self, dest):
        self.dest = dest
        Templated.__init__(self)

class Login(Templated):
    """The two-unit login and register form."""
    def __init__(self, user_reg = '', user_login = '', dest='', is_popup=False):
        Templated.__init__(self, user_reg = user_reg, user_login = user_login,
                           dest = dest, captcha = Captcha(),
                           is_popup=is_popup,
                           registration_info=RegistrationInfo())

class Register(Login):
    pass


class RegistrationInfo(Templated):
    def __init__(self):
        html = unsafe(self.get_registration_info_html())
        Templated.__init__(self, content_html=html)

    @classmethod
    @memoize('registration_info_html', time=10*60)
    def get_registration_info_html(cls):
        try:
            wp = WikiPage.get(Frontpage, g.wiki_page_registration_info)
        except tdb_cassandra.NotFound:
            return ''
        else:
            return wikimarkdown(wp.content, include_toc=False, target='_blank')


class OAuth2AuthorizationPage(BoringPage):
    def __init__(self, client, redirect_uri, scope, state, duration):
        if duration == "permanent":
            expiration = None
        else:
            expiration = (
                datetime.datetime.now(g.tz)
                + datetime.timedelta(seconds=OAuth2AccessToken._ttl + 1))
        content = OAuth2Authorization(client=client,
                                      redirect_uri=redirect_uri,
                                      scope=scope,
                                      state=state,
                                      duration=duration,
                                      expiration=expiration)
        BoringPage.__init__(self, _("request for permission"),
                show_sidebar=False, content=content)

class OAuth2Authorization(Templated):
    pass

class SearchPage(BoringPage):
    """Search results page"""
    searchbox = False
    extra_page_classes = ['search-page']

    def __init__(self, pagename, prev_search, elapsed_time,
                 num_results, search_params={},
                 simple=False, restrict_sr=False, site=None,
                 syntax=None, converted_data=None, facets={}, sort=None,
                 recent=None,
                 *a, **kw):
        self.searchbar = SearchBar(prev_search=prev_search,
                                   elapsed_time=elapsed_time,
                                   num_results=num_results,
                                   search_params=search_params,
                                   show_feedback=True, site=site,
                                   simple=simple, restrict_sr=restrict_sr,
                                   syntax=syntax, converted_data=converted_data,
                                   facets=facets, sort=sort, recent=recent)
        BoringPage.__init__(self, pagename, robots='noindex', *a, **kw)

    def content(self):
        return self.content_stack((self.searchbar, self.infobar,
                                   self.nav_menu, self._content))

class TakedownPage(BoringPage):
    def __init__(self, link):
        BoringPage.__init__(self, getattr(link, "takedown_title", _("bummer")), 
                            content = TakedownPane(link))

    def render(self, *a, **kw):
        response = BoringPage.render(self, *a, **kw)
        return response


class TakedownPane(Templated):
    def __init__(self, link, *a, **kw):
        self.link = link
        self.explanation = getattr(self.link, "explanation", 
                                   _("this page is no longer available due to a copyright claim."))
        Templated.__init__(self, *a, **kw)

class CommentsPanel(Templated):
    """the side-panel on the reddit toolbar frame that shows the top
       comments of a link"""

    def __init__(self, link = None, listing = None, expanded = False, *a, **kw):
        self.link = link
        self.listing = listing
        self.expanded = expanded

        Templated.__init__(self, *a, **kw)

class CommentVisitsBox(Templated):
    def __init__(self, visits, *a, **kw):
        self.visits = []
        for visit in visits:
            pretty = timesince(visit, precision=60)
            self.visits.append(pretty)
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
    extra_page_classes = ['single-page']

    def __init__(self, link = None, comment = None,
                 link_title = '', subtitle = None, num_duplicates = None,
                 *a, **kw):

        c.permalink_page = True
        expand_children = kw.get("expand_children", not bool(comment))

        wrapper = default_thing_wrapper(expand_children=expand_children)

        # link_listing will be the one-element listing at the top
        self.link_listing = wrap_links(link, wrapper = wrapper)

        # link is a wrapped Link object
        self.link = self.link_listing.things[0]

        link_title = ((self.link.title) if hasattr(self.link, 'title') else '')

        # defaults whether or not there is a comment
        params = {'title':_force_unicode(link_title), 'site' : c.site.name}
        title = strings.link_info_title % params
        short_description = None
        if link and link.selftext:
            short_description = _truncate(link.selftext.strip(), MAX_DESCRIPTION_LENGTH)
        # only modify the title if the comment/author are neither deleted nor spam
        if comment and not comment._deleted and not comment._spam:
            author = Account._byID(comment.author_id, data=True)

            if not author._deleted and not author._spam:
                params = {'author' : author.name, 'title' : _force_unicode(link_title)}
                title = strings.permalink_title % params
                short_description = _truncate(comment.body.strip(), MAX_DESCRIPTION_LENGTH) if comment.body else None
                

        self.subtitle = subtitle

        if hasattr(self.link, "shortlink"):
            self.shortlink = self.link.shortlink

        if hasattr(self.link, "dart_keyword"):
            c.custom_dart_keyword = self.link.dart_keyword

        # if we're already looking at the 'duplicates' page, we can
        # avoid doing this lookup twice
        if num_duplicates is None:
            builder = url_links_builder(self.link.url,
                                        exclude=self.link._fullname)
            self.num_duplicates = len(builder.get_items()[0])
        else:
            self.num_duplicates = num_duplicates

        robots = "noindex,nofollow" if link._deleted else None
        Reddit.__init__(self, title = title, short_description=short_description, robots=robots, *a, **kw)

    def build_toolbars(self):
        base_path = "/%s/%s/" % (self.link._id36, title_to_url(self.link.title))
        base_path = _force_utf8(base_path)


        def info_button(name, **fmt_args):
            return NamedButton(name, dest = '/%s%s' % (name, base_path),
                               aliases = ['/%s/%s' % (name, self.link._id36)],
                               fmt_args = fmt_args)
        buttons = []
        if not getattr(self.link, "disable_comments", False):
            buttons.extend([info_button('comments'),
                            info_button('related')])

            if not self.link.is_self and self.num_duplicates > 0:
                buttons.append(info_button('duplicates', num=self.num_duplicates))

        if c.user_is_admin:
            buttons.append(NamedButton("details", dest="/details/"+self.link._fullname))

        # should we show a traffic tab (promoted and author or sponsor)
        if (self.link.promoted is not None and
            (c.user_is_sponsor or
             (c.user_is_loggedin and c.user._id == self.link.author_id))):
            buttons += [info_button('traffic')]

        toolbar = [NavMenu(buttons, base_path = "", type="tabmenu")]

        if not isinstance(c.site, DefaultSR) and not c.cname:
            toolbar.insert(0, PageNameNav('subreddit'))

        return toolbar

    def content(self):
        title_buttons = getattr(self, "subtitle_buttons", [])
        return self.content_stack((self.infobar, self.link_listing,
                                   PaneStack([PaneStack((self.nav_menu,
                                                         self._content))],
                                             title = self.subtitle,
                                             title_buttons = title_buttons,
                                             css_class = "commentarea")))

    def rightbox(self):
        rb = Reddit.rightbox(self)
        if not (self.link.promoted and not c.user_is_sponsor):
            rb.insert(1, LinkInfoBar(a = self.link))
        return rb

    def page_classes(self):
        classes = Reddit.page_classes(self)

        if c.user_is_loggedin and self.link.author == c.user:
            classes.add("post-submitter")

        time_ago = datetime.datetime.now(g.tz) - self.link._date
        delta = datetime.timedelta
        steps = [
            delta(minutes=10),
            delta(hours=6),
            delta(hours=24),
        ]
        for step in steps:
            if time_ago < step:
                if step < delta(hours=1):
                    step_str = "%dm" % (step.total_seconds() / 60)
                else:
                    step_str = "%dh" % (step.total_seconds() / (60 * 60))
                classes.add("post-under-%s-old" % step_str)

        return classes

class LinkCommentSep(Templated):
    pass

class CommentPane(Templated):
    def cache_key(self):
        num = self.article.num_comments
        # bit of triage: we don't care about 10% changes in comment
        # trees once they get to a certain length.  The cache is only a few
        # min long anyway. 
        if num > 1000:
            num = (num / 100) * 100
        elif num > 100:
            num = (num / 10) * 10
        return "_".join(map(str, ["commentpane", self.article._fullname,
                                  self.article.contest_mode,
                                  num, self.sort, self.num, c.lang,
                                  self.can_reply, c.render_style,
                                  c.user.pref_show_flair,
                                  c.user.pref_show_link_flair]))

    def __init__(self, article, sort, comment, context, num, **kw):
        # keys: lang, num, can_reply, render_style
        # disable: admin

        timer = g.stats.get_timer("service_time.CommentPaneCache")
        timer.start()

        from r2.models import CommentBuilder, NestedListing
        from r2.controllers.reddit_base import UnloggedUser

        self.sort = sort
        self.num = num
        self.article = article

        # don't cache on permalinks or contexts, and keep it to html
        try_cache = not comment and not context and (c.render_style == "html")
        self.can_reply = False
        if c.user_is_admin:
            try_cache = False

        # don't cache if the current user is the author of the link
        if c.user_is_loggedin and c.user._id == article.author_id:
            try_cache = False

        if try_cache and c.user_is_loggedin:
            sr = article.subreddit_slow
            c.can_reply = self.can_reply = sr.can_comment(c.user)
            # don't cache if the current user can ban comments in the listing
            try_cache = not sr.can_ban(c.user)
            # don't cache for users with custom hide threshholds
            try_cache &= (c.user.pref_min_comment_score ==
                         Account._defaults["pref_min_comment_score"])

        def renderer():
            builder = CommentBuilder(article, sort, comment, context, **kw)
            listing = NestedListing(builder, num = num,
                                    parent_name = article._fullname)
            return listing.listing()

        # disable the cache if the user is the author of anything in the
        # thread because of edit buttons etc.
        my_listing = None
        if try_cache and c.user_is_loggedin:
            my_listing = renderer()
            for t in self.listing_iter(my_listing):
                if getattr(t, "is_author", False):
                    try_cache = False
                    break

        timer.intermediate("try_cache")
        cache_hit = False

        if try_cache:
            # try to fetch the comment tree from the cache
            key = self.cache_key()
            self.rendered = g.pagecache.get(key)
            if not self.rendered:
                # spoof an unlogged in user
                user = c.user
                logged_in = c.user_is_loggedin
                try:
                    c.user = UnloggedUser([c.lang])
                    # Preserve the viewing user's flair preferences.
                    c.user.pref_show_flair = user.pref_show_flair
                    c.user.pref_show_link_flair = user.pref_show_link_flair
                    c.user_is_loggedin = False

                    # render as if not logged in (but possibly with reply buttons)
                    self.rendered = renderer().render()
                    g.pagecache.set(
                        key,
                        self.rendered,
                        time=g.commentpane_cache_time
                    )

                finally:
                    # undo the spoofing
                    c.user = user
                    c.user_is_loggedin = logged_in
            else:
                cache_hit = True

            # figure out what needs to be updated on the listing
            if c.user_is_loggedin:
                likes = []
                dislikes = []
                is_friend = set()
                gildings = {}
                saves = set()
                for t in self.listing_iter(my_listing):
                    if not hasattr(t, "likes"):
                        # this is for MoreComments and MoreRecursion
                        continue
                    if getattr(t, "friend", False) and not t.author._deleted:
                        is_friend.add(t.author._fullname)
                    if t.likes:
                        likes.append(t._fullname)
                    if t.likes is False:
                        dislikes.append(t._fullname)
                    if t.user_gilded:
                        gildings[t._fullname] = (t.gilded_message, t.gildings)
                    if t.saved:
                        saves.add(t._fullname)
                self.rendered += ThingUpdater(likes = likes,
                                              dislikes = dislikes,
                                              is_friend = is_friend,
                                              gildings = gildings,
                                              saves = saves).render()
            g.log.debug("using comment page cache")
        else:
            my_listing = my_listing or renderer()
            self.rendered = my_listing.render()

        if try_cache:
            if cache_hit:
                timer.stop("hit")
            else:
                timer.stop("miss")
        else:
            timer.stop("uncached")

    def listing_iter(self, l):
        for t in l:
            yield t
            for x in self.listing_iter(getattr(t, "child", [])):
                yield x

    def render(self, *a, **kw):
        return self.rendered

class ThingUpdater(Templated):
    pass


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
        from r2.lib.menus import menu

        try:
            key = kw.pop("location")
            title = menu[key]
        except KeyError:
            is_moderator = c.user_is_loggedin and \
                c.site.is_moderator(c.user) or c.user_is_admin

            title = (_('subreddit settings') if is_moderator else
                     _('about %(site)s') % dict(site=c.site.name))

        Reddit.__init__(self, title=title, *a, **kw)
    
    def build_toolbars(self):
        if not c.cname:
            return [PageNameNav('subreddit', title=self.title)]
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
                 title = '', loginbox = True, infotext = None, show_interestbar=False,
                 search_params = {}, *a, **kw):
        Reddit.__init__(self, title = title, loginbox = loginbox, infotext = infotext,
                        *a, **kw)
        self.searchbar = SearchBar(prev_search = prev_search,
                                   elapsed_time = elapsed_time,
                                   num_results = num_results,
                                   header = _('search subreddits by name'),
                                   search_params = {},
                                   simple=True,
                                   subreddit_search=True
                                   )
        self.sr_infobar = InfoBar(message = strings.sr_subscribe)

        self.interestbar = InterestBar(True) if show_interestbar else None

    def build_toolbars(self):
        buttons =  [NavButton(menu.popular, ""),
                    NamedButton("new")]
        if c.user_is_admin:
            buttons.append(NamedButton("banned"))

        if c.user_is_loggedin:
            #add the aliases to "my reddits" stays highlighted
            buttons.append(NamedButton("mine",
                                       aliases=['/subreddits/mine/subscriber',
                                                '/subreddits/mine/contributor',
                                                '/subreddits/mine/moderator']))

        return [PageNameNav('subreddits'),
                NavMenu(buttons, base_path = '/subreddits', type="tabmenu")]

    def content(self):
        return self.content_stack((self.interestbar, self.searchbar,
                                   self.nav_menu, self.sr_infobar,
                                   self._content))

    def rightbox(self):
        ps = Reddit.rightbox(self)
        srs = Subreddit.user_subreddits(c.user, ids=False, limit=None)
        srs.sort(key=lambda sr: sr.name.lower())
        subscribe_box = SubscriptionBox(srs,
                                        multi_text=strings.subscribed_multi)
        num_reddits = len(subscribe_box.srs)
        ps.append(SideContentBox(_("your front page subreddits (%s)") %
                                 num_reddits, [subscribe_box]))
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
    extra_page_classes = ['profile-page']

    def __init__(self, user, *a, **kw):
        self.user     = user
        Reddit.__init__(self, *a, **kw)

    def build_toolbars(self):
        path = "/user/%s/" % self.user.name
        main_buttons = [NavButton(menu.overview, '/', aliases = ['/overview']),
                   NamedButton('comments'),
                   NamedButton('submitted')]

        if votes_visible(self.user):
            main_buttons += [NamedButton('liked'),
                        NamedButton('disliked'),
                        NamedButton('hidden')]

        if c.user_is_loggedin and (c.user._id == self.user._id or
                                   c.user_is_admin):
            main_buttons += [NamedButton('saved')]

        if c.user_is_sponsor:
            main_buttons += [NamedButton('promoted')]

        toolbar = [PageNameNav('nomenu', title = self.user.name),
                   NavMenu(main_buttons, base_path = path, type="tabmenu")]

        if c.user_is_admin:
            from admin_pages import AdminProfileMenu
            toolbar.append(AdminProfileMenu(path))

        return toolbar


    def rightbox(self):
        rb = Reddit.rightbox(self)

        tc = TrophyCase(self.user)
        helplink = ( "/wiki/awards", _("what's this?") )
        scb = SideContentBox(title=_("trophy case"),
                 helplink=helplink, content=[tc],
                 extra_class="trophy-area")

        rb.push(scb)

        if c.user_is_admin:
            from admin_pages import AdminSidebar
            rb.push(AdminSidebar(self.user))
        rb.push(ProfileBar(self.user))

        return rb

class TrophyCase(Templated):
    def __init__(self, user):
        self.user = user
        self.trophies = []
        self.invisible_trophies = []
        self.dupe_trophies = []

        award_ids_seen = []

        for trophy in Trophy.by_account(user):
            if trophy._thing2.awardtype == 'invisible':
                self.invisible_trophies.append(trophy)
            elif trophy._thing2_id in award_ids_seen:
                self.dupe_trophies.append(trophy)
            else:
                self.trophies.append(trophy)
                award_ids_seen.append(trophy._thing2_id)

        self.cup_info = user.cup_info()
        Templated.__init__(self)

class ProfileBar(Templated):
    """Draws a right box for info about the user (karma, etc)"""
    def __init__(self, user):
        Templated.__init__(self, user = user)
        self.is_friend = None
        self.my_fullname = None
        self.gold_remaining = None
        running_out_of_gold = False
        self.gold_creddit_message = None

        if c.user_is_loggedin:
            if ((user._id == c.user._id or c.user_is_admin)
                and getattr(user, "gold", None)):
                self.gold_expiration = getattr(user, "gold_expiration", None)
                if self.gold_expiration is None:
                    self.gold_remaining = _("an unknown amount")
                else:
                    gold_days_left = (self.gold_expiration -
                                      datetime.datetime.now(g.tz)).days
                    if gold_days_left < 7:
                        running_out_of_gold = True

                    if gold_days_left < 1:
                        self.gold_remaining = _("less than a day")
                    else:
                        # "X months, Y days" if less than 2 months left, otherwise "X months"
                        precision = 60 * 60 * 24 * 30 if gold_days_left > 60 else 60 * 60 * 24 
                        self.gold_remaining = timeuntil(self.gold_expiration, precision)

                if hasattr(user, "gold_subscr_id"):
                    self.gold_subscr_id = user.gold_subscr_id

            if ((user._id == c.user._id or c.user_is_admin) and
                user.gold_creddits > 0):
                msg = ungettext("%(creddits)s gold creddit to give",
                                "%(creddits)s gold creddits to give",
                                user.gold_creddits)
                msg = msg % dict(creddits=user.gold_creddits)
                self.gold_creddit_message = msg

            if user._id != c.user._id:
                self.goldlink = "/gold?goldtype=gift&recipient=" + user.name
                self.giftmsg = _("give reddit gold to %(user)s to show "
                                 "your appreciation") % {'user': user.name}
            elif running_out_of_gold:
                self.goldlink = "/gold/about"
                self.giftmsg = _("renew your reddit gold")
            elif not c.user.gold:
                self.goldlink = "/gold/about"
                self.giftmsg = _("get extra features and help support reddit "
                                 "with a reddit gold subscription")

            self.my_fullname = c.user._fullname
            self.is_friend = self.user._id in c.user.friends

class MenuArea(Templated):
    """Draws the gray box at the top of a page for sort menus"""
    def __init__(self, menus = []):
        Templated.__init__(self, menus = menus)

class InfoBar(Templated):
    """Draws the yellow box at the top of a page for info"""
    def __init__(self, message = '', extra_class = ''):
        Templated.__init__(self, message = message, extra_class = extra_class)

class WelcomeBar(InfoBar):
    def __init__(self):
        messages = g.live_config.get("welcomebar_messages")
        if messages:
            message = random.choice(messages).split(" / ")
        else:
            message = (_("reddit is a platform for internet communities"),
                       _("where your votes shape what the world is talking about."))
        InfoBar.__init__(self, message=message)

class ClientInfoBar(InfoBar):
    """Draws the message the top of a login page before OAuth2 authorization"""
    def __init__(self, client, *args, **kwargs):
        kwargs.setdefault("extra_class", "client-info")
        InfoBar.__init__(self, *args, **kwargs)
        self.client = client

class SidebarMessage(Templated):
    """An info message box on the sidebar."""
    def __init__(self, message, extra_class=None):
        Templated.__init__(self, message=message, extra_class=extra_class)

class RedditError(BoringPage):
    site_tracking = False
    def __init__(self, title, message, image=None, sr_description=None,
                 explanation=None):
        BoringPage.__init__(self, title, loginbox=False,
                            show_sidebar = False, 
                            content=ErrorPage(title=title,
                                              message=message,
                                              image=image,
                                              sr_description=sr_description,
                                              explanation=explanation))

class ErrorPage(Templated):
    """Wrapper for an error message"""
    def __init__(self, title, message, image=None, explanation=None, **kwargs):
        if not image:
            letter = random.choice(['a', 'b', 'c', 'd', 'e'])
            image = 'reddit404' + letter + '.png'
        # Normalize explanation strings.
        if explanation:
            explanation = explanation.lower().rstrip('.') + '.'
        Templated.__init__(self,
                           title=title,
                           message=message,
                           image_url=image,
                           explanation=explanation,
                           **kwargs)


class Over18(Templated):
    """The creepy 'over 18' check page for nsfw content."""
    pass

class SubredditTopBar(CachedTemplate):

    """The horizontal strip at the top of most pages for navigating
    user-created reddits."""
    def __init__(self):
        self._my_reddits = None
        self._pop_reddits = None
        name = '' if not c.user_is_loggedin else c.user.name
        langs = "" if name else c.content_langs
        # poor man's expiration, with random initial time
        t = int(time.time()) / 3600
        if c.user_is_loggedin:
            t += c.user._id
        CachedTemplate.__init__(self, name = name, langs = langs, t = t,
                               over18 = c.over18)

    @property
    def my_reddits(self):
        if self._my_reddits is None:
            self._my_reddits = Subreddit.user_subreddits(c.user,
                                                         ids=False,
                                                         stale=True)
        return self._my_reddits

    @property
    def pop_reddits(self):
        if self._pop_reddits is None:
            p_srs = Subreddit.default_subreddits(ids = False,
                                                 limit = Subreddit.sr_limit)
            self._pop_reddits = [ sr for sr in p_srs
                                  if sr.name not in g.automatic_reddits ]
        return self._pop_reddits

    @property
    def show_my_reddits_dropdown(self):
        return len(self.my_reddits) > g.sr_dropdown_threshold

    def my_reddits_dropdown(self):
        drop_down_buttons = []
        for sr in sorted(self.my_reddits, key = lambda sr: sr.name.lower()):
            drop_down_buttons.append(SubredditButton(sr))
        drop_down_buttons.append(NavButton(menu.edit_subscriptions,
                                           sr_path = False,
                                           css_class = 'bottom-option',
                                           dest = '/subreddits/'))
        return SubredditMenu(drop_down_buttons,
                             title = _('my subreddits'),
                             type = 'srdrop')

    def subscribed_reddits(self):
        srs = [SubredditButton(sr) for sr in
                        sorted(self.my_reddits,
                               key = lambda sr: sr._downs,
                               reverse=True)
                        if sr.name not in g.automatic_reddits
                        ]
        return NavMenu(srs,
                       type='flatlist', separator = '-',
                       css_class = 'sr-bar')

    def popular_reddits(self, exclude=[]):
        exclusions = set(exclude)
        buttons = [SubredditButton(sr)
                   for sr in self.pop_reddits if sr not in exclusions]

        return NavMenu(buttons,
                       type='flatlist', separator = '-',
                       css_class = 'sr-bar', _id = 'sr-bar')

    def special_reddits(self):
        css_classes = {Random: "random",
                       RandomSubscription: "gold"}
        reddits = [Frontpage, All, Random]
        if getattr(c.site, "over_18", False):
            reddits.append(RandomNSFW)
        if c.user_is_loggedin:
            if c.user.gold:
                reddits.append(RandomSubscription)
            if c.user.friends:
                reddits.append(Friends)
            if c.show_mod_mail:
                reddits.append(Mod)
        return NavMenu([SubredditButton(sr, css_class=css_classes.get(sr))
                        for sr in reddits],
                       type = 'flatlist', separator = '-',
                       css_class = 'sr-bar')
    
    def sr_bar (self):
        sep = '<span class="separator">&nbsp;|&nbsp;</span>'
        menus = []
        menus.append(self.special_reddits())
        menus.append(RawString(sep))


        if not c.user_is_loggedin:
            menus.append(self.popular_reddits())
        else:
            menus.append(self.subscribed_reddits())
            sep = '<span class="separator">&nbsp;&ndash;&nbsp;</span>'
            menus.append(RawString(sep))

            menus.append(self.popular_reddits(exclude=self.my_reddits))

        return menus

class SubscriptionBox(Templated):
    """The list of reddits a user is currently subscribed to to go in
    the right pane."""
    def __init__(self, srs, multi_text=None):
        self.srs = srs
        self.goldlink = None
        self.goldmsg = None
        self.prelink = None
        self.multi_path = None
        self.multi_text = multi_text

        # Construct MultiReddit path
        if multi_text:
            self.multi_path = '/r/' + '+'.join([sr.name for sr in srs])

        if len(srs) > Subreddit.sr_limit and c.user_is_loggedin:
            if not c.user.gold:
                self.goldlink = "/gold"
                self.goldmsg = _("raise it to %s") % Subreddit.gold_limit
                self.prelink = ["/wiki/faq#wiki_how_many_subreddits_can_i_subscribe_to.3F",
                                _("%s visible") % Subreddit.sr_limit]
            else:
                self.goldlink = "/gold/about"
                extra = min(len(srs) - Subreddit.sr_limit,
                            Subreddit.gold_limit - Subreddit.sr_limit)
                visible = min(len(srs), Subreddit.gold_limit)
                bonus = {"bonus": extra}
                self.goldmsg = _("%(bonus)s bonus subreddits") % bonus
                self.prelink = ["/wiki/faq#wiki_how_many_subreddits_can_i_subscribe_to.3F",
                                _("%s visible") % visible]

        Templated.__init__(self, srs=srs, goldlink=self.goldlink,
                           goldmsg=self.goldmsg)

    @property
    def reddits(self):
        return wrap_links(self.srs)


class AllInfoBar(Templated):
    def __init__(self, site, user):
        self.sr = site
        self.allminus_url = None
        self.css_class = None
        if isinstance(site, AllMinus) and c.user.gold:
            self.description = (strings.r_all_minus_description + "\n\n" +
                                " ".join("/r/" + sr.name for sr in site.srs))
            self.css_class = "gold-accent"
        else:
            self.description = strings.r_all_description
            sr_ids = Subreddit.user_subreddits(user)
            srs = Subreddit._byID(sr_ids, data=True, return_dict=False)
            if srs:
                self.allminus_url = '/r/all-' + '-'.join([sr.name for sr in srs])

        self.gilding_listing = False
        if request.path.startswith("/comments/gilded"):
            self.gilding_listing = True

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

class SubredditStylesheetSource(Templated):
    """A view of the unminified source of a subreddit's stylesheet."""
    def __init__(self, stylesheet_contents):
        Templated.__init__(self, stylesheet_contents=stylesheet_contents)

class CssError(Templated):
    """Rendered error returned to the stylesheet editing page via ajax"""
    def __init__(self, error):
        # error is an instance of cssutils.py:ValidationError
        Templated.__init__(self, error = error)

class UploadedImage(Templated):
    "The page rendered in the iframe during an upload of a header image"
    def __init__(self,status,img_src, name="", errors = {}, form_id = ""):
        self.errors = list(errors.iteritems())
        Templated.__init__(self, status=status, img_src=img_src, name = name,
                           form_id = form_id)

class Thanks(Templated):
    """The page to claim reddit gold trophies"""
    def __init__(self, secret=None):
        if secret and secret.startswith("cr_"):
            status = "creddits"
        elif g.cache.get("recent-gold-" + c.user.name):
            status = "recent"
        elif c.user.gold:
            status = "gold"
        else:
            status = "mundane"

        Templated.__init__(self, status=status, secret=secret)

class GoldThanks(Templated):
    """An actual 'Thanks for buying gold!' landing page"""
    pass

class Gold(Templated):
    def __init__(self, goldtype, period, months, signed,
                 recipient, recipient_name):

        if c.user_is_admin:
            user_creddits = 50
        else:
            user_creddits = c.user.gold_creddits

        Templated.__init__(self, goldtype = goldtype, period = period,
                           months = months, signed = signed,
                           recipient_name = recipient_name,
                           user_creddits = user_creddits,
                           bad_recipient =
                           bool(recipient_name and not recipient))


class GoldPayment(Templated):
    def __init__(self, goldtype, period, months, signed,
                 recipient, giftmessage, passthrough, comment,
                 clone_template=False):
        pay_from_creddits = False

        if period == "monthly" or 1 <= months < 12:
            unit_price = g.gold_month_price
            if period == 'monthly':
                price = unit_price
            else:
                price = unit_price * months
        else:
            unit_price = g.gold_year_price
            if period == 'yearly':
                price = unit_price
            else:
                years = months / 12
                price = unit_price * years

        if c.user_is_admin:
            user_creddits = 50
        else:
            user_creddits = c.user.gold_creddits

        if goldtype == "autorenew":
            summary = strings.gold_summary_autorenew % dict(user=c.user.name)
            if period == "monthly":
                paypal_buttonid = g.PAYPAL_BUTTONID_AUTORENEW_BYMONTH
            elif period == "yearly":
                paypal_buttonid = g.PAYPAL_BUTTONID_AUTORENEW_BYYEAR

            quantity = None
            google_id = None
            stripe_key = None
            coinbase_button_id = None

        elif goldtype == "onetime":
            if months < 12:
                paypal_buttonid = g.PAYPAL_BUTTONID_ONETIME_BYMONTH
                quantity = months
                coinbase_name = 'COINBASE_BUTTONID_ONETIME_%sMO' % quantity
                coinbase_button_id = getattr(g, coinbase_name, None)
            else:
                paypal_buttonid = g.PAYPAL_BUTTONID_ONETIME_BYYEAR
                quantity = months / 12
                months = quantity * 12
                coinbase_name = 'COINBASE_BUTTONID_ONETIME_%sYR' % quantity
                coinbase_button_id = getattr(g, coinbase_name, None)

            summary = strings.gold_summary_onetime % dict(user=c.user.name,
                                     amount=Score.somethings(months, "month"))

            google_id = g.GOOGLE_ID
            stripe_key = g.STRIPE_PUBLIC_KEY

        else:
            if months < 12:
                paypal_buttonid = g.PAYPAL_BUTTONID_CREDDITS_BYMONTH
                quantity = months
                coinbase_name = 'COINBASE_BUTTONID_ONETIME_%sMO' % quantity
                coinbase_button_id = getattr(g, coinbase_name, None)
            else:
                paypal_buttonid = g.PAYPAL_BUTTONID_CREDDITS_BYYEAR
                quantity = months / 12
                coinbase_name = 'COINBASE_BUTTONID_ONETIME_%sYR' % quantity
                coinbase_button_id = getattr(g, coinbase_name, None)

            if goldtype == "creddits":
                summary = strings.gold_summary_creddits % dict(
                          amount=Score.somethings(months, "month"))
            elif goldtype == "gift":
                if clone_template:
                    format = strings.gold_summary_comment_gift
                elif comment:
                    format = strings.gold_summary_comment_page
                elif signed:
                    format = strings.gold_summary_signed_gift
                else:
                    format = strings.gold_summary_anonymous_gift

                if months <= user_creddits:
                    pay_from_creddits = True
                elif months >= 12:
                    # If you're not paying with creddits, you have to either
                    # buy by month or spend a multiple of 12 months
                    months = quantity * 12

                if not clone_template:
                    summary = format % dict(
                        amount=Score.somethings(months, "month"),
                        recipient=recipient and
                                  recipient.name.replace('_', '&#95;'),
                    )
                else:
                    # leave the replacements to javascript
                    summary = format
            else:
                raise ValueError("wtf is %r" % goldtype)

            google_id = g.GOOGLE_ID
            stripe_key = g.STRIPE_PUBLIC_KEY

        Templated.__init__(self, goldtype=goldtype, period=period,
                           months=months, quantity=quantity,
                           unit_price=unit_price, price=price,
                           summary=summary, giftmessage=giftmessage,
                           pay_from_creddits=pay_from_creddits,
                           passthrough=passthrough,
                           google_id=google_id,
                           comment=comment, clone_template=clone_template,
                           paypal_buttonid=paypal_buttonid,
                           stripe_key=stripe_key,
                           coinbase_button_id=coinbase_button_id)


class CreditGild(Templated):
    """Page for credit card payments for comment gilding."""
    pass


class GiftGold(Templated):
    """The page to gift reddit gold trophies"""
    def __init__(self, recipient):
        if c.user_is_admin:
            gold_creddits = 500
        else:
            gold_creddits = c.user.gold_creddits
        Templated.__init__(self, recipient=recipient, gold_creddits=gold_creddits)

class Password(Templated):
    """Form encountered when 'recover password' is clicked in the LoginFormWide."""
    def __init__(self, success=False):
        Templated.__init__(self, success = success)

class PasswordReset(Templated):
    """Template for generating an email to the user who wishes to
    reset their password (step 2 of password recovery, after they have
    entered their user name in Password.)"""
    pass

class VerifyEmail(Templated):
    pass

class Promo_Email(Templated):
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
                 title="", title_buttons = []):
        div = div or div_id or css_class or False
        self.div_id    = div_id
        self.css_class = css_class
        self.div       = div
        self.stack     = list(panes)
        self.title = title
        self.title_buttons = title_buttons
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
    def __init__(self, prev_search='', search_params={}, site=None,
                 simple=True, restrict_sr=False, subreddit_search=False,
                 syntax=None):
        Templated.__init__(self, prev_search=prev_search,
                           search_params=search_params, site=site,
                           simple=simple, restrict_sr=restrict_sr,
                           subreddit_search=subreddit_search, syntax=syntax)


class SearchBar(Templated):
    """More detailed search box for /search and /subreddits pages.
    Displays the previous search as well as info of the elapsed_time
    and num_results if any."""
    def __init__(self, header=None, num_results=0, prev_search='',
                 elapsed_time=0, search_params={}, show_feedback=False,
                 simple=False, restrict_sr=False, site=None, syntax=None,
                 subreddit_search=False, converted_data=None, facets={}, 
                 sort=None, recent=None, **kw):
        if header is None:
            header = _("previous search")
        self.header = header

        self.prev_search  = prev_search
        self.elapsed_time = elapsed_time
        self.show_feedback = show_feedback

        # All results are approximate unless there are fewer than 10.
        if num_results > 10:
            self.num_results = (num_results / 10) * 10
        else:
            self.num_results = num_results

        Templated.__init__(self, search_params=search_params,
                           simple=simple, restrict_sr=restrict_sr,
                           site=site, syntax=syntax,
                           converted_data=converted_data,
                           subreddit_search=subreddit_search, facets=facets,
                           sort=sort, recent=recent)

class Frame(Wrapped):
    """Frameset for the FrameToolbar used when a user hits /tb/. The
    top 30px of the page are dedicated to the toolbar, while the rest
    of the page will show the results of following the link."""
    def __init__(self, url='', title='', fullname=None, thumbnail=None):
        if title:
            title = (_('%(site_title)s via %(domain)s')
                     % dict(site_title = _force_unicode(title),
                            domain     = g.domain))
        else:
            title = g.domain
        Wrapped.__init__(self, url = url, title = title,
                           fullname = fullname, thumbnail = thumbnail)

class FrameToolbar(Wrapped):
    """The reddit voting toolbar used together with Frame."""

    cachable = True
    extension_handling = False
    cache_ignore = Link.cache_ignore
    site_tracking = True
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

    def page_classes(self):
        return ("toolbar",)


class NewLink(Templated):
    """Render the link submission form"""
    def __init__(self, captcha = None, url = '', title= '', text = '', selftext = '',
                 subreddits = (), then = 'comments', resubmit=False, never_show_self=False):

        self.show_link = self.show_self = False

        tabs = []
        if c.default_sr or c.site.link_type != 'self':
            tabs.append(('link', ('link-desc', 'url-field')))
            self.show_link = True
        if c.default_sr or c.site.link_type != 'link':
            tabs.append(('text', ('text-desc', 'text-field')))
            self.show_self = not never_show_self

        if self.show_self and self.show_link:
            all_fields = set(chain(*(parts for (tab, parts) in tabs)))
            buttons = []
            
            if selftext == 'true' or text != '':
                self.default_tab = tabs[1][0]
            else:
                self.default_tab = tabs[0][0]

            for tab_name, parts in tabs:
                to_show = ','.join('#' + p for p in parts)
                to_hide = ','.join('#' + p for p in all_fields if p not in parts)
                onclick = "return select_form_tab(this, '%s', '%s');"
                onclick = onclick % (to_show, to_hide)
                if tab_name == self.default_tab:
                    self.default_show = to_show
                    self.default_hide = to_hide

                buttons.append(JsButton(tab_name, onclick=onclick, css_class=tab_name + "-button"))

            self.formtabs_menu = JsNavMenu(buttons, type = 'formtab')

        self.sr_searches = simplejson.dumps(popular_searches(include_over_18=c.over18))

        self.resubmit = resubmit
        if c.default_sr:
            self.default_sr = None
        else:
            self.default_sr = c.site

        Templated.__init__(self, captcha = captcha, url = url,
                         title = title, text = text, subreddits = subreddits,
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


class Button(Wrapped):
    cachable = True
    extension_handling = False
    def __init__(self, link, **kw):
        Wrapped.__init__(self, link, **kw)
        if link is None:
            self.title = ""
            self.add_props(c.user, [self])


    @classmethod
    def add_props(cls, user, wrapped):
        # unlike most wrappers we can guarantee that there is a link
        # that this wrapper is wrapping.
        Link.add_props(user, [w for w in wrapped if hasattr(w, "_fullname")])
        for w in wrapped:
            # caching: store the user name since each button has a modhash
            w.user_name = c.user.name if c.user_is_loggedin else ""
            if not hasattr(w, '_fullname'):
                w._fullname = None

    def render(self, *a, **kw):
        res = Wrapped.render(self, *a, **kw)
        return responsive(res, True)

class ButtonLite(Button):
    def render(self, *a, **kw):
        return Wrapped.render(self, *a, **kw)

class ButtonDemoPanel(Templated):
    """The page for showing the different styles of embedable voting buttons"""
    pass

class SelfServeBlurb(Templated):
    pass

class FeedbackBlurb(Templated):
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


class UserAwards(Templated):
    """For drawing the regular-user awards page."""
    def __init__(self):
        from r2.models import Award, Trophy
        Templated.__init__(self)

        self.regular_winners = []
        self.manuals = []
        self.invisibles = []

        for award in Award._all_awards():
            if award.awardtype == 'regular':
                trophies = Trophy.by_award(award)
                # Don't show awards that nobody's ever won
                # (e.g., "9-Year Club")
                if trophies:
                    winner = trophies[0]._thing1.name
                    self.regular_winners.append( (award, winner, trophies[0]) )
            elif award.awardtype == 'manual':
                self.manuals.append(award)
            elif award.awardtype == 'invisible':
                self.invisibles.append(award)
            else:
                raise NotImplementedError

class AdminErrorLog(Templated):
    """The admin page for viewing the error log"""
    def __init__(self):
        hcb = g.hardcache.backend

        date_groupings = {}
        hexkeys_seen = {}

        idses = hcb.ids_by_category("error", limit=5000)
        errors = g.hardcache.get_multi(prefix="error-", keys=idses)

        for ids in idses:
            date, hexkey = ids.split("-")

            hexkeys_seen[hexkey] = True

            d = errors.get(ids, None)

            if d is None:
                log_text("error=None", "Why is error-%s None?" % ids,
                         "warning")
                continue

            tpl = (d.get('times_seen', 1), hexkey, d)
            date_groupings.setdefault(date, []).append(tpl)

        self.nicknames = {}
        self.statuses = {}

        nicks = g.hardcache.get_multi(prefix="error_nickname-",
                                      keys=hexkeys_seen.keys())
        stati = g.hardcache.get_multi(prefix="error_status-",
                                      keys=hexkeys_seen.keys())

        for hexkey in hexkeys_seen.keys():
            self.nicknames[hexkey] = nicks.get(hexkey, "???")
            self.statuses[hexkey] = stati.get(hexkey, "normal")

        idses = hcb.ids_by_category("logtext")
        texts = g.hardcache.get_multi(prefix="logtext-", keys=idses)

        for ids in idses:
            date, level, classification = ids.split("-", 2)
            textoccs = []
            dicts = texts.get(ids, None)
            if dicts is None:
                log_text("logtext=None", "Why is logtext-%s None?" % ids,
                         "warning")
                continue
            for d in dicts:
                textoccs.append( (d['text'], d['occ'] ) )

            sort_order = {
                'error': -1,
                'warning': -2,
                'info': -3,
                'debug': -4,
                }[level]

            tpl = (sort_order, level, classification, textoccs)
            date_groupings.setdefault(date, []).append(tpl)

        self.date_summaries = []

        for date in sorted(date_groupings.keys(), reverse=True):
            groupings = sorted(date_groupings[date], reverse=True)
            self.date_summaries.append( (date, groupings) )

        Templated.__init__(self)

class AdminAwards(Templated):
    """The admin page for editing awards"""
    def __init__(self):
        from r2.models import Award
        Templated.__init__(self)
        self.awards = Award._all_awards()

class AdminAwardGive(Templated):
    """The interface for giving an award"""
    def __init__(self, award, recipient='', desc='', url='', hours=''):
        now = datetime.datetime.now(g.display_tz)
        if desc:
            self.description = desc
        elif award.awardtype == 'regular':
            self.description = "??? -- " + now.strftime("%Y-%m-%d")
        else:
            self.description = ""
        self.url = url
        self.recipient = recipient
        self.hours = hours

        Templated.__init__(self, award = award)

class AdminAwardWinners(Templated):
    """The list of winners of an award"""
    def __init__(self, award):
        trophies = Trophy.by_award(award)
        Templated.__init__(self, award = award, trophies = trophies)


class Ads(Templated):
    def __init__(self):
        Templated.__init__(self)
        self.ad_url = g.ad_domain + "/ads/"
        self.frame_id = "ad-frame"


class Embed(Templated):
    """wrapper for embedding /help into reddit as if it were not on a separate wiki."""
    def __init__(self,content = ''):
        Templated.__init__(self, content = content)


def wrapped_flair(user, subreddit, force_show_flair):
    if (not hasattr(subreddit, '_id')
        or not (force_show_flair or getattr(subreddit, 'flair_enabled', True))):
        return False, 'right', '', ''

    get_flair_attr = lambda a, default=None: getattr(
        user, 'flair_%s_%s' % (subreddit._id, a), default)

    return (get_flair_attr('enabled', default=True),
            getattr(subreddit, 'flair_position', 'right'),
            get_flair_attr('text'), get_flair_attr('css_class'))

class WrappedUser(CachedTemplate):
    FLAIR_CSS_PREFIX = 'flair-'

    def __init__(self, user, attribs = [], context_thing = None, gray = False,
                 subreddit = None, force_show_flair = None,
                 flair_template = None, flair_text_editable = False,
                 include_flair_selector = False):
        if not subreddit:
            subreddit = c.site

        attribs.sort()
        author_cls = 'author'

        author_title = ''
        if gray:
            author_cls += ' gray'
        for tup in attribs:
            author_cls += " " + tup[2]
            # Hack: '(' should be in tup[3] iff this friend has a note
            if tup[1] == 'F' and '(' in tup[3]:
                author_title = tup[3]

        flair = wrapped_flair(user, subreddit or c.site, force_show_flair)
        flair_enabled, flair_position, flair_text, flair_css_class = flair
        has_flair = bool(
            c.user.pref_show_flair and (flair_text or flair_css_class))

        if flair_template:
            flair_template_id = flair_template._id
            flair_text = flair_template.text
            flair_css_class = flair_template.css_class
            has_flair = True
        else:
            flair_template_id = None

        if flair_css_class:
            # This is actually a list of CSS class *suffixes*. E.g., "a b c"
            # should expand to "flair-a flair-b flair-c".
            flair_css_class = ' '.join(self.FLAIR_CSS_PREFIX + c
                                       for c in flair_css_class.split())

        if include_flair_selector:
            if (not getattr(c.site, 'flair_self_assign_enabled', True)
                and not (c.user_is_admin
                         or c.site.is_moderator_with_perms(c.user, 'flair'))):
                include_flair_selector = False

        target = None
        ip_span = None
        context_deleted = None
        if context_thing:
            target = getattr(context_thing, 'target', None)
            ip_span = getattr(context_thing, 'ip_span', None)
            context_deleted = context_thing.deleted

        karma = ''
        if c.user_is_admin:
            karma = ' (%d)' % user.link_karma

        CachedTemplate.__init__(self,
                                name = user.name,
                                force_show_flair = force_show_flair,
                                has_flair = has_flair,
                                flair_enabled = flair_enabled,
                                flair_position = flair_position,
                                flair_text = flair_text,
                                flair_text_editable = flair_text_editable,
                                flair_css_class = flair_css_class,
                                flair_template_id = flair_template_id,
                                include_flair_selector = include_flair_selector,
                                author_cls = author_cls,
                                author_title = author_title,
                                attribs = attribs,
                                context_thing = context_thing,
                                karma = karma,
                                ip_span = ip_span,
                                context_deleted = context_deleted,
                                fullname = user._fullname,
                                user_deleted = user._deleted)

# Classes for dealing with friend/moderator/contributor/banned lists


class UserTableItem(Templated):
    """A single row in a UserList of type 'type' and of name
    'container_name' for a given user.  The provided list of 'cells'
    will determine what order the different columns are rendered in."""
    def __init__(self, user, type, cellnames, container_name, editable,
                 remove_action, rel=None):
        self.user = user
        self.type = type
        self.cells = cellnames
        self.rel = rel
        self.container_name = container_name
        self.editable       = editable
        self.remove_action  = remove_action
        Templated.__init__(self)

    def __repr__(self):
        return '<UserTableItem "%s">' % self.user.name

class FlairPane(Templated):
    def __init__(self, num, after, reverse, name, user):
        # Make sure c.site isn't stale before rendering.
        c.site = Subreddit._byID(c.site._id)

        tabs = [
            ('grant', _('grant flair'), FlairList(num, after, reverse, name,
                                                  user)),
            ('templates', _('user flair templates'),
             FlairTemplateList(USER_FLAIR)),
            ('link_templates', _('link flair templates'),
             FlairTemplateList(LINK_FLAIR)),
        ]

        Templated.__init__(
            self,
            tabs=TabbedPane(tabs, linkable=True),
            flair_enabled=c.site.flair_enabled,
            flair_position=c.site.flair_position,
            link_flair_position=c.site.link_flair_position,
            flair_self_assign_enabled=c.site.flair_self_assign_enabled,
            link_flair_self_assign_enabled=
                c.site.link_flair_self_assign_enabled)

class FlairList(Templated):
    """List of users who are tagged with flair within a subreddit."""

    def __init__(self, num, after, reverse, name, user):
        Templated.__init__(self, num=num, after=after, reverse=reverse,
                           name=name, user=user)

    @property
    def flair(self):
        if self.user:
            return [FlairListRow(self.user)]

        if self.name:
            # user lookup was requested, but no user was found, so abort
            return []

        # Fetch one item more than the limit, so we can tell if we need to link
        # to a "next" page.
        query = Flair.flair_id_query(c.site, self.num + 1, self.after,
                                     self.reverse)
        flair_rows = list(query)
        if len(flair_rows) > self.num:
            next_page = flair_rows.pop()
        else:
            next_page = None
        uids = [row._thing2_id for row in flair_rows]
        users = Account._byID(uids, data=True)
        result = [FlairListRow(users[row._thing2_id])
                  for row in flair_rows if row._thing2_id in users]
        links = []
        if self.after:
            links.append(
                FlairNextLink(result[0].user._fullname,
                              reverse=not self.reverse,
                              needs_border=bool(next_page)))
        if next_page:
            links.append(
                FlairNextLink(result[-1].user._fullname, reverse=self.reverse))
        if self.reverse:
            result.reverse()
            links.reverse()
            if len(links) == 2 and links[1].needs_border:
                # if page was rendered after clicking "prev", we need to move
                # the border to the other link.
                links[0].needs_border = True
                links[1].needs_border = False
        return result + links

class FlairListRow(Templated):
    def __init__(self, user):
        get_flair_attr = lambda a: getattr(user,
                                           'flair_%s_%s' % (c.site._id, a), '')
        Templated.__init__(self, user=user,
                           flair_text=get_flair_attr('text'),
                           flair_css_class=get_flair_attr('css_class'))

class FlairNextLink(Templated):
    def __init__(self, after, reverse=False, needs_border=False):
        Templated.__init__(self, after=after, reverse=reverse,
                           needs_border=needs_border)

class FlairCsv(Templated):
    class LineResult:
        def __init__(self):
            self.errors = {}
            self.warnings = {}
            self.status = 'skipped'
            self.ok = False

        def error(self, field, desc):
            self.errors[field] = desc

        def warn(self, field, desc):
            self.warnings[field] = desc

    def __init__(self):
        Templated.__init__(self, results_by_line=[])

    def add_line(self):
        self.results_by_line.append(self.LineResult())
        return self.results_by_line[-1]

class FlairTemplateList(Templated):
    def __init__(self, flair_type):
        Templated.__init__(self, flair_type=flair_type)

    @property
    def templates(self):
        ids = FlairTemplateBySubredditIndex.get_template_ids(
                c.site._id, flair_type=self.flair_type)
        fts = FlairTemplate._byID(ids)
        return [FlairTemplateEditor(fts[i], self.flair_type) for i in ids]

class FlairTemplateEditor(Templated):
    def __init__(self, flair_template, flair_type):
        Templated.__init__(self,
                           id=flair_template._id,
                           text=flair_template.text,
                           css_class=flair_template.css_class,
                           text_editable=flair_template.text_editable,
                           sample=FlairTemplateSample(flair_template,
                                                      flair_type),
                           position=getattr(c.site, 'flair_position', 'right'),
                           flair_type=flair_type)

    def render(self, *a, **kw):
        res = Templated.render(self, *a, **kw)
        if not g.template_debug:
            res = spaceCompress(res)
        return res

class FlairTemplateSample(Templated):
    """Like a read-only version of FlairTemplateEditor."""
    def __init__(self, flair_template, flair_type):
        if flair_type == USER_FLAIR:
            wrapped_user = WrappedUser(c.user, subreddit=c.site,
                                       force_show_flair=True,
                                       flair_template=flair_template)
        else:
            wrapped_user = None
        Templated.__init__(self,
                           flair_template=flair_template,
                           wrapped_user=wrapped_user, flair_type=flair_type)

class FlairPrefs(CachedTemplate):
    def __init__(self):
        sr_flair_enabled = getattr(c.site, 'flair_enabled', False)
        user_flair_enabled = getattr(c.user, 'flair_%s_enabled' % c.site._id,
                                     True)
        sr_flair_self_assign_enabled = getattr(
            c.site, 'flair_self_assign_enabled', True)
        wrapped_user = WrappedUser(c.user, subreddit=c.site,
                                   force_show_flair=True,
                                   include_flair_selector=True)
        CachedTemplate.__init__(
            self,
            sr_flair_enabled=sr_flair_enabled,
            sr_flair_self_assign_enabled=sr_flair_self_assign_enabled,
            user_flair_enabled=user_flair_enabled,
            wrapped_user=wrapped_user)

class FlairSelectorLinkSample(CachedTemplate):
    def __init__(self, link, site, flair_template):
        flair_position = getattr(site, 'link_flair_position', 'right')
        admin = bool(c.user_is_admin
                     or site.is_moderator_with_perms(c.user, 'flair'))
        CachedTemplate.__init__(
            self,
            title=link.title,
            flair_position=flair_position,
            flair_template_id=flair_template._id,
            flair_text=flair_template.text,
            flair_css_class=flair_template.css_class,
            flair_text_editable=admin or flair_template.text_editable,
            )

class FlairSelector(CachedTemplate):
    """Provide user with flair options according to subreddit settings."""
    def __init__(self, user=None, link=None, site=None):
        if user is None:
            user = c.user
        if site is None:
            site = c.site
        admin = bool(c.user_is_admin
                     or site.is_moderator_with_perms(c.user, 'flair'))

        if link:
            flair_type = LINK_FLAIR
            target = link
            target_name = link._fullname
            attr_pattern = 'flair_%s'
            position = getattr(site, 'link_flair_position', 'right')
            target_wrapper = (
                lambda flair_template: FlairSelectorLinkSample(
                    link, site, flair_template))
            self_assign_enabled = (
                c.user._id == link.author_id
                and site.link_flair_self_assign_enabled)
        else:
            flair_type = USER_FLAIR
            target = user
            target_name = user.name
            position = getattr(site, 'flair_position', 'right')
            attr_pattern = 'flair_%s_%%s' % c.site._id
            target_wrapper = (
                lambda flair_template: WrappedUser(
                    user, subreddit=site, force_show_flair=True,
                    flair_template=flair_template,
                    flair_text_editable=admin or template.text_editable))
            self_assign_enabled = site.flair_self_assign_enabled

        text = getattr(target, attr_pattern % 'text', '')
        css_class = getattr(target, attr_pattern % 'css_class', '')
        templates, matching_template = self._get_templates(
                site, flair_type, text, css_class)

        if self_assign_enabled or admin:
            choices = [target_wrapper(template) for template in templates]
        else:
            choices = []

        # If one of the templates is already selected, modify its text to match
        # the user's current flair.
        if matching_template:
            for choice in choices:
                if choice.flair_template_id == matching_template:
                    if choice.flair_text_editable:
                        choice.flair_text = text
                    break

        Templated.__init__(self, text=text, css_class=css_class,
                           position=position, choices=choices,
                           matching_template=matching_template,
                           target_name=target_name)

    def _get_templates(self, site, flair_type, text, css_class):
        ids = FlairTemplateBySubredditIndex.get_template_ids(
            site._id, flair_type)
        template_dict = FlairTemplate._byID(ids)
        templates = [template_dict[i] for i in ids]
        for template in templates:
            if template.covers((text, css_class)):
                matching_template = template._id
                break
        else:
             matching_template = None
        return templates, matching_template


class UserList(Templated):
    """base class for generating a list of users"""
    form_title     = ''
    table_title    = ''
    table_headers  = None
    type           = ''
    container_name = ''
    cells          = ('user', 'sendmessage', 'remove')
    _class         = ""
    destination    = "friend"
    remove_action  = "unfriend"

    def __init__(self, editable=True, addable=None):
        self.editable = editable
        if addable is None:
            addable = editable
        self.addable = addable
        Templated.__init__(self)

    def user_row(self, row_type, user, editable=True):
        """Convenience method for constructing a UserTableItem
        instance of the user with type, container_name, etc. of this
        UserList instance"""
        return UserTableItem(user, row_type, self.cells, self.container_name,
                             editable, self.remove_action)

    def _user_rows(self, row_type, uids, editable_fn=None):
        """Generates a UserTableItem wrapped list of the Account
        objects which should be present in this UserList."""

        if uids:
            users = Account._byID(uids, True, return_dict = False)
            rows = []
            for u in users:
                if not u._deleted:
                    editable = editable_fn(u) if editable_fn else self.editable
                    rows.append(self.user_row(row_type, u, editable))
            return rows
        else:
            return []

    @property
    def user_rows(self):
        return self._user_rows(self.type, self.user_ids())

    def user_ids(self):
        """virtual method for fetching the list of ids of the Accounts
        to be listing in this UserList instance"""
        raise NotImplementedError

    @property
    def container_name(self):
        return c.site._fullname

    def executed_message(self, row_type):
        return _("added")


class FriendList(UserList):
    """Friend list on /pref/friends"""
    type = 'friend'

    def __init__(self, editable = True):
        if c.user.gold:
            self.friend_rels = c.user.friend_rels()
            self.cells = ('user', 'sendmessage', 'note', 'age', 'remove')
            self._class = "gold-accent rounded"
            self.table_headers = (_('user'), '', _('note'), _('friendship'), '')

        UserList.__init__(self)

    @property
    def form_title(self):
        return _('add a friend')

    @property
    def table_title(self):
        return _('your friends')

    def user_ids(self):
        return c.user.friends

    def user_row(self, row_type, user, editable=True):
        if not getattr(self, "friend_rels", None):
            return UserList.user_row(self, row_type, user, editable)
        else:
            rel = self.friend_rels[user._id]
            return UserTableItem(user, row_type, self.cells, self.container_name,
                                 editable, self.remove_action, rel)

    @property
    def container_name(self):
        return c.user._fullname


class EnemyList(UserList):
    """Blacklist on /pref/friends"""
    type = 'enemy'
    cells = ('user', 'remove')
    
    def __init__(self, editable=True, addable=False):
        UserList.__init__(self, editable, addable)

    @property
    def table_title(self):
        return _('blocked users')

    def user_ids(self):
        return c.user.enemies

    @property
    def container_name(self):
        return c.user._fullname


class ContributorList(UserList):
    """Contributor list on a restricted/private reddit."""
    type = 'contributor'

    @property
    def form_title(self):
        return _("add approved submitter")

    @property
    def table_title(self):
        return _("approved submitters for %(reddit)s") % dict(reddit = c.site.name)

    def user_ids(self):
        if c.site.name == g.lounge_reddit:
            return [] # /r/lounge has too many subscribers to load without timing out,
                      # and besides, some people might not want this list to be so
                      # easily accessible.
        else:
            return c.site.contributors

class ModList(UserList):
    """Moderator list for a reddit."""
    type = 'moderator'
    invite_type = 'moderator_invite'
    invite_action = 'accept_moderator_invite'
    form_title = _('add moderator')
    invite_form_title = _('invite moderator')
    remove_self_title = _('you are a moderator of this subreddit. %(action)s')

    def __init__(self, editable=True):
        super(ModList, self).__init__(editable=editable)
        self.perms_by_type = {
            self.type: c.site.moderators_with_perms(),
            self.invite_type: c.site.moderator_invites_with_perms(),
        }
        self.cells = ('user', 'permissions', 'permissionsctl')
        if editable:
            self.cells += ('remove',)

    @property
    def table_title(self):
        return _("moderators of /r/%(reddit)s") % {"reddit": c.site.name}

    def executed_message(self, row_type):
        if row_type == "moderator_invite":
            return _("invited")
        else:
            return _("added")

    @property
    def can_force_add(self):
        return c.user_is_admin

    @property
    def can_remove_self(self):
        return c.user_is_loggedin and c.site.is_moderator(c.user)

    @property
    def has_invite(self):
        return c.user_is_loggedin and c.site.is_moderator_invite(c.user)

    def moderator_editable(self, user, row_type):
        if not c.user_is_loggedin:
            return False
        elif c.user_is_admin:
            return True
        elif row_type == self.type:
            return c.user != user and c.site.can_demod(c.user, user)
        elif row_type == self.invite_type:
            return c.site.is_unlimited_moderator(c.user)
        else:
            return False

    def user_row(self, row_type, user, editable=True):
        perms = ModeratorPermissions(
            user, row_type, self.perms_by_type[row_type].get(user._id),
            editable=editable)
        return UserTableItem(user, row_type, self.cells, self.container_name,
                             editable, self.remove_action, rel=perms)

    @property
    def user_rows(self):
        return self._user_rows(
            self.type, self.user_ids(),
            lambda u: self.moderator_editable(u, self.type))

    @property
    def invited_user_rows(self):
        return self._user_rows(
            self.invite_type, self.invited_user_ids(),
            lambda u: self.moderator_editable(u, self.invite_type))

    def _sort_user_ids(self, row_type):
        for user_id, perms in self.perms_by_type[row_type].iteritems():
            if perms is None:
                yield user_id
        for user_id, perms in self.perms_by_type[row_type].iteritems():
            if perms is not None:
                yield user_id

    def user_ids(self):
        return list(self._sort_user_ids(self.type))

    def invited_user_ids(self):
        return list(self._sort_user_ids(self.invite_type))

class BannedList(UserList):
    """List of users banned from a given reddit"""
    type = 'banned'

    def __init__(self, *k, **kw):
        UserList.__init__(self, *k, **kw)
        rels = getattr(c.site, 'each_%s' % self.type)
        self.rels = OrderedDict((rel._thing2_id, rel) for rel in rels())
        self.cells += ('note',)

    def user_row(self, row_type, user, editable=True):
        rel = self.rels.get(user._id, None)
        return UserTableItem(user, row_type, self.cells, self.container_name,
                             editable, self.remove_action, rel)

    @property
    def form_title(self):
        return _('ban users')

    @property
    def table_title(self):
        return  _('banned users')

    def user_ids(self):
        return self.rels.keys()
 
class WikiBannedList(BannedList):
    """List of users banned from editing a given wiki"""
    type = 'wikibanned'

class WikiMayContributeList(UserList):
    """List of users allowed to contribute to a given wiki"""
    type = 'wikicontributor'

    @property
    def form_title(self):
        return _('add a wiki contributor')

    @property
    def table_title(self):
        return _('wiki page contributors')

    def user_ids(self):
        return c.site.wikicontributor


class DetailsPage(LinkInfoPage):
    extension_handling= False

    def __init__(self, thing, *args, **kwargs):
        from admin_pages import Details
        after = kwargs.pop('after', None)
        reverse = kwargs.pop('reverse', False)
        count = kwargs.pop('count', None)

        if isinstance(thing, (Link, Comment)):
            details = Details(thing, after=after, reverse=reverse, count=count)

        if isinstance(thing, Link):
            link = thing
            comment = None
            content = details
        elif isinstance(thing, Comment):
            comment = thing
            link = Link._byID(comment.link_id)
            content = PaneStack()
            content.append(PermalinkMessage(link.make_permalink_slow()))
            content.append(LinkCommentSep())
            content.append(CommentPane(link, CommentSortMenu.operator('new'),
                                   comment, None, 1))
            content.append(details)

        kwargs['content'] = content
        LinkInfoPage.__init__(self, link, comment, *args, **kwargs)

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

class SelfServiceOatmeal(Templated):
    pass

class PromotePage(Reddit):
    create_reddit_box  = False
    submit_box         = False
    extension_handling = False
    searchbox          = False

    def __init__(self, title, nav_menus = None, *a, **kw):
        buttons = [NamedButton('new_promo')]
        if c.user_is_sponsor:
            buttons.append(NamedButton('roadblock'))
            buttons.append(NamedButton('current_promos', dest = ''))
        else:
            buttons.append(NamedButton('my_current_promos', dest = ''))

        buttons.append(NamedButton('graph'))

        if c.user_is_sponsor:
            buttons.append(NamedButton('admin_graph',
                                       dest='/admin/graph'))
            buttons.append(NavButton('report', 'report'))

        menu  = NavMenu(buttons, base_path = '/promoted',
                        type='flatlist')

        if nav_menus:
            nav_menus.insert(0, menu)
        else:
            nav_menus = [menu]

        kw['show_sidebar'] = False
        Reddit.__init__(self, title, nav_menus = nav_menus, *a, **kw)

class PromoteLinkForm(Templated):
    def __init__(self, sr=None, link=None, listing='',
                 timedeltatext='', *a, **kw):
        self.setup(sr, link, listing, timedeltatext, *a, **kw)
        Templated.__init__(self, sr=sr, datefmt = datefmt,
                           timedeltatext=timedeltatext, listing = listing,
                           bids = self.bids, *a, **kw)

    def setup(self, sr, link, listing, timedeltatext, *a, **kw):
        bids = []
        if c.user_is_sponsor and link:
            self.author = Account._byID(link.author_id)
            try:
                bids = bidding.Bid.lookup(thing_id = link._id)
                bids.sort(key = lambda x: x.date, reverse = True)
            except NotFound:
                pass

        # reference "now" to what we use for promtions
        now = promote.promo_datetime_now()

        # min date is the day before the first possible start date.
        self.promote_date_today = now
        mindate = make_offset_date(now, g.min_promote_future,
                                  business_days=True)
        mindate -= datetime.timedelta(1)

        startdate = mindate + datetime.timedelta(1)
        enddate = startdate + datetime.timedelta(3)

        self.startdate = startdate.strftime("%m/%d/%Y")
        self.enddate = enddate.strftime("%m/%d/%Y")

        self.mindate = mindate.strftime("%m/%d/%Y")

        self.link = None
        if link:
            self.sr_searches = simplejson.dumps(popular_searches())
            self.subreddits = (Subreddit.submit_sr_names(c.user) or
                               Subreddit.submit_sr_names(None))
            self.default_sr = (self.subreddits[0] if self.subreddits
                               else g.default_sr)
            self.link = promote.wrap_promoted(link)
            campaigns = PromoCampaign._by_link(link._id)
            self.campaigns = promote.get_renderable_campaigns(link, campaigns)
            self.promotion_log = PromotionLog.get(link)

        self.bids = bids
        self.min_daily_bid = 0 if c.user_is_admin else g.min_promote_bid


class PromoteLinkFormCpm(PromoteLinkForm):
    def __init__(self, sr=None, link=None, listing='',
                 timedeltatext='', *a, **kw):
        self.setup(sr, link, listing, timedeltatext, *a, **kw)
        
        if not c.user_is_sponsor:
            self.now = promote.promo_datetime_now().date()
            start_date = self.now
            end_date = self.now + datetime.timedelta(60) # two months
            self.inventory = promote.get_available_impressions(sr, start_date, end_date)

        Templated.__init__(self, sr=sr, datefmt = datefmt,
                           timedeltatext=timedeltatext, listing = listing,
                           bids = self.bids, *a, **kw)


class PromoAdminTool(Reddit):
    def __init__(self, query_type=None, launchdate=None, start=None, end=None, *a, **kw):
        self.query_type = query_type
        self.launch = launchdate if launchdate else datetime.datetime.now()
        self.start = start if start else datetime.datetime.now()
        self.end = end if end else self.start + datetime.timedelta(1)
        # started_on shows promos that were scheduled to launch on start date
        if query_type == "started_on" and self.start:
            all_promos = self.get_promo_info(self.start, 
                    self.start + datetime.timedelta(1)) # exactly one day
            promos = {}
            start_date_string = self.start.strftime("%Y/%m/%d")
            for camp_id, data in all_promos.iteritems():
                if start_date_string == data["campaign_start"]:
                    promos[camp_id] = data
        # between shows any promo that was scheduled on at least one day in
        # the range [start, end)
        elif query_type == "between" and self.start and self.end:
            promos = self.get_promo_info(self.start, self.end)
        else:
            promos = {}
      
        for camp_id, promo in promos.iteritems():
            link_id36 = promo["link_fullname"].split('_')[1]
            promo["campaign_id"] = camp_id
            promo["edit_link"] = promote.promo_edit_url(None, id36=link_id36)

        self.promos = sorted(promos.values(), 
                             key=lambda x: (x['username'], x['campaign_start']))

        Reddit.__init__(self, title="Promo Admin Tool", show_sidebar=False)


    def get_promo_info(self, start_date, end_date):
        promo_info = {}
        scheduled = Promote_Graph.get_current_promos(start_date, 
                            end_date + datetime.timedelta(1))
        campaign_ids = [x[1] for x in scheduled]
        campaigns = PromoCampaign._byID(campaign_ids, data=True, return_dict=True)
        account_ids = [pc.owner_id for pc in campaigns.itervalues()]
        accounts = Account._byID(account_ids, data=True, return_dict=True)
        for link, campaign_id, scheduled_start, scheduled_end in scheduled:
            campaign = campaigns[campaign_id]
            days = (campaign.end_date - campaign.start_date).days
            bid_per_day = float(campaign.bid) / days
            account = accounts[campaign.owner_id]
            promo_info[campaign._id] = { 
                'username': account.name,
                'user_email': account.email,
                'link_title': link.title,
                'link_fullname': link._fullname,
                'campaign_start': campaign.start_date.strftime("%Y/%m/%d"),
                'campaign_end': campaign.end_date.strftime("%Y/%m/%d"),
                'bid_per_day': bid_per_day,
            }            
        return promo_info 



class Roadblocks(Templated):
    def __init__(self):
        self.roadblocks = promote.get_roadblocks()
        Templated.__init__(self)
        # reference "now" to what we use for promtions
        now = promote.promo_datetime_now()

        startdate = now + datetime.timedelta(1)
        enddate   = startdate + datetime.timedelta(1)

        self.startdate = startdate.strftime("%m/%d/%Y")
        self.enddate   = enddate  .strftime("%m/%d/%Y")
        self.sr_searches = simplejson.dumps(popular_searches())
        self.subreddits = (Subreddit.submit_sr_names(c.user) or
                           Subreddit.submit_sr_names(None))
        self.default_sr = self.subreddits[0] if self.subreddits \
                          else g.default_sr

class TabbedPane(Templated):
    def __init__(self, tabs, linkable=False):
        """Renders as tabbed area where you can choose which tab to
        render. Tabs is a list of tuples (tab_name, tab_pane)."""
        buttons = []
        for tab_name, title, pane in tabs:
            onclick = "return select_tab_menu(this, '%s')" % tab_name
            buttons.append(JsButton(title, tab_name=tab_name, onclick=onclick))

        self.tabmenu = JsNavMenu(buttons, type = 'tabmenu')
        self.tabs = tabs

        Templated.__init__(self, linkable=linkable)

class LinkChild(object):
    def __init__(self, link, load = False, expand = False, nofollow = False):
        self.link = link
        self.expand = expand
        self.load = load or expand
        self.nofollow = nofollow

    def content(self):
        return ''

def make_link_child(item):
    link_child = None
    editable = False

    # if the item has a media_object, try to make a MediaEmbed for rendering
    if item.media_object:
        media_embed = None
        if isinstance(item.media_object, basestring):
            media_embed = item.media_object
        else:
            try:
                media_embed = get_media_embed(item.media_object)
            except TypeError:
                g.log.warning("link %s has a bad media object" % item)
                media_embed = None

            if media_embed:
                media_embed =  MediaEmbed(media_domain = g.media_domain,
                                          height = media_embed.height + 10,
                                          width = media_embed.width + 10,
                                          scrolling = media_embed.scrolling,
                                          id36 = item._id36)
            else:
                g.log.debug("media_object without media_embed %s" % item)

        if media_embed:
            link_child = MediaChild(item, media_embed, load = True)

    # if the item is_self, add a selftext child
    elif item.is_self:
        if not item.selftext: item.selftext = u''

        expand = getattr(item, 'expand_children', False)

        editable = (expand and
                    item.author == c.user and
                    not item._deleted)    
        link_child = SelfTextChild(item, expand = expand,
                                   nofollow = item.nofollow)

    return link_child, editable

class MediaChild(LinkChild):
    """renders when the user hits the expando button to expand media
       objects, like embedded videos"""
    css_style = "video"
    def __init__(self, link, content, **kw):
        self._content = content
        LinkChild.__init__(self, link, **kw)

    def content(self):
        if isinstance(self._content, basestring):
            return self._content
        return self._content.render()

class MediaEmbed(Templated):
    """The actual rendered iframe for a media child"""
    pass


class SelfTextChild(LinkChild):
    css_style = "selftext"

    def content(self):
        u = UserText(self.link, self.link.selftext,
                     editable = c.user == self.link.author,
                     nofollow = self.nofollow,
                     target="_top" if c.cname else None,
                     expunged=self.link.expunged)
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
                 extra_css = '',
                 name = "text",
                 expunged=False):

        css_class = "usertext"
        if cloneable:
            css_class += " cloneable"
        if extra_css:
            css_class += " " + extra_css

        if text is None:
            text = ''

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
                                css_class = css_class,
                                name = name,
                                expunged=expunged)

class MediaEmbedBody(CachedTemplate):
    """What's rendered inside the iframe that contains media objects"""
    def render(self, *a, **kw):
        res = CachedTemplate.render(self, *a, **kw)
        return responsive(res, True)


class PaymentForm(Templated):
    def __init__(self, link, campaign, **kw):
        self.link = promote.wrap_promoted(link)
        self.campaign = promote.get_renderable_campaigns(link, campaign)
        Templated.__init__(self, **kw)

class Promotion_Summary(Templated):
    def __init__(self, ndays):
        end_date = promote.promo_datetime_now().date()
        start_date = promote.promo_datetime_now(offset = -ndays).date()
        links = set()
        authors = {}
        author_score = {}
        self.total = 0
        for link, camp_id, s, e in Promote_Graph.get_current_promos(start_date, end_date):
            # fetch campaign or skip to next campaign if it's not found
            try:
                campaign = PromoCampaign._byID(camp_id, data=True)
            except NotFound:
                g.log.error("Missing campaign (link: %d, camp_id: %d) omitted "
                            "from promotion summary" % (link._id, camp_id))
                continue

            # get required attributes or skip to next campaign if any are missing.
            try:
                campaign_trans_id = campaign.trans_id
                campaign_start_date = campaign.start_date
                campaign_end_date = campaign.end_date
                campaign_bid = campaign.bid
            except AttributeError, e:
                g.log.error("Corrupt PromoCampaign (link: %d, camp_id, %d) "
                            "omitted from promotion summary. Error was: %r" % 
                            (link._id, camp_id, e))
                continue

            if campaign_trans_id > 0: # skip freebies and unauthorized
                links.add(link)
                link.bid = getattr(link, "bid", 0) + campaign_bid
                link.ncampaigns = getattr(link, "ncampaigns", 0) + 1
                
                bid_per_day = campaign_bid / (campaign_end_date - campaign_start_date).days

                sd = max(start_date, campaign_start_date.date())
                ed = min(end_date, campaign_end_date.date())
                
                self.total += bid_per_day * (ed - sd).days
                    
                authors.setdefault(link.author.name, []).append(link)
                author_score[link.author.name] = author_score.get(link.author.name, 0) + link._score
            
        links = list(links)
        links.sort(key = lambda x: x._score, reverse = True)
        author_score = list(sorted(((v, k) for k,v in author_score.iteritems()),
                                   reverse = True))

        self.links = links
        self.ndays = ndays
        Templated.__init__(self)

    @classmethod
    def send_summary_email(cls, to_addr, ndays):
        from r2.lib import emailer
        c.site = DefaultSR()
        c.user = FakeAccount()
        p = cls(ndays)
        emailer.send_html_email(to_addr, g.feedback_email,
                                "Self-serve promotion summary for last %d days"
                                % ndays, p.render('email'))


def force_datetime(d):
    return datetime.datetime.combine(d, datetime.time())


class Promote_Graph(Templated):
    
    @classmethod
    @memoize('get_market', time = 60)
    def get_market(cls, user_id, start_date, end_date):
        market = {}
        promo_counter = {}
        def callback(link, bid_day, starti, endi, campaign):
            for i in xrange(starti, endi):
                if user_id is None or link.author_id == user_id:
                    if (not promote.is_unpaid(link) and 
                        not promote.is_rejected(link) and
                        campaign.trans_id != NO_TRANSACTION):
                        market[i] = market.get(i, 0) + bid_day
                        promo_counter[i] = promo_counter.get(i, 0) + 1
        cls.promo_iter(start_date, end_date, callback)
        return market, promo_counter

    @classmethod
    def promo_iter(cls, start_date, end_date, callback):
        size = (end_date - start_date).days
        current_promos = cls.get_current_promos(start_date, end_date)
        campaign_ids = [camp_id for link, camp_id, s, e in current_promos]
        campaigns = PromoCampaign._byID(campaign_ids, data=True)
        for link, campaign_id, s, e in current_promos:
            if campaign_id in campaigns:
                campaign = campaigns[campaign_id]
                sdate = campaign.start_date.date()
                edate = campaign.end_date.date()
                starti = max((sdate - start_date).days, 0)
                endi = min((edate - start_date).days, size)
                bid_day = campaign.bid / max((edate - sdate).days, 1)
                callback(link, bid_day, starti, endi, campaign)
        
    @classmethod
    def get_current_promos(cls, start_date, end_date):
        # grab promoted links
        # returns a list of (thing_id, campaign_idx, start, end)
        promos = PromotionWeights.get_schedule(start_date, end_date)
        # sort based on the start date
        promos.sort(key = lambda x: x[2])

        # wrap the links
        links = wrap_links([p[0] for p in promos])
        # remove rejected/unpaid promos
        links = dict((l._fullname, l) for l in links.things
                     if promote.is_accepted(l) or promote.is_unapproved(l))
        # filter promos accordingly
        promos = [(links[thing_name], campaign_id, s, e) 
                  for thing_name, campaign_id, s, e in promos
                  if links.has_key(thing_name)]

        return promos

    def __init__(self, start_date, end_date, bad_dates=None, admin_view=False):
        self.admin_view = admin_view and c.user_is_sponsor
        self.now = promote.promo_datetime_now()

        start_date = to_date(start_date)
        end_date = to_date(end_date)
        end_before = end_date + datetime.timedelta(days=1)

        size = (end_before - start_date).days
        self.dates = [start_date + datetime.timedelta(i) for i in xrange(size)]

        # these will be cached queries
        market, promo_counter = self.get_market(None, start_date, end_before)
        my_market = market
        if not self.admin_view:
            my_market = self.get_market(c.user._id, start_date, end_before)[0]

        # determine the range of each link
        promote_blocks = []
        def block_maker(link, bid_day, starti, endi, campaign):
            if ((self.admin_view or link.author_id == c.user._id)
                and not promote.is_rejected(link)
                and not promote.is_unpaid(link)):
                promote_blocks.append((link, starti, endi, campaign))
        self.promo_iter(start_date, end_before, block_maker)

        # now sort the promoted_blocks into the most contiguous chuncks we can
        sorted_blocks = []
        while promote_blocks:
            cur = promote_blocks.pop(0)
            while True:
                sorted_blocks.append(cur)
                # get the future items (sort will be preserved)
                future = filter(lambda x: x[2] >= cur[3], promote_blocks)
                if future:
                    # resort by date and give precidence to longest promo:
                    cur = min(future, key = lambda x: (x[2], x[2]-x[3]))
                    promote_blocks.remove(cur)
                else:
                    break

        pool =PromotionWeights.bid_history(promote.promo_datetime_now(offset=-30),
                                           promote.promo_datetime_now(offset=2))

        # graphs of impressions and clicks
        self.promo_traffic = promote.traffic_totals()

        impressions = [(d, i) for (d, (i, k)) in self.promo_traffic]
        pool = dict((d, b+r) for (d, b, r) in pool)

        if impressions:
            CPM = [(force_datetime(d), (pool.get(d, 0) * 1000. / i) if i else 0)
                   for (d, (i, k)) in self.promo_traffic if d in pool]
            mean_CPM = sum(x[1] for x in CPM) * 1. / max(len(CPM), 1)

            CPC = [(force_datetime(d), (100 * pool.get(d, 0) / k) if k else 0)
                   for (d, (i, k)) in self.promo_traffic if d in pool]
            mean_CPC = sum(x[1] for x in CPC) * 1. / max(len(CPC), 1)

            cpm_title = _("cost per 1k impressions ($%(avg).2f average)") % dict(avg=mean_CPM)
            cpc_title = _("cost per click ($%(avg).2f average)") % dict(avg=mean_CPC/100.)

            data = traffic.zip_timeseries(((d, (min(v, mean_CPM * 2),)) for d, v in CPM),
                                          ((d, (min(v, mean_CPC * 2),)) for d, v in CPC))

            from r2.lib.pages.trafficpages import COLORS  # not top level because of * imports :(
            self.performance_table = TimeSeriesChart("promote-graph-table",
                                                     _("historical performance"),
                                                     "day",
                                                     [dict(color=COLORS.DOWNVOTE_BLUE,
                                                           title=cpm_title,
                                                           shortname=_("CPM")),
                                                      dict(color=COLORS.DOWNVOTE_BLUE,
                                                           title=cpc_title,
                                                           shortname=_("CPC"))],
                                                     data)
        else:
            self.performance_table = None

        self.promo_traffic = dict(self.promo_traffic)

        if self.admin_view:
            predicted = inventory.get_predicted_by_date(None, start_date,
                                                        end_before)
            self.impression_inventory = predicted
            # TODO: Real data
            self.scheduled_impressions = dict.fromkeys(predicted, 0)
        else:
            self.scheduled_impressions = None
            self.impression_inventory = None

        self.cpc = {}
        self.cpm = {}
        self.delivered = {}
        self.clicked = {}
        self.my_market = {}
        self.promo_counter = {}

        today = self.now.date()
        for i in xrange(size):
            day = start_date + datetime.timedelta(i)
            cpc = cpm = delivered = clicks = "---"
            if day in self.promo_traffic:
                delivered, clicks = self.promo_traffic[day]
                if i in market and day < today:
                    cpm = "$%.2f" % promote.cost_per_mille(market[i], delivered)
                    cpc = "$%.2f" % promote.cost_per_click(market[i], clicks)
                delivered = format_number(delivered, c.locale)
                clicks = format_number(clicks, c.locale)
                if day == today:
                    delivered = "(%s)" % delivered
                    clicks = "(%s)" % clicks
            self.cpc[day] = cpc
            self.cpm[day] = cpm
            self.delivered[day] = delivered
            self.clicked[day] = clicks
            if i in my_market:
                self.my_market[day] = "$%.2f" % my_market[i]
            else:
                self.my_market[day] = "---"
            self.promo_counter[day] = promo_counter.get(i, "---")

        Templated.__init__(self, today=today, promote_blocks=sorted_blocks,
                           start_date=start_date, end_date=end_date,
                           bad_dates=bad_dates)

    def to_iter(self, localize = True):
        locale = c.locale
        def num(x):
            if localize:
                return format_number(x, locale)
            return str(x)
        for link, uimp, nimp, ucli, ncli in self.recent:
            yield (link._date.strftime("%Y-%m-%d"),
                   num(uimp), num(nimp), num(ucli), num(ncli),
                   num(link._ups - link._downs), 
                   "$%.2f" % link.promote_bid,
                   _force_unicode(link.title))


class PromoteReport(Templated):
    def __init__(self, links, link_text, bad_links, start, end):
        self.links = links
        self.start = start
        self.end = end
        if links:
            self.make_link_report()
            self.make_campaign_report()
            p = request.get.copy()
            self.csv_url = '%s.csv?%s' % (request.path, urlencode(p))
        else:
            self.link_report = None
            self.campaign_report = None
            self.csv_url = None

        Templated.__init__(self, link_text=link_text, bad_links=bad_links)

    def as_csv(self):
        out = cStringIO.StringIO()
        writer = csv.writer(out)

        writer.writerow((_("start date"), self.start.strftime('%m/%d/%Y')))
        writer.writerow((_("end date"), self.end.strftime('%m/%d/%Y')))
        writer.writerow([])
        writer.writerow((_("links"),))
        writer.writerow((
            _("name"),
            _("owner"),
            _("comments"),
            _("upvotes"),
            _("downvotes"),
        ))
        for row in self.link_report:
            writer.writerow((row['name'], row['owner'], row['comments'],
                             row['upvotes'], row['downvotes']))

        writer.writerow([])
        writer.writerow((_("campaigns"),))
        writer.writerow((
            _("link"),
            _("owner"),
            _("campaign"),
            _("target"),
            _("bid"),
            _("frontpage clicks"), _("frontpage impressions"),
            _("subreddit clicks"), _("subreddit impressions"),
            _("total clicks"), _("total impressions"),
        ))
        for row in self.campaign_report:
            writer.writerow(
                (row['link'], row['owner'], row['campaign'], row['target'],
                 row['bid'], row['fp_clicks'], row['fp_impressions'],
                 row['sr_clicks'], row['sr_impressions'], row['total_clicks'],
                 row['total_impressions'])
            )
        return out.getvalue()

    def make_link_report(self):
        link_report = []
        owners = Account._byID([link.author_id for link in self.links],
                               data=True)

        for link in self.links:
            row = {
                'name': link._fullname,
                'owner': owners[link.author_id].name,
                'comments': link.num_comments,
                'upvotes': link._ups,
                'downvotes': link._downs,
            }
            link_report.append(row)
        self.link_report = link_report

    @classmethod
    def _get_hits(cls, traffic_cls, campaigns, start, end):
        campaigns_by_name = {camp._fullname: camp for camp in campaigns}
        codenames = campaigns_by_name.keys()
        start = (start - promote.timezone_offset).replace(tzinfo=None)
        end = (end - promote.timezone_offset).replace(tzinfo=None)
        hits = traffic_cls.campaign_history(codenames, start, end)
        sr_hits = defaultdict(int)
        fp_hits = defaultdict(int)
        for date, codename, sr, (uniques, pageviews) in hits:
            campaign = campaigns_by_name[codename]
            campaign_start = campaign.start_date - promote.timezone_offset
            campaign_end = campaign.end_date - promote.timezone_offset
            date = date.replace(tzinfo=g.tz)
            if date < campaign_start or date > campaign_end:
                continue
            if sr == '':
                fp_hits[codename] += pageviews
            else:
                sr_hits[codename] += pageviews
        return fp_hits, sr_hits

    @classmethod
    def get_imps(cls, campaigns, start, end):
        return cls._get_hits(traffic.TargetedImpressionsByCodename, campaigns,
                             start, end)

    @classmethod
    def get_clicks(cls, campaigns, start, end):
        return cls._get_hits(traffic.TargetedClickthroughsByCodename, campaigns,
                             start, end)

    def make_campaign_report(self):
        campaigns = PromoCampaign._by_link([link._id for link in self.links])

        def keep_camp(camp):
            return not (camp.start_date.date() >= self.end.date() or
                        camp.end_date.date() <= self.start.date() or
                        not camp.trans_id)

        campaigns = [camp for camp in campaigns if keep_camp(camp)]
        fp_imps, sr_imps = self.get_imps(campaigns, self.start, self.end)
        fp_clicks, sr_clicks = self.get_clicks(campaigns, self.start, self.end)
        owners = Account._byID([link.author_id for link in self.links],
                               data=True)
        links_by_id = {link._id: link for link in self.links}
        campaign_report = []

        for camp in campaigns:
            link = links_by_id[camp.link_id]
            fullname = camp._fullname
            camp_duration = (camp.end_date - camp.start_date).days
            effective_duration = (min(camp.end_date, self.end)
                                  - max(camp.start_date, self.start)).days
            bid = camp.bid * (float(effective_duration) / camp_duration)
            row = {
                'link': link._fullname,
                'owner': owners[link.author_id].name,
                'campaign': fullname,
                'target': camp.sr_name or 'frontpage',
                'bid': format_currency(bid, 'USD'),
                'fp_impressions': fp_imps[fullname],
                'sr_impressions': sr_imps[fullname],
                'fp_clicks': fp_clicks[fullname],
                'sr_clicks': sr_clicks[fullname],
                'total_impressions': fp_imps[fullname] + sr_imps[fullname],
                'total_clicks': fp_clicks[fullname] + sr_clicks[fullname],
            }
            campaign_report.append(row)
        self.campaign_report = sorted(campaign_report, key=lambda r: r['link'])

class InnerToolbarFrame(Templated):
    def __init__(self, link, expanded = False):
        Templated.__init__(self, link = link, expanded = expanded)

class RawString(Templated):
   def __init__(self, s):
       self.s = s

   def render(self, *a, **kw):
       return unsafe(self.s)


class TryCompact(Reddit):
    def __init__(self, dest, **kw):
        dest = dest or "/"
        u = UrlParser(dest)
        u.set_extension("compact")
        self.compact = u.unparse()

        u.update_query(keep_extension = True)
        self.like = u.unparse()

        u.set_extension("mobile")
        self.mobile = u.unparse()
        Reddit.__init__(self, **kw)

class AccountActivityPage(BoringPage):
    def __init__(self):
        super(AccountActivityPage, self).__init__(_("account activity"))

    def content(self):
        return UserIPHistory()

class UserIPHistory(Templated):
    def __init__(self):
        self.my_apps = OAuth2Client._by_user(c.user)
        self.ips = ips_by_account_id(c.user._id)
        super(UserIPHistory, self).__init__()

class ApiHelp(Templated):
    def __init__(self, api_docs, *a, **kw):
        self.api_docs = api_docs
        super(ApiHelp, self).__init__(*a, **kw)

class RulesPage(Templated):
    pass

class AwardReceived(Templated):
    pass

class ConfirmAwardClaim(Templated):
    pass

class TimeSeriesChart(Templated):
    def __init__(self, id, title, interval, columns, rows,
                 latest_available_data=None, classes=[]):
        self.id = id
        self.title = title
        self.interval = interval
        self.columns = columns
        self.rows = rows
        self.latest_available_data = (latest_available_data or
                                      datetime.datetime.utcnow())
        self.classes = " ".join(classes)

        Templated.__init__(self)

class InterestBar(Templated):
    def __init__(self, has_subscribed):
        self.has_subscribed = has_subscribed
        Templated.__init__(self)

class GoldInfoPage(BoringPage):
    def __init__(self, *args, **kwargs):
        self.prices = {
            "gold_month_price": g.gold_month_price,
            "gold_year_price": g.gold_year_price,
        }
        BoringPage.__init__(self, *args, **kwargs)

class GoldPartnersPage(BoringPage):
    def __init__(self, *args, **kwargs):
        self.prices = {
            "gold_month_price": g.gold_month_price,
            "gold_year_price": g.gold_year_price,
        }
        if c.user_is_loggedin:
            self.existing_codes = GoldPartnerDealCode.get_codes_for_user(c.user)
        else:
            self.existing_codes = []
        BoringPage.__init__(self, *args, **kwargs)

class Goldvertisement(Templated):
    def __init__(self):
        Templated.__init__(self)
        if not c.user.gold:
            blurbs = g.live_config["goldvertisement_blurbs"]
        else:
            blurbs = g.live_config["goldvertisement_has_gold_blurbs"]
        self.blurb = random.choice(blurbs)

class LinkCommentsSettings(Templated):
    def __init__(self, link):
        Templated.__init__(self)
        self.link = link
        self.contest_mode = link.contest_mode
        self.can_edit = (c.user_is_loggedin
                           and (c.user_is_admin or
                                link.subreddit_slow.is_moderator(c.user)))

class ModeratorPermissions(Templated):
    def __init__(self, user, permissions_type, permissions,
                 editable=False, embedded=False):
        self.user = user
        self.permissions = permissions
        Templated.__init__(self, permissions_type=permissions_type,
                           editable=editable, embedded=embedded)


class PolicyView(Templated):
    pass


class PolicyPage(BoringPage):
    css_class = 'policy-page'

    def __init__(self, pagename=None, content=None, **kw):
        BoringPage.__init__(self, pagename=pagename, show_sidebar=False,
                            content=content, **kw)
        self.welcomebar = None

    def build_toolbars(self):
        toolbars = BoringPage.build_toolbars(self)
        policies_buttons = [
            NavButton(_('privacy policy'), '/privacypolicy'),
            NavButton(_('user agreement'), '/useragreement'),
        ]
        policies_menu = NavMenu(policies_buttons, type='tabmenu',
                                base_path='/help')
        toolbars.append(policies_menu)
        return toolbars
