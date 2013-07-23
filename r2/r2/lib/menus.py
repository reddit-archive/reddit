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

from wrapped import CachedTemplate, Styled
from pylons import c, request, g
from utils import  query_string, timeago
from strings import StringHandler, plurals
from r2.lib.db import operators
import r2.lib.search as search
from r2.lib.filters import _force_unicode
from pylons.i18n import _, N_



class MenuHandler(StringHandler):
    """Bastard child of StringHandler and plurals.  Menus are
    typically a single word (and in some cases, a single plural word
    like 'moderators' or 'contributors' so this class first checks its
    own dictionary of string translations before falling back on the
    plurals list."""
    def __getattr__(self, attr):
        try:
            return StringHandler.__getattr__(self, attr)
        except KeyError:
            return getattr(plurals, attr)

# translation strings for every menu on the site
menu =   MenuHandler(hot          = _('hot'),
                     new          = _('new'),
                     old          = _('old'),
                     ups          = _('ups'),
                     downs        = _('downs'),
                     top          = _('top'),
                     more         = _('more'),
                     relevance    = _('relevance'),
                     controversial  = _('controversial'),
                     confidence   = _('best'),
                     random       = _('random'),
                     saved        = _('saved {toolbar}'),
                     recommended  = _('recommended'),
                     rising       = _('rising'), 
                     admin        = _('admin'), 
                                 
                     # time sort words
                     hour         = _('this hour'),
                     day          = _('today'),
                     week         = _('this week'),
                     month        = _('this month'),
                     year         = _('this year'),
                     all          = _('all time'),
                                  
                     # "kind" words
                     spam         = _("spam"),
                     autobanned   = _("autobanned"),

                     # reddit header strings
                     prefs        = _("preferences"), 
                     submit       = _("submit"),
                     wiki         = _("wiki"),
                     blog         = _("blog"),
                     logout       = _("logout"),
                     
                     #reddit footer strings
                     feedback     = _("contact us"),
                     buttons      = _("buttons"),
                     widget       = _("widget"), 
                     code         = _("source code"),
                     mobile       = _("mobile"), 
                     store        = _("store"),  
                     ad_inq       = _("advertise"),
                     gold         = _('reddit gold'),
                     reddits      = _('subreddits'),
                     team         = _('team'),
                     rules        = _('rules'),

                     #preferences
                     options      = _('options'),
                     apps         = _("apps"),
                     feeds        = _("RSS feeds"),
                     friends      = _("friends"),
                     update       = _("password/email"),
                     delete       = _("delete"),
                     otp          = _("two-factor authentication"),

                     # messages
                     compose      = _("compose"),
                     inbox        = _("inbox"),
                     sent         = _("sent"),

                     # comments
                     comments     = _("comments {toolbar}"),
                     related      = _("related"),
                     details      = _("details"),
                     duplicates   = _("other discussions (%(num)s)"),
                     traffic      = _("traffic stats"),
                     stylesheet   = _("stylesheet"),

                     # reddits
                     home         = _("home"),
                     about        = _("about"),
                     edit_subscriptions = _("edit subscriptions"),
                     community_settings = _("subreddit settings"),
                     moderators   = _("edit moderators"),
                     modmail      = _("moderator mail"),
                     contributors = _("edit approved submitters"),
                     banned       = _("ban users"),
                     banusers     = _("ban users"),
                     flair        = _("edit flair"),
                     log          = _("moderation log"),
                     modqueue     = _("moderation queue"),
                     unmoderated  = _("unmoderated links"),
                     
                     wikibanned        = _("ban wiki contributors"),
                     wikicontributors  = _("add wiki contributors"),
                     
                     wikirecentrevisions = _("recent wiki revisions"),
                     wikipageslist = _("wiki page list"),

                     popular      = _("popular"),
                     create       = _("create"),
                     mine         = _("my subreddits"),

                     i18n         = _("help translate"),
                     errors       = _("errors"),
                     awards       = _("awards"),
                     ads          = _("ads"),
                     promoted     = _("promoted"),
                     reporters    = _("reporters"),
                     reports      = _("reports"),
                     reportedauth = _("reported authors"),
                     info         = _("info"),
                     share        = _("share"),

                     overview     = _("overview"),
                     submitted    = _("submitted"),
                     liked        = _("liked"),
                     disliked     = _("disliked"),
                     hidden       = _("hidden {toolbar}"),
                     deleted      = _("deleted"),
                     reported     = _("reported"),
                     voting       = _("voting"),

                     promote        = _('self-serve advertising'),
                     new_promo      = _('create promotion'),
                     my_current_promos = _('my promoted links'),
                     current_promos = _('all promoted links'),
                     all_promos     = _('all'),
                     future_promos  = _('unseen'),
                     roadblock      = _('roadblock'),
                     graph          = _('analytics'),
                     admin_graph = _('admin analytics'),
                     live_promos    = _('live'),
                     unpaid_promos  = _('unpaid'),
                     pending_promos = _('pending'),
                     rejected_promos = _('rejected'),

                     sitewide = _('sitewide'),
                     languages = _('languages'),
                     adverts = _('adverts'),

                     whitelist = _("whitelist")
                     )

def menu_style(type):
    """Simple manager function for the styled menus.  Returns a
    (style, css_class) pair given a 'type', defaulting to style =
    'dropdown' with no css_class."""
    default = ('dropdown', '')
    d = dict(heavydrop = ('dropdown', 'heavydrop'),
             lightdrop = ('dropdown', 'lightdrop'),
             tabdrop = ('dropdown', 'tabdrop'),
             srdrop = ('dropdown', 'srdrop'),
             flatlist =  ('flatlist', 'flat-list'),
             tabmenu = ('tabmenu', ''),
             formtab = ('tabmenu', 'formtab'),
             flat_vert = ('flatlist', 'flat-vert'),
             )
    return d.get(type, default)

class NavMenu(Styled):
    """generates a navigation menu.  The intention here is that the
    'style' parameter sets what template/layout to use to differentiate, say,
    a dropdown from a flatlist, while the optional _class, and _id attributes
    can be used to set individualized CSS."""

    use_post = False

    def __init__(self, options, default = None, title = '', type = "dropdown",
                 base_path = '', separator = '|', **kw):
        self.options = options
        self.base_path = base_path

        #add the menu style, but preserve existing css_class parameter
        kw['style'], css_class = menu_style(type)
        kw['css_class'] = css_class + ' ' + kw.get('css_class', '')

        #used by flatlist to delimit menu items
        self.separator = separator

        # since the menu contains the path info, it's buttons need a
        # configuration pass to get them pointing to the proper urls
        for opt in self.options:
            opt.build(self.base_path)

        # selected holds the currently selected button defined as the
        # one whose path most specifically matches the current URL
        # (possibly None)
        self.default = default
        self.selected = self.find_selected()

        Styled.__init__(self, title = title, **kw)

    def find_selected(self):
        maybe_selected = [o for o in self.options if o.is_selected()]
        if maybe_selected:
            # pick the button with the most restrictive pathing
            maybe_selected.sort(lambda x, y:
                                len(y.bare_path) - len(x.bare_path))
            return maybe_selected[0]
        elif self.default:
            #lookup the menu with the 'dest' that matches 'default'
            for opt in self.options:
                if opt.dest == self.default:
                    return opt

    def __iter__(self):
        for opt in self.options:
            yield opt

class NavButton(Styled):
    """Smallest unit of site navigation.  A button once constructed
    must also have its build() method called with the current path to
    set self.path.  This step is done automatically if the button is
    passed to a NavMenu instance upon its construction."""
    def __init__(self, title, dest, sr_path = True, 
                 nocname=False, opt = '', aliases = [],
                 target = "", style = "plain", **kw):
        # keep original dest to check against c.location when rendering
        aliases = set(_force_unicode(a.rstrip('/')) for a in aliases)
        if dest:
            aliases.add(_force_unicode(dest.rstrip('/')))

        self.request_params = dict(request.GET)
        self.stripped_path = _force_unicode(request.path.rstrip('/').lower())

        Styled.__init__(self, style = style, sr_path = sr_path, 
                        nocname = nocname, target = target,
                        aliases = aliases, dest = dest,
                        selected = False, 
                        title = title, opt = opt, **kw)

    def build(self, base_path = ''):
        '''Generates the href of the button based on the base_path provided.'''

        # append to the path or update the get params dependent on presence
        # of opt 
        if self.opt:
            p = self.request_params.copy()
            if self.dest:
                p[self.opt] = self.dest
            elif self.opt in p:
                del p[self.opt]
        else:
            p = {}
            base_path = ("%s/%s/" % (base_path, self.dest)).replace('//', '/')

        self.action_params = p

        self.bare_path = _force_unicode(base_path.replace('//', '/')).lower()
        self.bare_path = self.bare_path.rstrip('/')
        self.base_path = base_path
        
        # append the query string
        base_path += query_string(p)
        
        # since we've been sloppy of keeping track of "//", get rid
        # of any that may be present
        self.path = base_path.replace('//', '/')

    def is_selected(self):
        """Given the current request path, would the button be selected."""
        if self.opt:
            if not self.dest and self.opt not in self.request_params:
                return True
            return self.request_params.get(self.opt, '') in self.aliases
        else:
            if self.stripped_path == self.bare_path:
                return True
            site_path = c.site.user_path.lower() + self.bare_path
            if self.sr_path and self.stripped_path == site_path:
                return True
            if self.bare_path and self.stripped_path.startswith(self.bare_path):
                return True
            if self.stripped_path in self.aliases:
                return True

    def selected_title(self):
        """returns the title of the button when selected (for cases
        when it is different from self.title)"""
        return self.title

class ModeratorMailButton(NavButton):
    def is_selected(self):
        if c.default_sr and not self.sr_path:
            return NavButton.is_selected(self)
        elif not c.default_sr and self.sr_path:
            return NavButton.is_selected(self)

class OffsiteButton(NavButton):
    def build(self, base_path = ''):
        self.sr_path = False
        self.path = self.bare_path = self.dest

    def cachable_attrs(self):
        return [('path', self.path), ('title', self.title)]

class SubredditButton(NavButton):
    from r2.models.subreddit import Frontpage, Mod, All, Random, RandomSubscription
    # Translation is deferred (N_); must be done per-request,
    # not at import/class definition time.
    # TRANSLATORS: This refers to /r/mod
    name_overrides = {Mod: N_("mod"),
    # TRANSLATORS: This refers to the user's front page
                      Frontpage: N_("front"),
                      All: N_("all"),
                      Random: N_("random"),
    # TRANSLATORS: Gold feature, "myrandom", a random subreddit from your subscriptions
                      RandomSubscription: N_("myrandom")}

    def __init__(self, sr, **kw):
        self.path = sr.path
        name = self.name_overrides.get(sr)
        # Run the name through deferred translation
        name = _(name) if name else sr.name
        NavButton.__init__(self, name, sr.path, False,
                           isselected = (c.site == sr), **kw)

    def build(self, base_path = ''):
        self.bare_path = ""

    def is_selected(self):
        return self.isselected

    def cachable_attrs(self):
        return [('path', self.path), ('title', self.title),
                ('isselected', self.isselected)]

class NamedButton(NavButton):
    """Convenience class for handling the majority of NavButtons
    whereby the 'title' is just the translation of 'name' and the
    'dest' defaults to the 'name' as well (unless specified
    separately)."""
    
    def __init__(self, name, sr_path = True, nocname=False, dest = None, fmt_args = {}, **kw):
        self.name = name.strip('/')
        menutext = menu[self.name] % fmt_args
        NavButton.__init__(self, menutext, name if dest is None else dest,
                           sr_path = sr_path, nocname=nocname, **kw)

class JsButton(NavButton):
    """A button which fires a JS event and thus has no path and cannot
    be in the 'selected' state"""
    def __init__(self, title, style = 'js', tab_name = None, **kw):
        NavButton.__init__(self, title, '#', style = style, tab_name = tab_name,
                           **kw)

    def build(self, *a, **kw):
        if self.tab_name:
            self.path = '#' + self.tab_name
        else:
            self.path = 'javascript:void(0)'

    def is_selected(self):
        return False

class PageNameNav(Styled):
    """generates the links and/or labels which live in the header
    between the header image and the first nav menu (e.g., the
    subreddit name, the page name, etc.)"""
    pass

class SimplePostMenu(NavMenu):
    """Parent class of menus used for sorting and time sensitivity of
    results. Defines a type of menu that uses hidden forms to POST the user's
    selection to a handler that may commit the user's choice as a preference
    change before redirecting to a URL that also includes the user's choice.
    If other user's load this URL, they won't affect their own preferences, but
    the given choice will apply for that page load.

    The value of the POST/GET parameter must be one of the entries in
    'cls.options'.  This parameter is also used to construct the list
    of NavButtons contained in this Menu instance.  The goal here is
    to have a menu object which 'out of the box' is self validating."""
    options   = []
    hidden_options = []
    name      = ''
    title     = ''
    default = None
    type = 'lightdrop'

    def __init__(self, **kw):
        buttons = []
        for name in self.options:
            css_class = 'hidden' if name in self.hidden_options else ''
            button = NavButton(self.make_title(name), name, opt=self.name,
                               style='post', css_class=css_class)
            buttons.append(button)

        kw['default'] = kw.get('default', self.default)
        kw['base_path'] = kw.get('base_path') or request.path
        NavMenu.__init__(self, buttons, type = self.type, **kw)

    def make_title(self, attr):
        return menu[attr]

    @classmethod
    def operator(self, sort):
        """Converts the opt into a DB-esque operator used for sorting results"""
        return None

class SortMenu(SimplePostMenu):
    """The default sort menu."""
    name      = 'sort'
    default   = 'hot'
    options   = ('hot', 'new', 'top', 'old', 'controversial')

    def __init__(self, **kw):
        kw['title'] = _("sorted by")
        SimplePostMenu.__init__(self, **kw)

    @classmethod
    def operator(self, sort):
        if sort == 'hot':
            return operators.desc('_hot')
        elif sort == 'new':
            return operators.desc('_date')
        elif sort == 'old':
            return operators.asc('_date')
        elif sort == 'top':
            return operators.desc('_score')
        elif sort == 'controversial':
            return operators.desc('_controversy')
        elif sort == 'confidence':
            return operators.desc('_confidence')
        elif sort == 'random':
            return operators.shuffled('_confidence')

class ProfileSortMenu(SortMenu):
    default   = 'new'
    options   = ('hot', 'new', 'top', 'controversial')

class CommentSortMenu(SortMenu):
    """Sort menu for comments pages"""
    default   = 'confidence'
    options   = ('confidence', 'top', 'new', 'hot', 'controversial', 'old',
                 'random')
    hidden_options = ('random',)
    use_post  = True

class SearchSortMenu(SortMenu):
    """Sort menu for search pages."""
    default   = 'relevance'
    mapping   = search.sorts
    options   = mapping.keys()

    @classmethod
    def operator(cls, sort):
        return cls.mapping.get(sort, cls.mapping[cls.default])

class RecSortMenu(SortMenu):
    """Sort menu for recommendation page"""
    default   = 'new'
    options   = ('hot', 'new', 'top', 'controversial', 'relevance')

class KindMenu(SimplePostMenu):
    name    = 'kind'
    default = 'all'
    options = ('links', 'comments', 'messages', 'all')

    def __init__(self, **kw):
        kw['title'] = _("kind")
        SimplePostMenu.__init__(self, **kw)

    def make_title(self, attr):
        if attr == "all":
            return _("all")
        return menu[attr]

class TimeMenu(SimplePostMenu):
    """Menu for setting the time interval of the listing (from 'hour' to 'all')"""
    name      = 't'
    default   = 'all'
    options   = ('hour', 'day', 'week', 'month', 'year', 'all')

    def __init__(self, **kw):
        kw['title'] = _("links from")
        SimplePostMenu.__init__(self, **kw)

    @classmethod
    def operator(self, time):
        from r2.models import Link
        if time != 'all':
            return Link.c._date >= timeago(time)

class ControversyTimeMenu(TimeMenu):
    """time interval for controversial sort.  Make default time 'day' rather than 'all'"""
    default = 'day'
    use_post = True

class SubredditMenu(NavMenu):
    def find_selected(self):
        """Always return False so the title is always displayed"""
        return None

class JsNavMenu(NavMenu):
    def find_selected(self):
        """Always return the first element."""
        return self.options[0]

# --------------------
# TODO: move to admin area
class AdminReporterMenu(SortMenu):
    default = 'top'
    options = ('hot', 'new', 'top')

class AdminKindMenu(KindMenu):
    options = ('all', 'links', 'comments', 'spam', 'autobanned')


class AdminTimeMenu(TimeMenu):
    get_param = 't'
    default   = 'day'
    options   = ('hour', 'day', 'week')


