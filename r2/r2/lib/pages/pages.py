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

from collections import Counter, OrderedDict

from r2.lib.wrapped import Wrapped, Templated, CachedTemplate
from r2.models import Account, FakeAccount, DefaultSR, make_feedurl
from r2.models import FakeSubreddit, Subreddit, SubSR, AllMinus, AllSR
from r2.models import Friends, All, Sub, NotFound, DomainSR, Random, Mod, RandomNSFW, RandomSubscription, MultiReddit, ModSR, Frontpage, LabeledMulti
from r2.models import Link, Printable, Trophy, PromoCampaign, PromotionWeights, Comment
from r2.models import Flair, FlairTemplate, FlairTemplateBySubredditIndex
from r2.models import USER_FLAIR, LINK_FLAIR
from r2.models.bidding import Bid
from r2.models.gold import (
    gold_payments_by_user,
    gold_received_by_user,
    days_to_pennies,
    gold_goal_on,
    gold_revenue_steady,
    gold_revenue_volatile,
    get_subscription_details,
    TIMEZONE as GOLD_TIMEZONE,
)
from r2.models.promo import (
    NO_TRANSACTION,
    PROMOTE_PRIORITIES,
    PromotedLinkRoadblock,
    PromotionLog,
)
from r2.models.token import OAuth2Client, OAuth2AccessToken
from r2.models import traffic
from r2.models import ModAction
from r2.models import Thing
from r2.models.wiki import WikiPage, ImagesByWikiPage
from r2.lib.db import tdb_cassandra
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
from r2.lib.template_helpers import add_sr, get_domain, format_number, media_https_if_secure
from r2.lib.subreddit_search import popular_searches
from r2.lib.log import log_text
from r2.lib.memoize import memoize
from r2.lib.utils import trunc_string as _truncate, to_date
from r2.lib.filters import safemarkdown
from r2.lib.utils import Storage, tup
from r2.lib.utils import precise_format_timedelta

from babel.numbers import format_currency
from babel.dates import format_date
from collections import defaultdict
import csv
import hmac
import hashlib
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

from things import wrap_links, wrap_things, default_thing_wrapper

datefmt = _force_utf8(_('%d %b %Y'))

MAX_DESCRIPTION_LENGTH = 150

def get_captcha():
    if not c.user_is_loggedin or c.user.needs_captcha():
        return get_iden()

def responsive(res, space_compress=None):
    """
    Use in places where the template is returned as the result of the
    controller so that it becomes compatible with the page cache.
    """
    if space_compress is None:
        space_compress = not g.template_debug

    if is_api():
        res = websafe_json(simplejson.dumps(res or ''))
        if c.allowed_callback:
            res = "%s(%s)" % (websafe_json(c.allowed_callback), res)
    elif space_compress:
        res = spaceCompress(res)
    return res


class Robots(Templated):
    pass


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

    def __init__(self, space_compress=None, nav_menus=None, loginbox=True,
                 infotext='', content=None, short_description='', title='',
                 robots=None, show_sidebar=True, show_chooser=False,
                 footer=True, srbar=True, page_classes=None, short_title=None,
                 show_wiki_actions=False, extra_js_config=None, **context):
        Templated.__init__(self, **context)
        self.title = title
        self.short_title = short_title
        self.short_description = short_description
        self.robots = robots
        self.infotext = infotext
        self.extra_js_config = extra_js_config
        self.show_wiki_actions = show_wiki_actions
        self.loginbox = True
        self.show_sidebar = show_sidebar
        self.space_compress = space_compress
        # instantiate a footer
        self.footer = RedditFooter() if footer else None
        self.debug_footer = DebugFooter()
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
            gold_link = GoldPayment("gift",
                                    "monthly",
                                    months=1,
                                    signed=False,
                                    recipient="",
                                    giftmessage=None,
                                    passthrough=None,
                                    thing=None,
                                    clone_template=True,
                                    thing_type="link",
                                   )
            gold_comment = GoldPayment("gift",
                                       "monthly",
                                       months=1,
                                       signed=False,
                                       recipient="",
                                       giftmessage=None,
                                       passthrough=None,
                                       thing=None,
                                       clone_template=True,
                                       thing_type="comment",
                                      )
            self._content = PaneStack([ShareLink(), content,
                                       gold_comment, gold_link])
        else:
            self._content = content

        self.show_chooser = (
            show_chooser and
            c.render_style == "html" and
            c.user_is_loggedin and
            (
                isinstance(c.site, (DefaultSR, AllSR, ModSR, LabeledMulti)) or
                c.site.name == g.live_config["listing_chooser_explore_sr"]
            )
        )

        self.toolbars = self.build_toolbars()
        self.subreddit_stylesheet_url = self.get_subreddit_stylesheet_url()

    @staticmethod
    def get_subreddit_stylesheet_url():
        if c.can_apply_styles and c.allow_styles:
            if c.secure:
                if c.site.stylesheet_url_https:
                    return c.site.stylesheet_url_https
                elif c.site.stylesheet_contents_secure:
                    return c.site.stylesheet_url
            else:
                if c.site.stylesheet_url_http:
                    return c.site.stylesheet_url_http
                elif c.site.stylesheet_contents:
                    return c.site.stylesheet_url

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

    def sr_moderators(self):
        accounts = Account._byID(c.site.moderators,
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

        if isinstance(c.site, (MultiReddit, ModSR)):
            srs = Subreddit._byID(c.site.sr_ids, data=True,
                                  return_dict=False)

            if (srs and c.user_is_loggedin and
                    (c.user_is_admin or c.site.is_moderator(c.user))):
                ps.append(self.sr_admin_menu())

            if isinstance(c.site, LabeledMulti):
                ps.append(MultiInfoBar(c.site, srs, c.user))
                c.js_preload.set_wrapped(
                    '/api/multi/%s' % c.site.path.lstrip('/'), c.site)
            elif srs:
                if isinstance(c.site, ModSR):
                    box = SubscriptionBox(srs, multi_text=strings.mod_multi)
                else:
                    box = SubscriptionBox(srs)
                ps.append(SideContentBox(_('these subreddits'), [box]))


        if isinstance(c.site, AllSR):
            ps.append(AllInfoBar(c.site, c.user))

        user_banned = c.user_is_loggedin and c.site.is_banned(c.user)

        if (self.submit_box
                and (c.user_is_loggedin or not g.read_only_mode)
                and not user_banned):
            if (not isinstance(c.site, FakeSubreddit)
                    and c.site.type in ("archived",
                                        "restricted",
                                        "gold_restricted")
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
                    if c.site.type == 'restricted':
                        subtitle = _('submission in this subreddit '
                                     'is restricted to approved submitters.')
                    elif c.site.type == 'gold_restricted':
                        subtitle = _('submission in this subreddit '
                                     'is restricted to reddit gold members.')
                    ps.append(SideBox(title=_('Submissions restricted'),
                                      css_class="submit",
                                      disabled=True,
                                      subtitles=[subtitle],
                                      show_icon=False))
            else:
                fake_sub = isinstance(c.site, FakeSubreddit)
                is_multi = isinstance(c.site, MultiReddit)
                if c.site.link_type != 'self':
                    ps.append(SideBox(title=c.site.submit_link_label or
                                            strings.submit_link_label,
                                      css_class="submit submit-link",
                                      link="/submit",
                                      sr_path=not fake_sub or is_multi,
                                      show_cover=True))
                if c.site.link_type != 'link':
                    ps.append(SideBox(title=c.site.submit_text_label or
                                            strings.submit_text_label,
                                      css_class="submit submit-text",
                                      link="/submit?selftext=true",
                                      sr_path=not fake_sub or is_multi,
                                      show_cover=True))

        no_ads_yet = True
        show_adbox = (c.user.pref_show_adbox or not c.user.gold) and not g.disable_ads

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
                more_text = mod_href = ""
                sidebar_list_length = 10
                num_not_shown = len(moderators) - sidebar_list_length

                if num_not_shown > 0:
                    more_text = _("...and %d more") % (num_not_shown)
                    mod_href = "http://%s/about/moderators" % get_domain()

                if '/r/%s' % c.site.name == g.admin_message_acct:
                    label = _('message the admins')
                else:
                    label = _('message the moderators')
                helplink = ("/message/compose?to=%%2Fr%%2F%s" % c.site.name,
                            label)
                ps.append(SideContentBox(_('moderators'),
                                         moderators[:sidebar_list_length],
                                         helplink = helplink,
                                         more_href = mod_href,
                                         more_text = more_text))

        if no_ads_yet and show_adbox:
            ps.append(Ads())
            if g.live_config["gold_revenue_goal"]:
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
        if c.bare_content:
            res = self.content().render()
        else:
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
                            NamedButton('comments'),
                            NamedButton('gilded'),
                            ]
        else:
            main_buttons = [NamedButton('hot', dest='', aliases=['/hot']),
                            NamedButton('new'),
                            NamedButton('rising'),
                            NamedButton('controversial'),
                            NamedButton('top'),
                            ]

            if not isinstance(c.site, DomainSR):
                main_buttons.append(NamedButton('gilded',
                                                aliases=['/comments/gilded']))

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
            func = 'subreddit'
            if isinstance(c.site, DomainSR):
                func = 'domain'
            toolbar.insert(0, PageNameNav(func))

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
            if c.site.is_moderator(c.user):
                classes.add('moderator')
            if c.user.gold:
                classes.add('gold')

        if isinstance(c.site, MultiReddit):
            classes.add('multi-page')

        if self.show_chooser:
            classes.add('with-listing-chooser')
            if c.user.pref_collapse_left_bar:
                classes.add('listing-chooser-collapsed')

        if self.extra_page_classes:
            classes.update(self.extra_page_classes)
        if self.supplied_page_classes:
            classes.update(self.supplied_page_classes)

        return classes


class DebugFooter(Templated):
    pass


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
                    NamedButton("jobs", False, nocname=True, dest="/r/redditjobs"),
                ],
                title = _("about"),
                type = "flat_vert",
                separator = ""),

            NavMenu([
                    NamedButton("wiki", False, nocname=True),
                    OffsiteButton(_("FAQ"), dest = "/wiki/faq", nocname=True),
                    OffsiteButton(_("reddiquette"), nocname=True, dest = "/wiki/reddiquette"),
                    NamedButton("rules", False, nocname=True),
                    NamedButton("contact", False),
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
        request.GET["style"] = "off"
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

    @property
    def creator_text(self):
        if self.sr.author:
            if self.sr.is_moderator(self.sr.author) or self.sr.author._deleted:
                return WrappedUser(self.sr.author).render()
            else:
                return self.sr.author.name
        return None

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
                 disabled=False, show_icon=True, target='_top'):
        CachedTemplate.__init__(self, link = link, target = target,
                           title = title, css_class = css_class,
                           sr_path = sr_path, subtitles = subtitles,
                           show_cover = show_cover, nocname=nocname,
                           disabled=disabled, show_icon=show_icon)


class PrefsPage(Reddit):
    """container for pages accessible via /prefs.  No extension handling."""

    extension_handling = False

    def __init__(self, show_sidebar = False, title=None, *a, **kw):
        title = title or "%s (%s)" % (_("preferences"), c.site.name.strip(' '))
        Reddit.__init__(self, show_sidebar = show_sidebar,
                        title=title,
                        *a, **kw)

    def build_toolbars(self):
        buttons = [NavButton(menu.options, ''),
                   NamedButton('apps')]

        if c.user.pref_private_feeds:
            buttons.append(NamedButton('feeds'))

        buttons.extend([NamedButton('friends'),
                        NamedButton('blocked'),
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
    def __init__(self, email=True, password=True, verify=False, dest=None):
        self.email = email
        self.password = password
        self.verify = verify
        self.dest = dest
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
        if c.user_is_loggedin and c.user.is_moderator_somewhere:
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
            if u.path in ['/api/v1/authorize', '/api/v1/authorize.compact']:
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
                            show_sidebar=False, content=content,
                            short_title=_("permission"))

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
        for visit in reversed(visits):
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
                 show_promote_button=False, *a, **kw):

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
                                        exclude=self.link._fullname,
                                        public_srs_only=True)
            self.num_duplicates = len(builder.get_items()[0])
        else:
            self.num_duplicates = num_duplicates

        self.show_promote_button = show_promote_button
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

            if self.num_duplicates > 0:
                buttons.append(info_button('duplicates', num=self.num_duplicates))

        if self.show_promote_button:
            buttons.append(NavButton(menu.promote, 'promoted', sr_path=False))

        toolbar = [NavMenu(buttons, base_path = "", type="tabmenu")]

        if not isinstance(c.site, DefaultSR) and not c.cname:
            toolbar.insert(0, PageNameNav('subreddit'))

        if c.user_is_admin:
            from admin_pages import AdminLinkMenu
            toolbar.append(AdminLinkMenu(self.link))

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

        if self.link.flair_css_class:
            for css_class in self.link.flair_css_class.split():
                classes.add('post-linkflair-' + css_class)

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
                                  c.user.pref_show_link_flair,
                                  c.can_save,
                                  self.max_depth]))

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

        self.max_depth = kw.get('max_depth')

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
            c.can_save = True
            # don't cache if the current user can ban comments in the listing
            try_cache = not sr.can_ban(c.user)
            # don't cache for users with custom hide threshholds
            try_cache &= (c.user.pref_min_comment_score ==
                         Account._defaults["pref_min_comment_score"])

        def renderer():
            builder = CommentBuilder(article, sort, comment=comment,
                                     context=context, num=num, **kw)
            listing = NestedListing(builder, parent_name=article._fullname)
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
                   NamedButton('submitted'),
                   NamedButton('gilded')]

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

        multis = [m for m in LabeledMulti.by_owner(self.user)
                  if m.visibility == "public"]
        if multis:
            scb = SideContentBox(title=_("public multireddits"), content=[
                SidebarMultiList(multis)
            ])
            rb.push(scb)

        mod_sr_ids = Subreddit.reverse_moderator_ids(self.user)
        all_mod_srs = Subreddit._byID(mod_sr_ids, data=True,
                                      return_dict=False)
        mod_srs = [sr for sr in all_mod_srs if sr.can_view(c.user)]
        if mod_srs:
            rb.push(SideContentBox(title=_("moderator of"),
                                   content=[SidebarModList(mod_srs)]))

        if c.user_is_admin:
            from admin_pages import AdminSidebar
            rb.push(AdminSidebar(self.user))
        elif c.user_is_sponsor:
            from admin_pages import SponsorSidebar
            rb.push(SponsorSidebar(self.user))

        if (c.user == self.user or c.user.employee or
            self.user.pref_public_server_seconds):
            seconds_bar = ServerSecondsBar(self.user)
            if seconds_bar.message or seconds_bar.gift_message:
                rb.push(seconds_bar)

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

        Templated.__init__(self)


class SidebarMultiList(Templated):
    def __init__(self, multis):
        Templated.__init__(self)
        multis.sort(key=lambda multi: multi.name.lower())
        self.multis = multis


class SidebarModList(Templated):
    def __init__(self, subreddits):
        Templated.__init__(self)
        # primary sort is desc. subscribers, secondary is name
        self.subreddits = sorted(subreddits,
                                 key=lambda sr: (-sr._ups, sr.name.lower()))


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
                        # Round remaining gold to number of days
                        precision = 60 * 60 * 24
                        self.gold_remaining = timeuntil(self.gold_expiration,
                                                        precision)

                if user.has_paypal_subscription:
                    self.paypal_subscr_id = user.gold_subscr_id
                if user.has_stripe_subscription:
                    self.stripe_customer_id = user.gold_subscr_id

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


class ServerSecondsBar(Templated):
    pennies_per_server_second = {
        datetime.datetime.strptime(datestr, "%Y/%m/%d").date(): v
        for datestr, v in g.live_config['pennies_per_server_second'].iteritems()
    }

    my_message = _("you have helped pay for *%(time)s* of reddit server time.")
    their_message = _("/u/%(user)s has helped pay for *%%(time)s* of reddit server "
                      "time.")

    my_gift_message = _("gifts on your behalf have helped pay for *%(time)s* of "
                        "reddit server time.")
    their_gift_message = _("gifts on behalf of /u/%(user)s have helped pay for "
                           "*%%(time)s* of reddit server time.")

    @classmethod
    def get_rate(cls, dt):
        cutoff_dates = sorted(cls.pennies_per_server_second.keys())
        dt = dt.date()
        key = max(filter(lambda cutoff_date: dt >= cutoff_date, cutoff_dates))
        return cls.pennies_per_server_second[key]

    @classmethod
    def subtract_fees(cls, pennies):
        # for simplicity all payment processor fees are $0.30 + 2.9%
        return pennies * (1 - 0.029) - 30

    @classmethod
    def current_value_of_month(cls):
        price = g.gold_month_price.pennies
        after_fees = cls.subtract_fees(price)
        current_rate = cls.get_rate(datetime.datetime.now(g.display_tz))
        delta = datetime.timedelta(seconds=after_fees / current_rate)
        return precise_format_timedelta(delta, threshold=5, locale=c.locale)

    def make_message(self, seconds, my_message, their_message):
        if not seconds:
            return ''

        delta = datetime.timedelta(seconds=seconds)
        server_time = precise_format_timedelta(delta, threshold=5,
                                                locale=c.locale)
        if c.user == self.user:
            message = my_message
        else:
            message = their_message % {'user': self.user.name}
        return message % {'time': server_time}

    def __init__(self, user):
        Templated.__init__(self)

        self.is_public = user.pref_public_server_seconds
        self.is_user = c.user == user
        self.user = user

        seconds = 0.
        gold_payments = gold_payments_by_user(user)

        for payment in gold_payments:
            rate = self.get_rate(payment.date)
            seconds += self.subtract_fees(payment.pennies) / rate

        try:
            q = (Bid.query().filter(Bid.account_id == user._id)
                    .filter(Bid.status == Bid.STATUS.CHARGE)
                    .filter(Bid.transaction > 0))
            selfserve_payments = list(q)
        except NotFound:
            selfserve_payments = []

        for payment in selfserve_payments:
            rate = self.get_rate(payment.date)
            seconds += self.subtract_fees(payment.charge_amount * 100) / rate
        self.message = self.make_message(seconds, self.my_message,
                                         self.their_message)

        seconds = 0.
        gold_gifts = gold_received_by_user(user)

        for payment in gold_gifts:
            rate = self.get_rate(payment.date)
            pennies = days_to_pennies(payment.days)
            seconds += self.subtract_fees(pennies) / rate
        self.gift_message = self.make_message(seconds, self.my_gift_message,
                                              self.their_gift_message)


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
            if c.user.is_moderator_somewhere:
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


class MultiInfoBar(Templated):
    def __init__(self, multi, srs, user):
        Templated.__init__(self)
        self.multi = wrap_things(multi)[0]
        self.can_edit = multi.can_edit(user)
        self.can_copy = c.user_is_loggedin
        self.can_rename = c.user_is_loggedin and multi.owner == c.user
        srs.sort(key=lambda sr: sr.name.lower())
        self.description_md = multi.description_md
        self.srs = srs

        explore_sr = g.live_config["listing_chooser_explore_sr"]
        if explore_sr:
            self.share_url = "/r/%(sr)s/submit?url=%(url)s" % {
                "sr": explore_sr,
                "url": g.origin + self.multi.path,
            }
        else:
            self.share_url = None


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
        raw_images = ImagesByWikiPage.get_images(c.site, "config/stylesheet")
        images = {name: media_https_if_secure(url)
                  for name, url in raw_images.iteritems()}

        Templated.__init__(self, site = site, images=images,
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
                 recipient, recipient_name, can_subscribe=True):

        if c.user.employee:
            user_creddits = 50
        else:
            user_creddits = c.user.gold_creddits

        Templated.__init__(self, goldtype = goldtype, period = period,
                           months = months, signed = signed,
                           recipient_name = recipient_name,
                           user_creddits = user_creddits,
                           bad_recipient =
                           bool(recipient_name and not recipient),
                           can_subscribe=can_subscribe)


class GoldPayment(Templated):
    def __init__(self, goldtype, period, months, signed,
                 recipient, giftmessage, passthrough, thing,
                 clone_template=False, thing_type=None):
        pay_from_creddits = False
        desc = None

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

        if c.user.employee:
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
            stripe_key = g.STRIPE_PUBLIC_KEY
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

            stripe_key = g.STRIPE_PUBLIC_KEY

        else:
            if months < 12:
                if goldtype == "code":
                    paypal_buttonid = g.PAYPAL_BUTTONID_GIFTCODE_BYMONTH
                else:
                    paypal_buttonid = g.PAYPAL_BUTTONID_CREDDITS_BYMONTH
                quantity = months
                coinbase_name = 'COINBASE_BUTTONID_ONETIME_%sMO' % quantity
                coinbase_button_id = getattr(g, coinbase_name, None)
            else:
                if goldtype == "code":
                    paypal_buttonid = g.PAYPAL_BUTTONID_GIFTCODE_BYYEAR
                else:
                    paypal_buttonid = g.PAYPAL_BUTTONID_CREDDITS_BYYEAR
                quantity = months / 12
                coinbase_name = 'COINBASE_BUTTONID_ONETIME_%sYR' % quantity
                coinbase_button_id = getattr(g, coinbase_name, None)

            if goldtype in ("gift", "code"):
                if months <= user_creddits:
                    pay_from_creddits = True
                elif months >= 12:
                    # If you're not paying with creddits, you have to either
                    # buy by month or spend a multiple of 12 months
                    months = quantity * 12

            if goldtype == "creddits":
                summary = strings.gold_summary_creddits % dict(
                          amount=Score.somethings(months, "month"))
            elif goldtype == "gift":
                if clone_template:
                    if thing_type == "comment":
                        format = strings.gold_summary_gilding_comment
                    elif thing_type == "link":
                        format = strings.gold_summary_gilding_link
                elif thing:
                    if isinstance(thing, Comment):
                        format = strings.gold_summary_gilding_page_comment
                        desc = thing.body
                    else:
                        format = strings.gold_summary_gilding_page_link
                        desc = thing.markdown_link_slow()
                elif signed:
                    format = strings.gold_summary_signed_gift
                else:
                    format = strings.gold_summary_anonymous_gift

                if not clone_template:
                    summary = format % dict(
                        amount=Score.somethings(months, "month"),
                        recipient=recipient and
                                  recipient.name.replace('_', '&#95;'),
                    )
                else:
                    # leave the replacements to javascript
                    summary = format
            elif goldtype == "code":
                summary = strings.gold_summary_gift_code % dict(
                          amount=Score.somethings(months, "month"))
            else:
                raise ValueError("wtf is %r" % goldtype)

            stripe_key = g.STRIPE_PUBLIC_KEY

        Templated.__init__(self, goldtype=goldtype, period=period,
                           months=months, quantity=quantity,
                           unit_price=unit_price, price=price,
                           summary=summary, giftmessage=giftmessage,
                           pay_from_creddits=pay_from_creddits,
                           passthrough=passthrough,
                           thing=thing, clone_template=clone_template,
                           description=desc, thing_type=thing_type,
                           paypal_buttonid=paypal_buttonid,
                           stripe_key=stripe_key,
                           coinbase_button_id=coinbase_button_id)


class GoldSubscription(Templated):
    def __init__(self, user):
        if user.has_stripe_subscription:
            details = get_subscription_details(user)
        else:
            details = None

        if details:
            self.has_stripe_subscription = True
            date = details['next_charge_date']
            next_charge_date = format_date(date, format="short",
                                           locale=c.locale)
            credit_card_last4 = details['credit_card_last4']
            amount = format_currency(float(details['pennies']) / 100, 'USD',
                                     locale=c.locale)
            text = _("you have a credit card gold subscription. your card "
                     "(ending in %(last4)s) will be charged %(amount)s on "
                     "%(date)s.")
            self.text = text % dict(last4=credit_card_last4,
                                    amount=amount,
                                    date=next_charge_date)
            self.user_fullname = user._fullname
        else:
            self.has_stripe_subscription = False

        if user.has_paypal_subscription:
            self.has_paypal_subscription = True
            self.paypal_subscr_id = user.gold_subscr_id
            self.paypal_url = "https://www.paypal.com/cgi-bin/webscr?cmd=_subscr-find&alias=%s" % g.goldthanks_email
        else:
            self.has_paypal_subscription = False

        self.stripe_key = g.STRIPE_PUBLIC_KEY
        Templated.__init__(self)

class CreditGild(Templated):
    """Page for credit card payments for gilding."""
    pass


class GiftGold(Templated):
    """The page to gift reddit gold trophies"""
    def __init__(self, recipient):
        if c.user.employee:
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

class PasswordChangeEmail(Templated):
    """Notification e-mail that a user's password has changed."""
    pass

class EmailChangeEmail(Templated):
    """Notification e-mail that a user's e-mail has changed."""
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
    def __init__(self, captcha=None, url='', title='', text='', selftext='',
                 then='comments', resubmit=False, default_sr=None,
                 extra_subreddits=None, show_link=True, show_self=True):

        self.show_link = show_link
        self.show_self = show_self

        tabs = []
        if show_link:
            tabs.append(('link', ('link-desc', 'url-field')))
        if show_self:
            tabs.append(('text', ('text-desc', 'text-field')))

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

        self.resubmit = resubmit
        self.default_sr = default_sr
        self.extra_subreddits = extra_subreddits

        Templated.__init__(self, captcha = captcha, url = url,
                         title = title, text = text, then = then)

class ShareLink(CachedTemplate):
    def __init__(self, link_name = "", emails = None):
        self.captcha = c.user.needs_captcha()
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

class ContactUs(Templated):
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
            buttons = ["reddit toolbar", "submit", "serendipity!"]
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

class UserTableItem(Templated):
    type = ''
    remove_action = 'unfriend'
    cells = ('user', 'age', 'sendmessage', 'remove')

    @property
    def executed_message(self):
        return _("added")

    def __init__(self, user, editable=True, **kw):
        self.user = user
        self.editable = editable
        Templated.__init__(self, **kw)

    def __repr__(self):
        return '<UserTableItem "%s">' % self.user.name

class RelTableItem(UserTableItem):
    def __init__(self, rel, **kw):
        self._id = rel._id
        self.rel = rel
        UserTableItem.__init__(self, rel._thing2, **kw)

    @property
    def container_name(self):
        return c.site._fullname

class FriendTableItem(RelTableItem):
    type = 'friend'

    @property
    def cells(self):
        if c.user.gold:
            return ('user', 'sendmessage', 'note', 'age', 'remove')
        return ('user', 'sendmessage', 'remove')

    @property
    def container_name(self):
        return c.user._fullname

class EnemyTableItem(RelTableItem):
    type = 'enemy'
    cells = ('user', 'age', 'remove')

    @property
    def container_name(self):
        return c.user._fullname

class BannedTableItem(RelTableItem):
    type = 'banned'
    cells = ('user', 'age', 'sendmessage', 'remove', 'note')

    @property
    def executed_message(self):
        return _("banned")

class WikiBannedTableItem(BannedTableItem):
    type = 'wikibanned'

class ContributorTableItem(RelTableItem):
    type = 'contributor'

class WikiMayContributeTableItem(RelTableItem):
    type = 'wikicontributor'

class InvitedModTableItem(RelTableItem):
    type = 'moderator_invite'
    cells = ('user', 'age', 'permissions', 'permissionsctl')

    @property
    def executed_message(self):
        return _("invited")

    def is_editable(self, user):
        if not c.user_is_loggedin:
            return False
        elif c.user_is_admin:
            return True
        return c.site.is_unlimited_moderator(c.user)

    def __init__(self, rel, editable=True, **kw):
        if editable:
            self.cells += ('remove',)
        editable = self.is_editable(rel._thing2)
        self.permissions = ModeratorPermissions(rel._thing2, self.type,
                                                rel.get_permissions(),
                                                editable=editable)
        RelTableItem.__init__(self, rel, editable=editable, **kw)

class ModTableItem(InvitedModTableItem):
    type = 'moderator'

    @property
    def executed_message(self):
        return _("added")

    def is_editable(self, user):
        if not c.user_is_loggedin:
            return False
        elif c.user_is_admin:
            return True
        return c.user != user and c.site.can_demod(c.user, user)

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

    def render(self, *a, **kw):
        return responsive(CachedTemplate.render(self, *a, **kw), True)

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
            u.update_query(**request.GET.copy())
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
    searchbox          = False

    def __init__(self, nav_menus = None, *a, **kw):
        buttons = [NamedButton('new_promo')]
        if c.user_is_sponsor:
            buttons.append(NamedButton('roadblock'))
            buttons.append(NamedButton('current_promos', dest = ''))
        else:
            buttons.append(NamedButton('my_current_promos', dest = ''))

        if c.user_is_sponsor:
            buttons.append(NavButton('inventory', 'inventory'))
            buttons.append(NavButton('report', 'report'))
            buttons.append(NavButton('underdelivered', 'underdelivered'))
            buttons.append(NavButton('house ads', 'house'))
            buttons.append(NavButton('reported links', 'reported'))

        menu  = NavMenu(buttons, base_path = '/promoted',
                        type='flatlist')

        if nav_menus:
            nav_menus.insert(0, menu)
        else:
            nav_menus = [menu]

        kw['show_sidebar'] = False
        Reddit.__init__(self, nav_menus = nav_menus, *a, **kw)

class PromoteLinkNew(Templated): pass

class PromoteLinkForm(Templated):
    def __init__(self, link, listing, *a, **kw):
        self.setup(link, listing)
        Templated.__init__(self, *a, **kw)

    def setup(self, link, listing):
        self.bids = []
        self.author = Account._byID(link.author_id, data=True)

        if c.user_is_sponsor:
            try:
                bids = Bid.lookup(thing_id=link._id)
            except NotFound:
                pass
            else:
                bids.sort(key=lambda x: x.date, reverse=True)
                bidders = Account._byID(set(bid.account_id for bid in bids),
                                        data=True, return_dict=True)
                for bid in bids:
                    status = Bid.STATUS.name[bid.status].lower()
                    bidder = bidders[bid.account_id]
                    row = Storage(
                        status=status,
                        bidder=bidder.name,
                        date=bid.date,
                        transaction=bid.transaction,
                        campaign=bid.campaign,
                        pay_id=bid.pay_id,
                        amount_str=format_currency(bid.bid, 'USD',
                                                   locale=c.locale),
                        charge_str=format_currency(bid.charge or bid.bid, 'USD',
                                                   locale=c.locale),
                    )
                    self.bids.append(row)

        # determine date range
        now = promote.promo_datetime_now()

        if c.user_is_sponsor:
            mindate = now
        elif promote.is_accepted(link):
            mindate = make_offset_date(now, 1, business_days=True)
        else:
            mindate = make_offset_date(now, g.min_promote_future,
                                       business_days=True)

        if c.user_is_sponsor:
            max_days = 366
        else:
            max_days = g.max_promote_future

        maxstart = now + datetime.timedelta(max_days-1)
        maxend = maxstart + datetime.timedelta(days=1)
        self.maxstart = maxstart.strftime("%m/%d/%Y")
        self.maxend = maxend.strftime("%m/%d/%Y")

        self.startdate = mindate.strftime("%m/%d/%Y")
        enddate = mindate + datetime.timedelta(days=2)
        self.enddate = enddate.strftime("%m/%d/%Y")

        self.subreddit_selector = SubredditSelector()

        self.link = link
        self.listing = listing
        campaigns = list(PromoCampaign._by_link(link._id))
        self.campaigns = RenderableCampaign.from_campaigns(link, campaigns)
        self.promotion_log = PromotionLog.get(link)

        self.min_bid = 0 if c.user_is_sponsor else g.min_promote_bid

        self.priorities = [(p.name, p.text, p.description, p.default, p.inventory_override, p.cpm)
                           for p in sorted(PROMOTE_PRIORITIES.values(), key=lambda p: p.value)]

        # geotargeting
        def location_sort(location_tuple):
            code, name, default = location_tuple
            if code == '':
                return -2
            elif code == 'US':
                return -1
            else:
                return name

        countries = [(code, country['name'], False) for code, country
                                                    in g.locations.iteritems()]
        countries.append(('', _('none'), True))

        self.countries = sorted(countries, key=location_sort)
        self.regions = {}
        self.metros = {}
        for code, country in g.locations.iteritems():
            if 'regions' in country and country['regions']:
                self.regions[code] = [('', _('all'), True)]

                for region_code, region in country['regions'].iteritems():
                    if region['metros']:
                        region_tuple = (region_code, region['name'], False)
                        self.regions[code].append(region_tuple)
                        self.metros[region_code] = []

                        for metro_code, metro in region['metros'].iteritems():
                            metro_tuple = (metro_code, metro['name'], False)
                            self.metros[region_code].append(metro_tuple)
                        self.metros[region_code].sort(key=location_sort)
                self.regions[code].sort(key=location_sort)

        # preload some inventory
        srnames = set()
        for title, names in self.subreddit_selector.subreddit_names:
            srnames.update(names)
        srs = Subreddit._by_name(srnames)
        srs[''] = Frontpage
        inv_start = mindate
        inv_end = mindate + datetime.timedelta(days=14)
        sr_inventory = inventory.get_available_pageviews(
            srs.values(), inv_start, inv_end, datestr=True)

        sr_inventory[''] = sr_inventory[Frontpage.name]
        del sr_inventory[Frontpage.name]
        self.inventory = sr_inventory
        message = _("Need some ideas on how to showcase your brand? "
                    "[Here's a slideshow](%(link)s) on ways brands used "
                    "reddit ads last year.")
        message %= {'link': 'http://www.slideshare.net/MikeCole1/brands-that-were-awesome-on-reddit-2013-30801823'}
        self.infobar = InfoBar(message=message)

        if campaigns:
            subreddits = set()
            budget = 0.
            impressions = 0

            for campaign in campaigns:
                subreddits.add(campaign.sr_name)
                budget += campaign.bid
                if hasattr(campaign, 'cpm') and campaign.priority.cpm:
                    impressions += campaign.impressions

            num_srs = len(subreddits)
            summary = ungettext("this promotion has a total budget of "
                                "%(budget)s for %(impressions)s impressions in "
                                "%(num)s subreddit",
                                "this promotion has a total budget of "
                                "%(budget)s for %(impressions)s impressions in "
                                "%(num)s subreddits",
                                num_srs)
            self.summary = summary % {
                'budget': format_currency(budget, 'USD', locale=c.locale),
                'impressions': format_number(impressions),
                'num': num_srs,
            }
        else:
            self.summary = None

class RenderableCampaign(Templated):
    def __init__(self, link, campaign, transaction, is_pending, is_live,
                 is_complete):
        self.link = link
        self.campaign = campaign
        self.spent = promote.get_spent_amount(campaign)
        self.paid = bool(transaction and not transaction.is_void())
        self.free = campaign.is_freebie()
        self.is_pending = is_pending
        self.is_live = is_live
        self.is_complete = is_complete
        self.needs_refund = (is_complete and c.user_is_sponsor and
                             not transaction.is_refund() and
                             self.spent < campaign.bid)
        self.pay_url = promote.pay_url(link, campaign)
        self.view_live_url = promote.view_live_url(link, campaign.sr_name)
        self.refund_url = promote.refund_url(link, campaign)

        if campaign.location:
            country = campaign.location.country or ''
            region = campaign.location.region or ''
            metro = campaign.location.metro or ''
            pieces = [country, region]
            if metro:
                metro_str = (g.locations[country]['regions'][region]
                             ['metros'][metro]['name'])
                pieces.append(metro_str)
            pieces = filter(lambda i: i, pieces)
            self.geotarget = '/'.join(pieces)
            self.country, self.region, self.metro = country, region, metro
        else:
            self.geotarget = ''
            self.country, self.region, self.metro = '', '', ''

        Templated.__init__(self)

    @classmethod
    def from_campaigns(cls, link, campaigns):
        campaigns, is_single = tup(campaigns, ret_is_single=True)
        transactions = promote.get_transactions(link, campaigns)
        live_campaigns = promote.live_campaigns_by_link(link)
        today = promote.promo_datetime_now().date()

        ret = []
        for camp in campaigns:
            transaction = transactions.get(camp._id)
            is_pending = today < to_date(camp.start_date)
            is_live = camp in live_campaigns
            is_complete = (transaction and (transaction.is_charged() or
                                            transaction.is_refund()) and
                           not (is_live or is_pending))
            rc = cls(link, camp, transaction, is_pending, is_live, is_complete)
            ret.append(rc)
        if is_single:
            return ret[0]
        else:
            return ret

    def render_html(self):
        return spaceCompress(self.render(style='html'))


class RefundPage(Reddit):
    def __init__(self, link, campaign):
        self.link = link
        self.campaign = campaign
        self.listing = wrap_links(link, skip=False)
        billable_impressions = promote.get_billable_impressions(campaign)
        billable_amount = promote.get_billable_amount(campaign,
                                                      billable_impressions)
        refund_amount = promote.get_refund_amount(campaign, billable_amount)
        self.billable_impressions = billable_impressions
        self.billable_amount = billable_amount
        self.refund_amount = refund_amount
        self.traffic_url = '/traffic/%s/%s' % (link._id36, campaign._id36)
        Reddit.__init__(self, title="refund", show_sidebar=False)


class Roadblocks(Templated):
    def __init__(self):
        self.roadblocks = PromotedLinkRoadblock.get_roadblocks()
        Templated.__init__(self)
        # reference "now" to what we use for promtions
        now = promote.promo_datetime_now()

        startdate = now + datetime.timedelta(1)
        enddate   = startdate + datetime.timedelta(1)

        self.startdate = startdate.strftime("%m/%d/%Y")
        self.enddate   = enddate  .strftime("%m/%d/%Y")


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
    if not c.secure:
        media_object = item.media_object
    else:
        media_object = item.secure_media_object

    if media_object:
        media_embed = None
        if isinstance(media_object, basestring):
            media_embed = media_object
        else:
            try:
                media_embed = media.get_media_embed(media_object)
            except TypeError:
                g.log.warning("link %s has a bad media object" % item)
                media_embed = None

            if media_embed:
                should_authenticate = (item.subreddit.type == "private")
                media_embed =  MediaEmbed(media_domain = g.media_domain,
                                          height = media_embed.height + 10,
                                          width = media_embed.width + 10,
                                          scrolling = media_embed.scrolling,
                                          id36 = item._id36,
                                          authenticated=should_authenticate,
                                        )
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

    def __init__(self, *args, **kwargs):
        authenticated = kwargs.pop("authenticated", False)
        if authenticated:
            mac = hmac.new(g.secrets["media_embed"], kwargs["id36"],
                           hashlib.sha1)
            self.credentials = "/" + mac.hexdigest()
        else:
            self.credentials = ""
        Templated.__init__(self, *args, **kwargs)


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
                 textarea_class = '',
                 name = "text",
                 expunged=False,
                 include_errors=True):

        css_class = "usertext"
        if cloneable:
            css_class += " cloneable"
        if extra_css:
            css_class += " " + extra_css

        if text is None:
            text = ''

        fullname = ''
        # Do not pass fullname on deleted things, unless we're admin
        if hasattr(item, '_fullname'):
            if not getattr(item, 'deleted', False) or c.user_is_admin:
                fullname = item._fullname

        CachedTemplate.__init__(self,
                                fullname = fullname,
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
                                textarea_class = textarea_class,
                                name = name,
                                expunged=expunged,
                                include_errors=include_errors)

class MediaEmbedBody(CachedTemplate):
    """What's rendered inside the iframe that contains media objects"""
    def render(self, *a, **kw):
        res = CachedTemplate.render(self, *a, **kw)
        return responsive(res, True)


class PaymentForm(Templated):
    def __init__(self, link, campaign, **kw):
        self.link = link
        self.duration = strings.time_label
        self.duration %= {'num': campaign.ndays,
                          'time': ungettext("day", "days", campaign.ndays)}
        self.start_date = campaign.start_date.strftime("%m/%d/%Y")
        self.end_date = campaign.end_date.strftime("%m/%d/%Y")
        self.campaign_id36 = campaign._id36
        self.budget = format_currency(float(campaign.bid), 'USD',
                                      locale=c.locale)
        Templated.__init__(self, **kw)

class Promotion_Summary(Templated):
    def __init__(self, ndays):
        end_date = promote.promo_datetime_now().date()
        start_date = promote.promo_datetime_now(offset = -ndays).date()

        pws = PromotionWeights.get_campaigns(start_date,
                                             end_date + datetime.timedelta(1))
        campaign_ids = {pw.promo_idx for pw in pws}
        campaigns = PromoCampaign._byID(campaign_ids, data=True,
                                        return_dict=False)
        link_ids = {camp.link_id for camp in campaigns}
        link_names = {Link._fullname_from_id36(to36(id)) for id in link_ids}
        wrapped_links = wrap_links(link_names)
        wrapped_links_by_id = {link._id: link for link in wrapped_links}
        account_ids = {camp.owner_id for camp in campaigns}
        accounts_by_id = Account._byID(account_ids, data=True)

        links = set()
        total = 0
        for campaign in campaigns:
            if not campaign.trans_id or campaign.trans_id <= 0:
                continue

            link = wrapped_links_by_id[campaign.link_id]
            if not promote.is_accepted(link):
                continue

            link.bid = getattr(link, "bid", 0)
            link.bid += (campaign.bid - getattr(campaign, 'refund_amount', 0))
            link.ncampaigns = getattr(link, "ncampaigns", 0) + 1
            links.add(link)

            # calculate portion of this campaign's budget to include, assuming
            # even delivery
            bid_per_day = campaign.bid / campaign.ndays
            sd = max(start_date, campaign.start_date.date())
            ed = min(end_date, campaign.end_date.date())
            total += bid_per_day * (ed - sd).days

        links = list(links)
        links.sort(key = lambda x: x._score, reverse = True)

        self.links = links
        self.ndays = ndays
        self.total = total
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


class PromoteInventory(Templated):
    def __init__(self, start, end, sr):
        Templated.__init__(self)
        self.start = start
        self.end = end
        self.sr = sr
        self.sr_name = '' if isinstance(sr, DefaultSR) else sr.name
        self.setup()

    def setup(self):
        campaigns_by_date = inventory.get_campaigns_by_date(self.sr, self.start,
                                                            self.end)
        link_ids = {camp.link_id for camp
                    in chain.from_iterable(campaigns_by_date.itervalues())}
        links_by_id = Link._byID(link_ids, data=True)
        dates = inventory.get_date_range(self.start, self.end)
        imps_by_link_by_date = defaultdict(lambda: dict.fromkeys(dates, 0))
        total_by_date = dict.fromkeys(dates, 0)
        for date, campaigns in campaigns_by_date.iteritems():
            for camp in campaigns:
                link = links_by_id[camp.link_id]
                daily_impressions = camp.impressions / camp.ndays
                imps_by_link_by_date[link._id][date] += daily_impressions
                total_by_date[date] += daily_impressions

        account_ids = {link.author_id for link in links_by_id.itervalues()}
        accounts_by_id = Account._byID(account_ids, data=True)

        self.header = ['link'] + [date.strftime("%m/%d/%Y") for date in dates]
        rows = []
        for link_id, imps_by_date in imps_by_link_by_date.iteritems():
            link = links_by_id[link_id]
            author = accounts_by_id[link.author_id]
            info = {
                'author': author.name,
                'edit_url': promote.promo_edit_url(link),
            }
            row = Storage(info=info, is_total=False)
            row.columns = [format_number(imps_by_date[date]) for date in dates]
            rows.append(row)
        rows.sort(key=lambda row: row.info['author'].lower())

        total_row = Storage(
            info={'title': 'total'},
            is_total=True,
            columns=[format_number(total_by_date[date]) for date in dates],
        )
        rows.append(total_row)

        predicted_by_date = inventory.get_predicted_pageviews(self.sr,
                                            self.start, self.end)
        predicted_row = Storage(
            info={'title': 'predicted'},
            is_total=True,
            columns=[format_number(predicted_by_date[date]) for date in dates],
        )
        rows.append(predicted_row)

        remaining_by_date = {date: predicted_by_date[date] - total_by_date[date]
                             for date in dates}
        remaining_row = Storage(
            info={'title': 'remaining'},
            is_total=True,
            columns=[format_number(remaining_by_date[date]) for date in dates],
        )
        rows.append(remaining_row)

        self.rows = rows

class PromoteReport(Templated):
    def __init__(self, links, link_text, owner_name, bad_links, start, end):
        self.links = links
        self.start = start
        self.end = end
        if links:
            self.make_reports()
            p = request.GET.copy()
            self.csv_url = '%s.csv?%s' % (request.path, urlencode(p))
        else:
            self.link_report = []
            self.campaign_report = []
            self.csv_url = None

        Templated.__init__(self, link_text=link_text, owner_name=owner_name,
                           bad_links=bad_links)

    def as_csv(self):
        out = cStringIO.StringIO()
        writer = csv.writer(out)

        writer.writerow((_("start date"), self.start.strftime('%m/%d/%Y')))
        writer.writerow((_("end date"), self.end.strftime('%m/%d/%Y')))
        writer.writerow([])
        writer.writerow((_("links"),))
        writer.writerow((
            _("id"),
            _("owner"),
            _("url"),
            _("comments"),
            _("upvotes"),
            _("downvotes"),
            _("clicks"),
            _("impressions"),
        ))
        for row in self.link_report:
            writer.writerow((row['id36'], row['owner'], row['url'],
                             row['comments'], row['upvotes'], row['downvotes'],
                             row['clicks'], row['impressions']))

        writer.writerow([])
        writer.writerow((_("campaigns"),))
        writer.writerow((
            _("link id"),
            _("owner"),
            _("campaign id"),
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

    def make_reports(self):
        self.make_campaign_report()
        self.make_link_report()

    def make_link_report(self):
        link_report = []
        owners = Account._byID([link.author_id for link in self.links],
                               data=True)

        for link in self.links:
            row = {
                'id36': link._id36,
                'owner': owners[link.author_id].name,
                'comments': link.num_comments,
                'upvotes': link._ups,
                'downvotes': link._downs,
                'clicks': self.clicks_by_link.get(link._id36, 0),
                'impressions': self.impressions_by_link.get(link._id36, 0),
                'url': link.url,
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
            if not (campaign_start <= date < campaign_end):
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
                        not promote.charged_or_not_needed(camp))

        campaigns = [camp for camp in campaigns if keep_camp(camp)]
        fp_imps, sr_imps = self.get_imps(campaigns, self.start, self.end)
        fp_clicks, sr_clicks = self.get_clicks(campaigns, self.start, self.end)
        owners = Account._byID([link.author_id for link in self.links],
                               data=True)
        links_by_id = {link._id: link for link in self.links}
        campaign_report = []
        self.clicks_by_link = Counter()
        self.impressions_by_link = Counter()

        for camp in campaigns:
            link = links_by_id[camp.link_id]
            fullname = camp._fullname
            effective_duration = (min(camp.end_date, self.end)
                                  - max(camp.start_date, self.start)).days
            bid = camp.bid * (float(effective_duration) / camp.ndays)
            row = {
                'link': link._id36,
                'owner': owners[link.author_id].name,
                'campaign': camp._id36,
                'target': camp.sr_name or 'frontpage',
                'bid': format_currency(bid, 'USD', locale=c.locale),
                'fp_impressions': fp_imps[fullname],
                'sr_impressions': sr_imps[fullname],
                'fp_clicks': fp_clicks[fullname],
                'sr_clicks': sr_clicks[fullname],
                'total_impressions': fp_imps[fullname] + sr_imps[fullname],
                'total_clicks': fp_clicks[fullname] + sr_clicks[fullname],
            }
            self.clicks_by_link[link._id36] += row['total_clicks']
            self.impressions_by_link[link._id36] += row['total_impressions']
            campaign_report.append(row)
        self.campaign_report = sorted(campaign_report, key=lambda r: r['link'])

class InnerToolbarFrame(Templated):
    def __init__(self, link, url, expanded=False):
        Templated.__init__(self, link=link, url=url, expanded=expanded)

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
        self.my_apps = OAuth2Client._by_user_grouped(c.user)
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
                 latest_available_data=None, classes=[],
                 make_period_link=None):
        self.id = id
        self.title = title
        self.interval = interval
        self.columns = columns
        self.rows = rows
        self.latest_available_data = (latest_available_data or
                                      datetime.datetime.utcnow())
        self.classes = " ".join(classes)
        self.make_period_link = make_period_link

        Templated.__init__(self)

class InterestBar(Templated):
    def __init__(self, has_subscribed):
        self.has_subscribed = has_subscribed
        Templated.__init__(self)

class Goldvertisement(Templated):
    def __init__(self):
        now = datetime.datetime.now(GOLD_TIMEZONE)
        today = now.date()
        tomorrow = today + datetime.timedelta(days=1)
        end_time = datetime.datetime(tomorrow.year,
                                     tomorrow.month,
                                     tomorrow.day,
                                     tzinfo=GOLD_TIMEZONE)
        revenue_today = gold_revenue_volatile(today)
        yesterday = today - datetime.timedelta(days=1)
        revenue_yesterday = gold_revenue_steady(yesterday)
        revenue_goal = float(gold_goal_on(today))
        revenue_goal_yesterday = float(gold_goal_on(yesterday))

        self.percent_filled = int((revenue_today / revenue_goal) * 100)
        self.percent_filled_yesterday = int((revenue_yesterday /
                                             revenue_goal_yesterday) * 100)
        self.hours_paid = ServerSecondsBar.current_value_of_month()
        self.time_left_today = timeuntil(end_time, precision=60)
        if c.user.employee:
            self.goal_today = revenue_goal / 100.0
            self.goal_yesterday = revenue_goal_yesterday / 100.0
        Templated.__init__(self)

class LinkCommentsSettings(Templated):
    def __init__(self, link):
        Templated.__init__(self)
        sr = link.subreddit_slow
        self.link = link
        self.is_author = c.user_is_loggedin and c.user._id == link.author_id
        self.contest_mode = link.contest_mode
        self.stickied = link._fullname == sr.sticky_fullname
        self.sendreplies = link.sendreplies
        self.can_edit = (c.user_is_loggedin
                           and (c.user_is_admin or
                                sr.is_moderator(c.user)))

class ModeratorPermissions(Templated):
    def __init__(self, user, permissions_type, permissions,
                 editable=False, embedded=False):
        self.user = user
        self.permissions = permissions
        Templated.__init__(self, permissions_type=permissions_type,
                           editable=editable, embedded=embedded)

    def items(self):
        return self.permissions.iteritems()

class ListingChooser(Templated):
    def __init__(self):
        Templated.__init__(self)
        self.sections = defaultdict(list)
        self.add_item("global", _("subscribed"), site=Frontpage,
                      description=_("your front page"))
        self.add_item("global", _("explore"), path="/explore")
        self.add_item("other", _("everything"), site=All,
                      description=_("from all subreddits"))
        if c.user_is_loggedin and c.user.is_moderator_somewhere:
            self.add_item("other", _("moderating"), site=Mod,
                          description=_("subreddits you mod"))

        self.add_item("other", _("saved"), path='/user/%s/saved' % c.user.name)

        gold_multi = g.live_config["listing_chooser_gold_multi"]
        if c.user_is_loggedin and c.user.gold and gold_multi:
            self.add_item("other", name=_("gold perks"), path=gold_multi,
                          extra_class="gold-perks")

        self.show_samples = False
        if c.user_is_loggedin:
            multis = LabeledMulti.by_owner(c.user)
            multis.sort(key=lambda multi: multi.name.lower())
            for multi in multis:
                self.add_item("multi", multi.name, site=multi)

            explore_sr = g.live_config["listing_chooser_explore_sr"]
            if explore_sr:
                self.add_item("multi", name=_("explore multis"),
                              site=Subreddit._by_name(explore_sr))

            self.show_samples = not multis

        if self.show_samples:
            self.add_samples()

        self.selected_item = self.find_selected()
        if self.selected_item:
            self.selected_item["selected"] = True

    def add_item(self, section, name, path=None, site=None, description=None,
                 extra_class=None):
        self.sections[section].append({
            "name": name,
            "description": description,
            "path": path or site.user_path,
            "site": site,
            "selected": False,
            "extra_class": extra_class,
        })

    def add_samples(self):
        for path in g.live_config["listing_chooser_sample_multis"]:
            self.add_item(
                section="sample",
                name=path.rpartition('/')[2],
                path=path,
            )

    def find_selected(self):
        path = request.path
        matching = []
        for item in chain(*self.sections.values()):
            if item["site"]:
                if item["site"] == c.site:
                    matching.append(item)
            elif path.startswith(item["path"]):
                matching.append(item)

        matching.sort(key=lambda item: len(item["path"]), reverse=True)
        return matching[0] if matching else None

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


class SubscribeButton(Templated):
    def __init__(self, sr, bubble_class=None):
        Templated.__init__(self)
        self.sr = sr
        self.data_attrs = {"sr_name": sr.name}
        if bubble_class:
            self.data_attrs["bubble_class"] = bubble_class


class SubredditSelector(Templated):
    def __init__(self, default_sr=None, extra_subreddits=None, required=False,
                 include_searches=True):
        Templated.__init__(self)

        if extra_subreddits:
            self.subreddits = extra_subreddits
        else:
            self.subreddits = []

        self.subreddits.append((
            _('popular choices'),
            Subreddit.user_subreddits(c.user, ids=False)
        ))

        self.default_sr = default_sr
        self.required = required
        if include_searches:
            self.sr_searches = simplejson.dumps(
                popular_searches(include_over_18=c.over18)
            )
        else:
            self.sr_searches = simplejson.dumps({})
        self.include_searches = include_searches

    @property
    def subreddit_names(self):
        groups = []
        for title, subreddits in self.subreddits:
            names = [sr.name for sr in subreddits if sr.can_submit(c.user)]
            names.sort(key=str.lower)
            groups.append((title, names))
        return groups


class ListingSuggestions(Templated):
    def __init__(self):
        self.suggestion_type = None
        if c.default_sr:
            multis = c.user_is_loggedin and LabeledMulti.by_owner(c.user)

            if multis and c.site in multis:
                multis.remove(c.site)

            if multis:
                self.suggestion_type = "multis"
                if len(multis) <= 3:
                    self.suggestions = multis
                else:
                    self.suggestions = random.sample(multis, 3)
            else:
                self.suggestion_type = "random"

        Templated.__init__(self)


class ExploreItem(Templated):
    """For managing recommended content."""

    def __init__(self, item_type, rec_src, sr, link, comment=None):
        """Constructor.

        item_type - string that helps templates know how to render this item.
        rec_src - code that lets us track where the rec originally came from,
            useful for comparing performance of data sources or algorithms
        sr and link are required
        comment is optional
        
        See r2.lib.recommender for valid values of item_type and rec_src.

        """
        self.sr = sr
        self.link = link
        self.comment = comment
        self.type = item_type
        self.src = rec_src
        Templated.__init__(self)

    def is_over18(self):
        return (self.sr.over_18 or
                self.link.over_18 or
                Link._nsfw.findall(self.link.title))


class ExploreItemListing(Templated):
    def __init__(self, recs, settings):
        self.things = []
        self.settings = settings
        if recs:
            links, srs = zip(*[(rec.link, rec.sr) for rec in recs])
            wrapped_links = {l._id: l for l in wrap_links(links).things}
            wrapped_srs = {sr._id: sr for sr in wrap_things(*srs)}
            for rec in recs:
                if rec.link._id in wrapped_links:
                    rec.link = wrapped_links[rec.link._id]
                    rec.sr = wrapped_srs[rec.sr._id]
                    self.things.append(rec)
        Templated.__init__(self)
