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

from pylons.i18n import _, ungettext
from pylons.controllers.util import redirect_to
from r2.controllers.reddit_base import (
    base_listing,
    pagecache_policy,
    PAGECACHE_POLICY,
    paginated_listing,
    prevent_framing_and_css,
    RedditController,
)
from r2 import config
from r2.models import *
from r2.config.extensions import is_api
from r2.lib.pages import *
from r2.lib.pages.things import wrap_links
from r2.lib.pages import trafficpages
from r2.lib.menus import *
from r2.lib.utils import to36, sanitize_url, check_cheating, title_to_url
from r2.lib.utils import query_string, UrlParser, link_from_url, url_links_builder
from r2.lib.template_helpers import get_domain
from r2.lib.filters import unsafe, _force_unicode, _force_utf8
from r2.lib.emailer import Email
from r2.lib.db.operators import desc
from r2.lib.db import queries
from r2.lib.db.tdb_cassandra import MultiColumnQuery
from r2.lib.strings import strings
from r2.lib.search import (SearchQuery, SubredditSearchQuery, SearchException,
                           InvalidQuery)
from r2.lib.validator import *
from r2.lib import jsontemplates
from r2.lib import sup
import r2.lib.db.thing as thing
from r2.lib.errors import errors
from listingcontroller import ListingController
from oauth2 import OAuth2ResourceController, require_oauth2_scope
from api_docs import api_doc, api_section
from pylons import c, request, response
from r2.models.token import EmailVerificationToken
from r2.controllers.ipn import generate_blob, validate_blob, GoldException

from operator import attrgetter
import string
import random as rand
import re, socket
import time as time_module
from urllib import quote_plus

class FrontController(RedditController, OAuth2ResourceController):

    allow_stylesheets = True

    def pre(self):
        self.check_for_bearer_token()
        RedditController.pre(self)

    @validate(article=VLink('article'),
              comment=VCommentID('comment'))
    def GET_oldinfo(self, article, type, dest, rest=None, comment=''):
        """Legacy: supporting permalink pages from '06,
           and non-search-engine-friendly links"""
        if not (dest in ('comments','related','details')):
                dest = 'comments'
        if type == 'ancient':
            #this could go in config, but it should never change
            max_link_id = 10000000
            new_id = max_link_id - int(article._id)
            return self.redirect('/info/' + to36(new_id) + '/' + rest)
        if type == 'old':
            new_url = "/%s/%s/%s" % \
                      (dest, article._id36,
                       quote_plus(title_to_url(article.title).encode('utf-8')))
            if not c.default_sr:
                new_url = "/r/%s%s" % (c.site.name, new_url)
            if comment:
                new_url = new_url + "/%s" % comment._id36
            if c.extension:
                new_url = new_url + "/.%s" % c.extension

            new_url = new_url + query_string(request.get)

            # redirect should be smarter and handle extensions, etc.
            return self.redirect(new_url, code=301)

    @api_doc(api_section.listings)
    def GET_random(self):
        """The Serendipity button"""
        sort = rand.choice(('new','hot'))
        links = c.site.get_links(sort, 'all')
        if isinstance(links, thing.Query):
            links._limit = g.num_serendipity
            links = [x._fullname for x in links]
        else:
            links = list(links)[:g.num_serendipity]

        rand.shuffle(links)

        builder = IDBuilder(links, skip=True,
                            keep_fn=lambda x: x.fresh,
                            num=1)
        links = builder.get_items()[0]

        if links:
            l = links[0]
            return self.redirect(add_sr("/tb/" + l._id36))
        else:
            return self.redirect(add_sr('/'))

    @prevent_framing_and_css()
    @validate(VAdmin(),
              thing=VByName('article'),
              oldid36=nop('article'),
              after=nop('after'),
              before=nop('before'),
              count=VCount('count'))
    def GET_details(self, thing, oldid36, after, before, count):
        """The (now deprecated) details page.  Content on this page
        has been subsubmed by the presence of the LinkInfoBar on the
        rightbox, so it is only useful for Admin-only wizardry."""
        if not thing:
            try:
                link = Link._byID36(oldid36)
                return self.redirect('/details/' + link._fullname)
            except (NotFound, ValueError):
                abort(404)

        kw = {'count': count}
        if before:
            kw['after'] = before
            kw['reverse'] = True
        else:
            kw['after'] = after
            kw['reverse'] = False
        return DetailsPage(thing=thing, expand_children=False, **kw).render()

    def GET_selfserviceoatmeal(self):
        return BoringPage(_("self service help"),
                          show_sidebar=False,
                          content=SelfServiceOatmeal()).render()


    @validate(article=VLink('article'))
    def GET_shirt(self, article):
        if not can_view_link_comments(article):
            abort(403, 'forbidden')
        return self.abort404()

    def _comment_visits(self, article, user, new_visit=None):
        timer = g.stats.get_timer("gold.comment_visits")
        timer.start()

        hc_key = "comment_visits-%s-%s" % (user.name, article._id36)
        old_visits = g.hardcache.get(hc_key, [])

        append = False

        if new_visit is None:
            pass
        elif len(old_visits) == 0:
            append = True
        else:
            last_visit = max(old_visits)
            time_since_last = new_visit - last_visit
            if (time_since_last.days > 0
                or time_since_last.seconds > g.comment_visits_period):
                append = True
            else:
                # They were just here a few seconds ago; consider that
                # the same "visit" as right now
                old_visits.pop()

        if append:
            copy = list(old_visits) # make a copy
            copy.append(new_visit)
            if len(copy) > 10:
                copy.pop(0)
            g.hardcache.set(hc_key, copy, 86400 * 2)

        timer.stop()

        return old_visits


    @validate(article=VLink('article'),
              comment=VCommentID('comment'),
              context=VInt('context', min=0, max=8),
              sort=VMenu('controller', CommentSortMenu),
              limit=VInt('limit'),
              depth=VInt('depth'))
    def POST_comments(self, article, comment, context, sort, limit, depth):
        # VMenu validator will save the value of sort before we reach this
        # point. Now just redirect to GET mode.
        return self.redirect(request.fullpath + query_string(dict(sort=sort)))

    @require_oauth2_scope("read")
    @validate(article=VLink('article'),
              comment=VCommentID('comment'),
              context=VInt('context', min=0, max=8),
              sort=VMenu('controller', CommentSortMenu),
              limit=VInt('limit'),
              depth=VInt('depth'))
    @api_doc(api_section.listings,
             uri='/comments/{article}',
             extensions=['json', 'xml'])
    def GET_comments(self, article, comment, context, sort, limit, depth):
        """Comment page for a given 'article'."""
        if comment and comment.link_id != article._id:
            return self.abort404()

        sr = Subreddit._byID(article.sr_id, True)

        if sr.name == g.takedown_sr:
            request.environ['REDDIT_TAKEDOWN'] = article._fullname
            return self.abort404()

        if not c.default_sr and c.site._id != sr._id:
            return self.abort404()

        if not can_view_link_comments(article):
            abort(403, 'forbidden')

        #check for 304
        self.check_modified(article, 'comments')

        # If there is a focal comment, communicate down to
        # comment_skeleton.html who that will be. Also, skip
        # comment_visits check
        previous_visits = None
        if comment:
            c.focal_comment = comment._id36
        elif (c.user_is_loggedin and c.user.gold and
              c.user.pref_highlight_new_comments):
            previous_visits = self._comment_visits(article, c.user, c.start_time)

        # check if we just came from the submit page
        infotext = None
        if request.get.get('already_submitted'):
            infotext = strings.already_submitted % article.resubmit_link()

        check_cheating('comments')

        if not c.user.pref_num_comments:
            num = g.num_comments
        elif c.user.gold:
            num = min(c.user.pref_num_comments, g.max_comments_gold)
        else:
            num = min(c.user.pref_num_comments, g.max_comments)

        kw = {}
        # allow depth to be reset (I suspect I'll turn the VInt into a
        # validator on my next pass of .compact)
        if depth is not None and 0 < depth < MAX_RECURSION:
            kw['max_depth'] = depth
        elif c.render_style == "compact":
            kw['max_depth'] = 5

        displayPane = PaneStack()

        # allow the user's total count preferences to be overwritten
        # (think of .embed as the use case together with depth=1)

        if limit and limit > 0:
            num = limit

        if c.user_is_loggedin and c.user.gold:
            if num > g.max_comments_gold:
                displayPane.append(InfoBar(message =
                                           strings.over_comment_limit_gold
                                           % max(0, g.max_comments_gold)))
                num = g.max_comments_gold
        elif num > g.max_comments:
            if limit:
                displayPane.append(InfoBar(message =
                                       strings.over_comment_limit
                                       % dict(max=max(0, g.max_comments),
                                              goldmax=max(0,
                                                   g.max_comments_gold))))
            num = g.max_comments

        # if permalink page, add that message first to the content
        if comment:
            displayPane.append(PermalinkMessage(article.make_permalink_slow()))

        displayPane.append(LinkCommentSep())

        # insert reply box only for logged in user
        if c.user_is_loggedin and can_comment_link(article) and not is_api():
            #no comment box for permalinks
            display = False
            if not comment:
                age = c.start_time - article._date
                if article.promoted or age.days < g.REPLY_AGE_LIMIT:
                    display = True
            displayPane.append(UserText(item=article, creating=True,
                                        post_form='comment',
                                        display=display,
                                        cloneable=True))

        if previous_visits:
            displayPane.append(CommentVisitsBox(previous_visits))
            # Used in later "more comments" renderings
            pv_hex = md5(repr(previous_visits)).hexdigest()
            g.cache.set(pv_hex, previous_visits, time=g.comment_visits_period)
            c.previous_visits_hex = pv_hex

        # Used in template_helpers
        c.previous_visits = previous_visits

        if article.contest_mode:
            sort = "random"

        # finally add the comment listing
        displayPane.append(CommentPane(article, CommentSortMenu.operator(sort),
                                       comment, context, num, **kw))

        subtitle_buttons = []

        if c.focal_comment or context is not None:
            subtitle = None
        elif article.num_comments == 0:
            subtitle = _("no comments (yet)")
        elif article.num_comments <= num:
            subtitle = _("all %d comments") % article.num_comments
        else:
            subtitle = _("top %d comments") % num

            if g.max_comments > num:
                self._add_show_comments_link(subtitle_buttons, article, num,
                                             g.max_comments, gold=False)

            if (c.user_is_loggedin and c.user.gold
                and article.num_comments > g.max_comments):
                self._add_show_comments_link(subtitle_buttons, article, num,
                                             g.max_comments_gold, gold=True)

        res = LinkInfoPage(link=article, comment=comment,
                           content=displayPane,
                           page_classes=['comments-page'],
                           subtitle=subtitle,
                           subtitle_buttons=subtitle_buttons,
                           nav_menus=[CommentSortMenu(default=sort),
                                        LinkCommentsSettings(article)],
                           infotext=infotext).render()
        return res

    def _add_show_comments_link(self, array, article, num, max_comm, gold=False):
        if num == max_comm:
            return
        elif article.num_comments <= max_comm:
            link_text = _("show all %d") % article.num_comments
        else:
            link_text = _("show %d") % max_comm

        limit_param = "?limit=%d" % max_comm

        if gold:
            link_class = "gold"
        else:
            link_class = ""

        more_link = article.make_permalink_slow() + limit_param
        array.append( (link_text, more_link, link_class) )

    @validate(VUser(),
              name=nop('name'))
    def GET_newreddit(self, name):
        """Create a subreddit form"""
        title = _('create a subreddit')
        content=CreateSubreddit(name=name or '')
        res = FormPage(_("create a subreddit"),
                       content=content,
                       ).render()
        return res

    @pagecache_policy(PAGECACHE_POLICY.LOGGEDIN_AND_LOGGEDOUT)
    @require_oauth2_scope("modconfig")
    @api_doc(api_section.moderation)
    def GET_stylesheet(self):
        """Fetches a subreddit's current stylesheet."""
        if g.css_killswitch:
            self.abort404()

        # de-stale the subreddit object so we don't poison nginx's cache
        if not isinstance(c.site, FakeSubreddit):
            c.site = Subreddit._byID(c.site._id, data=True, stale=False)

        if c.site.stylesheet_is_static:
            # TODO: X-Private-Subreddit?
            return redirect_to(c.site.stylesheet_url)
        else:
            stylesheet_contents = c.site.stylesheet_contents

        if stylesheet_contents:
            c.allow_loggedin_cache = True

            if c.site.stylesheet_modified:
                self.abort_if_not_modified(
                    c.site.stylesheet_modified,
                    private=False,
                    max_age=timedelta(days=7),
                    must_revalidate=False,
                )

            response.content_type = 'text/css'
            if c.site.type == 'private':
                response.headers['X-Private-Subreddit'] = 'private'
            return stylesheet_contents
        else:
            return self.abort404()

    def _make_moderationlog(self, srs, num, after, reverse, count, mod=None, action=None):

        if mod and action:
            query = Subreddit.get_modactions(srs, mod=mod, action=None)
            def keep_fn(ma):
                return ma.action == action
        else:
            query = Subreddit.get_modactions(srs, mod=mod, action=action)
            def keep_fn(ma):
                return True

        builder = QueryBuilder(query, skip=True, num=num, after=after,
                               keep_fn=keep_fn, count=count,
                               reverse=reverse,
                               wrap=default_thing_wrapper())
        listing = ModActionListing(builder)
        pane = listing.listing()
        return pane

    modname_splitter = re.compile('[ ,]+')

    @require_oauth2_scope("modlog")
    @prevent_framing_and_css(allow_cname_frame=True)
    @paginated_listing(max_page_size=500, backend='cassandra')
    @validate(mod=nop('mod'),
              action=VOneOf('type', ModAction.actions))
    @api_doc(api_section.moderation)
    def GET_moderationlog(self, num, after, reverse, count, mod, action):
        if not c.user_is_loggedin or not (c.user_is_admin or
                                          c.site.is_moderator(c.user)):
            return self.abort404()

        if mod:
            if mod == 'a':
                modnames = g.admins
            else:
                modnames = self.modname_splitter.split(mod)
            mod = []
            for name in modnames:
                try:
                    mod.append(Account._by_name(name, allow_deleted=True))
                except NotFound:
                    continue
            mod = mod or None

        if isinstance(c.site, (MultiReddit, ModSR)):
            srs = Subreddit._byID(c.site.sr_ids, return_dict=False)

            # grab all moderators
            mod_ids = set(Subreddit.get_all_mod_ids(srs))
            mods = Account._byID(mod_ids, data=True)

            pane = self._make_moderationlog(srs, num, after, reverse, count,
                                            mod=mod, action=action)
        elif isinstance(c.site, FakeSubreddit):
            return self.abort404()
        else:
            mod_ids = c.site.moderators
            mods = Account._byID(mod_ids, data=True)

            pane = self._make_moderationlog(c.site, num, after, reverse, count,
                                            mod=mod, action=action)

        panes = PaneStack()
        panes.append(pane)

        action_buttons = [NavButton(_('all'), None, opt='type', css_class='primary')]
        for a in ModAction.actions:
            action_buttons.append(NavButton(ModAction._menu[a], a, opt='type'))

        mod_buttons = [NavButton(_('all'), None, opt='mod', css_class='primary')]
        for mod_id in mod_ids:
            mod = mods[mod_id]
            mod_buttons.append(NavButton(mod.name, mod.name, opt='mod'))
        mod_buttons.append(NavButton('admins*', 'a', opt='mod'))
        base_path = request.path
        menus = [NavMenu(action_buttons, base_path=base_path,
                         title=_('filter by action'), type='lightdrop', css_class='modaction-drop'),
                NavMenu(mod_buttons, base_path=base_path,
                        title=_('filter by moderator'), type='lightdrop')]
        return EditReddit(content=panes,
                          nav_menus=menus,
                          location="log",
                          extension_handling=False).render()

    def _make_spamlisting(self, location, only, num, after, reverse, count):
        include_links, include_comments = True, True
        if only == 'links':
            include_comments = False
        elif only == 'comments':
            include_links = False

        if location == 'reports':
            query = c.site.get_reported(include_links=include_links,
                                        include_comments=include_comments)
        elif location == 'spam':
            query = c.site.get_spam(include_links=include_links,
                                    include_comments=include_comments)
        elif location == 'modqueue':
            query = c.site.get_modqueue(include_links=include_links,
                                        include_comments=include_comments)
        elif location == 'unmoderated':
            query = c.site.get_unmoderated()
        else:
            raise ValueError

        if isinstance(query, thing.Query):
            builder_cls = QueryBuilder
        elif isinstance (query, list):
            builder_cls = QueryBuilder
        else:
            builder_cls = IDBuilder

        def keep_fn(x):
            # no need to bother mods with banned users, or deleted content
            if x._deleted:
                return False
            if getattr(x,'author',None) == c.user and c.user._spam:
                return False

            if location == "reports":
                return x.reported > 0 and not x._spam
            elif location == "spam":
                return x._spam
            elif location == "modqueue":
                if x.reported > 0 and not x._spam:
                    return True # reported but not banned
                if x.author._spam and x.subreddit.exclude_banned_modqueue:
                    # banned user, don't show if subreddit pref excludes
                    return False

                verdict = getattr(x, "verdict", None)
                if verdict is None:
                    return True # anything without a verdict
                if x._spam and verdict != 'mod-removed':
                    return True # spam, unless banned by a moderator
                return False
            elif location == "unmoderated":
                return not getattr(x, 'verdict', None)
            else:
                raise ValueError

        builder = builder_cls(query,
                              skip=True,
                              num=num, after=after,
                              keep_fn=keep_fn,
                              count=count, reverse=reverse,
                              wrap=ListingController.builder_wrapper,
                              spam_listing=True)
        listing = LinkListing(builder)
        pane = listing.listing()

        # Indicate that the comment tree wasn't built for comments
        for i in pane.things:
            if hasattr(i, 'body'):
                i.child = None

        return pane

    def _edit_normal_reddit(self, location, created):
        # moderator is either reddit's moderator or an admin
        moderator_rel = c.user_is_loggedin and c.site.get_moderator(c.user)
        is_moderator = c.user_is_admin or moderator_rel
        is_unlimited_moderator = c.user_is_admin or (
            moderator_rel and moderator_rel.is_superuser())
        is_moderator_with_perms = lambda *perms: (
            c.user_is_admin
            or moderator_rel and all(moderator_rel.has_permission(perm)
                                     for perm in perms))

        if is_moderator_with_perms('config') and location == 'edit':
            pane = PaneStack()
            if created == 'true':
                pane.append(InfoBar(message=strings.sr_created))
            c.allow_styles = True
            c.site = Subreddit._byID(c.site._id, data=True, stale=False)
            pane.append(CreateSubreddit(site=c.site))
        elif location == 'moderators':
            pane = ModList(editable=is_unlimited_moderator)
        elif is_moderator_with_perms('access') and location == 'banned':
            pane = BannedList(editable=is_moderator_with_perms('access'))
        elif is_moderator_with_perms('wiki') and location == 'wikibanned':
            pane = WikiBannedList(editable=is_moderator_with_perms('access'))
        elif (is_moderator_with_perms('wiki')
              and location == 'wikicontributors'):
            pane = WikiMayContributeList(
                editable=is_moderator_with_perms('wiki'))
        elif (location == 'contributors' and
              # On public reddits, only moderators can see the whitelist.
              # On private reddits, all contributors can see each other.
              (c.site.type != 'public' or
               (c.user_is_loggedin and
                (c.site.is_moderator_with_perms(c.user, 'access')
                 or c.user_is_admin)))):
                pane = ContributorList(
                    editable=is_moderator_with_perms('access'))
        elif (location == 'stylesheet'
              and c.site.can_change_stylesheet(c.user)
              and not g.css_killswitch):
            if hasattr(c.site,'stylesheet_contents_user') and c.site.stylesheet_contents_user:
                stylesheet_contents = c.site.stylesheet_contents_user
            elif hasattr(c.site,'stylesheet_contents') and c.site.stylesheet_contents:
                stylesheet_contents = c.site.stylesheet_contents
            else:
                stylesheet_contents = ''
            c.allow_styles = True
            pane = SubredditStylesheet(site=c.site,
                                       stylesheet_contents=stylesheet_contents)
        elif (location == 'stylesheet'
              and c.site.can_view(c.user)
              and not g.css_killswitch):
            stylesheet = (c.site.stylesheet_contents_user or
                          c.site.stylesheet_contents)
            pane = SubredditStylesheetSource(stylesheet_contents=stylesheet)
        elif location == 'traffic' and (c.site.public_traffic or
                                        (is_moderator or c.user_is_sponsor)):
            pane = trafficpages.SubredditTraffic()
        elif (location == "about") and is_api():
            return self.redirect(add_sr('about.json'), code=301)
        else:
            return self.abort404()

        is_wiki_action = location in ['wikibanned', 'wikicontributors']

        return EditReddit(content=pane,
                          show_wiki_actions=is_wiki_action,
                          location=location,
                          extension_handling=False).render()

    @base_listing
    @prevent_framing_and_css(allow_cname_frame=True)
    @validate(VSrModerator(perms='posts'),
              location=nop('location'),
              only=VOneOf('only', ('links', 'comments')))
    def GET_spamlisting(self, location, only, num, after, reverse, count):
        c.allow_styles = True
        c.profilepage = True
        pane = self._make_spamlisting(location, only, num, after, reverse,
                                      count)
        extension_handling = "private" if c.user.pref_private_feeds else False

        if location in ('reports', 'spam', 'modqueue'):
            buttons = [NavButton(_('links and comments'), None, opt='only'),
                       NavButton(_('links'), 'links', opt='only'),
                       NavButton(_('comments'), 'comments', opt='only')]
            menus = [NavMenu(buttons, base_path=request.path, title=_('show'),
                             type='lightdrop')]
        else:
            menus = None
        return EditReddit(content=pane,
                          location=location,
                          nav_menus=menus,
                          extension_handling=extension_handling).render()

    @base_listing
    @prevent_framing_and_css(allow_cname_frame=True)
    @validate(VSrModerator(perms='flair'),
              name=nop('name'))
    def GET_flairlisting(self, num, after, reverse, count, name):
        user = None
        if name:
            try:
                user = Account._by_name(name)
            except NotFound:
                c.errors.add(errors.USER_DOESNT_EXIST, field='name')

        c.allow_styles = True
        pane = FlairPane(num, after, reverse, name, user)
        return EditReddit(content=pane, location='flair').render()

    @prevent_framing_and_css(allow_cname_frame=True)
    @validate(location=nop('location'),
              created=VOneOf('created', ('true','false'),
                             default='false'))
    def GET_editreddit(self, location, created):
        """Edit reddit form."""
        c.profilepage = True
        if isinstance(c.site, FakeSubreddit):
            return self.abort404()
        else:
            return self._edit_normal_reddit(location, created)

    @require_oauth2_scope("read")
    @api_doc(api_section.subreddits, uri='/r/{subreddit}/about', extensions=['json'])
    def GET_about(self):
        """Return information about the subreddit.

        Data includes the subscriber count, description, and header image."""
        if not is_api() or isinstance(c.site, FakeSubreddit):
            return self.abort404()
        return Reddit(content=Wrapped(c.site)).render()

    @require_oauth2_scope("read")
    def GET_sidebar(self):
        usertext = UserText(c.site, c.site.description)
        return Reddit(content=usertext).render()

    def GET_awards(self):
        """The awards page."""
        return BoringPage(_("awards"), content=UserAwards()).render()

    # filter for removing punctuation which could be interpreted as search syntax
    related_replace_regex = re.compile(r'[?\\&|!{}+~^()"\':*-]+')
    related_replace_with = ' '

    @base_listing
    @validate(article=VLink('article'))
    def GET_related(self, num, article, after, reverse, count):
        """Related page: performs a search using title of article as
        the search query.

        """
        if not can_view_link_comments(article):
            abort(403, 'forbidden')

        query = self.related_replace_regex.sub(self.related_replace_with,
                                               article.title)
        query = _force_unicode(query)
        query = query[:1024]
        query = u"|".join(query.split())
        query = u"title:'%s'" % query
        rel_range = timedelta(days=3)
        start = int(time_module.mktime((article._date - rel_range).utctimetuple()))
        end = int(time_module.mktime((article._date + rel_range).utctimetuple()))
        nsfw = u"nsfw:0" if not (article.over_18 or article._nsfw.findall(article.title)) else u""
        query = u"(and %s timestamp:%s..%s %s)" % (query, start, end, nsfw)
        q = SearchQuery(query, raw_sort="-text_relevance",
                        syntax="cloudsearch")
        pane = self._search(q, num=num, after=after, reverse=reverse,
                            count=count)[2]

        return LinkInfoPage(link=article, content=pane,
                            page_classes=['related-page'],
                            subtitle=_('related')).render()

    @base_listing
    @validate(article=VLink('article'))
    def GET_duplicates(self, article, num, after, reverse, count):
        if not can_view_link_comments(article):
            abort(403, 'forbidden')

        builder = url_links_builder(article.url, exclude=article._fullname,
                                    num=num, after=after, reverse=reverse,
                                    count=count)
        num_duplicates = len(builder.get_items()[0])
        listing = LinkListing(builder).listing()

        res = LinkInfoPage(link=article,
                           comment=None,
                           num_duplicates=num_duplicates,
                           content=listing,
                           page_classes=['other-discussions-page'],
                           subtitle=_('other discussions')).render()
        return res


    @base_listing
    @validate(query=nop('q'))
    @api_doc(api_section.subreddits, uri='/subreddits/search', extensions=['json', 'xml'])
    def GET_search_reddits(self, query, reverse, after, count, num):
        """Search reddits by title and description."""
        q = SubredditSearchQuery(query)

        results, etime, spane = self._search(q, num=num, reverse=reverse,
                                             after=after, count=count,
                                             skip_deleted_authors=False)

        res = SubredditsPage(content=spane,
                             prev_search=query,
                             elapsed_time=etime,
                             num_results=results.hits,
                             # update if we ever add sorts
                             search_params={},
                             title=_("search results"),
                             simple=True).render()
        return res

    search_help_page = "/wiki/search"
    verify_langs_regex = re.compile(r"\A[a-z][a-z](,[a-z][a-z])*\Z")
    @base_listing
    @validate(query=VLength('q', max_length=512),
              sort=VMenu('sort', SearchSortMenu, remember=False),
              recent=VMenu('t', TimeMenu, remember=False),
              restrict_sr=VBoolean('restrict_sr', default=False),
              syntax=VOneOf('syntax', options=SearchQuery.known_syntaxes))
    @api_doc(api_section.search, extensions=['json', 'xml'])
    def GET_search(self, query, num, reverse, after, count, sort, recent,
                   restrict_sr, syntax):
        """Search links page."""
        if query and '.' in query:
            url = sanitize_url(query, require_scheme=True)
            if url:
                return self.redirect("/submit" + query_string({'url':url}))

        if not restrict_sr:
            site = DefaultSR()
        else:
            site = c.site

        if not syntax:
            syntax = SearchQuery.default_syntax

        try:
            cleanup_message = None
            try:
                q = SearchQuery(query, site, sort,
                                recent=recent, syntax=syntax)
                results, etime, spane = self._search(q, num=num, after=after,
                                                     reverse=reverse,
                                                     count=count)
            except InvalidQuery:
                # Clean the search of characters that might be causing the
                # InvalidQuery exception. If the cleaned search boils down
                # to an empty string, the search code is expected to bail
                # out early with an empty result set.
                cleaned = re.sub("[^\w\s]+", " ", query)
                cleaned = cleaned.lower().strip()

                q = SearchQuery(cleaned, site, sort, recent=recent)
                results, etime, spane = self._search(q, num=num,
                                                     after=after,
                                                     reverse=reverse,
                                                     count=count)
                if cleaned:
                    cleanup_message = strings.invalid_search_query % {
                                                        "clean_query": cleaned
                                                                      }
                    cleanup_message += " "
                    cleanup_message += strings.search_help % {
                                          "search_help": self.search_help_page
                                                              }
                else:
                    cleanup_message = strings.completely_invalid_search_query

            res = SearchPage(_('search results'), query, etime, results.hits,
                             content=spane,
                             nav_menus=[SearchSortMenu(default=sort),
                                        TimeMenu(default=recent)],
                             search_params=dict(sort=sort, t=recent),
                             infotext=cleanup_message,
                             simple=False, site=c.site,
                             restrict_sr=restrict_sr,
                             syntax=syntax,
                             converted_data=q.converted_data,
                             facets=results.subreddit_facets,
                             sort=sort,
                             recent=recent,
                             ).render()

            return res
        except SearchException + (socket.error,) as e:
            return self.search_fail(e)

    def _search(self, query_obj, num, after, reverse, count=0,
                skip_deleted_authors=True):
        """Helper function for interfacing with search.  Basically a
           thin wrapper for SearchBuilder."""

        builder = SearchBuilder(query_obj,
                                after=after, num=num, reverse=reverse,
                                count=count,
                                wrap=ListingController.builder_wrapper,
                                skip_deleted_authors=skip_deleted_authors)

        listing = LinkListing(builder, show_nums=True)

        # have to do it in two steps since total_num and timing are only
        # computed after fetch_more
        try:
            res = listing.listing()
        except SearchException + (socket.error,) as e:
            return self.search_fail(e)
        timing = time_module.time() - builder.start_time

        return builder.results, timing, res

    @validate(VAdmin(),
              comment=VCommentByID('comment_id'))
    def GET_comment_by_id(self, comment):
        href = comment.make_permalink_slow(context=5, anchor=True)
        return self.redirect(href)

    @validate(url=VRequired('url', None),
              title=VRequired('title', None),
              text=VRequired('text', None),
              selftext=VRequired('selftext', None),
              then=VOneOf('then', ('tb','comments'), default='comments'))
    def GET_submit(self, url, title, text, selftext, then):
        """Submit form."""
        resubmit = request.get.get('resubmit')
        if url and not resubmit:
            # check to see if the url has already been submitted
            links = link_from_url(url)
            if links and len(links) == 1:
                return self.redirect(links[0].already_submitted_link)
            elif links:
                infotext = (strings.multiple_submitted
                            % links[0].resubmit_link())
                res = BoringPage(_("seen it"),
                                 content=wrap_links(links),
                                 infotext=infotext).render()
                return res

        if not c.user_is_loggedin:
            raise UserRequiredException

        if not (c.default_sr or c.site.can_submit(c.user)):
            abort(403, "forbidden")

        captcha = Captcha() if c.user.needs_captcha() else None

        extra_subreddits = []
        if isinstance(c.site, MultiReddit):
            extra_subreddits.append((
                _('%s subreddits') % c.site.name,
                c.site.srs
            ))

        newlink = NewLink(
            url=url or '',
            title=title or '',
            text=text or '',
            selftext=selftext or '',
            captcha=captcha,
            resubmit=resubmit,
            default_sr=c.site if not c.default_sr else None,
            extra_subreddits=extra_subreddits,
            show_link=c.default_sr or c.site.link_type != 'self',
            show_self=((c.default_sr or c.site.link_type != 'link')
                      and not request.get.get('no_self')),
            then=then,
        )

        return FormPage(_("submit"),
                        show_sidebar=True,
                        page_classes=['submit-page'],
                        content=newlink).render()

    def GET_frame(self):
        """used for cname support.  makes a frame and
        puts the proper url as the frame source"""
        sub_domain = request.environ.get('sub_domain')
        original_path = request.environ.get('original_path')
        sr = Subreddit._by_domain(sub_domain)
        return Cnameframe(original_path, sr, sub_domain).render()


    def GET_framebuster(self, what=None, blah=None):
        """
        renders the contents of the iframe which, on a cname, checks
        if the user is currently logged into reddit.

        if this page is hit from the primary domain, redirects to the
        cnamed domain version of the site.  If the user is logged in,
        this cnamed version will drop a boolean session cookie on that
        domain so that subsequent page reloads will be caught in
        middleware and a frame will be inserted around the content.

        If the user is not logged in, previous session cookies will be
        emptied so that subsequent refreshes will not be rendered in
        that pesky frame.
        """
        if not c.site.domain:
            return ""
        elif c.cname:
            return FrameBuster(login=(what == "login")).render()
        else:
            path = "/framebuster/"
            if c.user_is_loggedin:
                path += "login/"
            u = UrlParser(path + str(random.random()))
            u.mk_cname(require_frame=False, subreddit=c.site,
                       port=request.port)
            return self.redirect(u.unparse())
        # the user is not logged in or there is no cname.
        return FrameBuster(login=False).render()

    def GET_catchall(self):
        return self.abort404()

    @validate(period=VInt('seconds',
                          min=sup.MIN_PERIOD,
                          max=sup.MAX_PERIOD,
                          default=sup.MIN_PERIOD))
    def GET_sup(self, period):
        #dont cache this, it's memoized elsewhere
        c.used_cache = True
        sup.set_expires_header()

        if c.extension == 'json':
            return sup.sup_json(period)
        else:
            return self.abort404()


    @require_oauth2_scope("modtraffic")
    @validate(VTrafficViewer('link'),
              link=VLink('link'),
              campaign=VPromoCampaign('campaign'),
              before=VDate('before', format='%Y%m%d%H'),
              after=VDate('after', format='%Y%m%d%H'))
    def GET_traffic(self, link, campaign, before, after):
        if c.render_style == 'csv':
            return trafficpages.PromotedLinkTraffic.as_csv(campaign or link)

        content = trafficpages.PromotedLinkTraffic(link, campaign, before,
                                                   after)
        return LinkInfoPage(link=link,
                            page_classes=["promoted-traffic"],
                            comment=None,
                            content=content).render()

    @validate(VSponsorAdmin())
    def GET_site_traffic(self):
        return trafficpages.SitewideTrafficPage().render()

    @validate(VSponsorAdmin())
    def GET_lang_traffic(self, langcode):
        return trafficpages.LanguageTrafficPage(langcode).render()

    @validate(VSponsorAdmin())
    def GET_advert_traffic(self, code):
        return trafficpages.AdvertTrafficPage(code).render()

    @validate(VSponsorAdmin())
    def GET_subreddit_traffic_report(self):
        content = trafficpages.SubredditTrafficReport()

        if c.render_style == 'csv':
            return content.as_csv()
        return trafficpages.TrafficPage(content=content).render()

    @validate(VUser())
    def GET_account_activity(self):
        return AccountActivityPage().render()

    def GET_rules(self):
        return BoringPage(_("rules of reddit"), show_sidebar=False,
                          content=RulesPage(), page_classes=["rulespage-body"]
                          ).render()

    @validate(vendor=VOneOf("v", ("claimed-gold", "claimed-creddits",
                                  "paypal", "google-checkout", "coinbase"),
                            default="claimed-gold"))
    def GET_goldthanks(self, vendor):
        vendor_url = None
        vendor_claim_msg = _("thanks for buying reddit gold! your transaction "
                             "has been completed and emailed to you. you can "
                             "check the details by logging into your account "
                             "at:")
        lounge_md = None
        if vendor == "claimed-gold":
            claim_msg = _("claimed! enjoy your reddit gold membership.")
        elif vendor == "claimed-creddits":
            claim_msg = _("your gold creddits have been claimed!")
            lounge_md = _("now go to someone's userpage and give "
                          "them a present!")
        elif vendor == "paypal":
            claim_msg = vendor_claim_msg
            vendor_url = "https://www.paypal.com/us"
        elif vendor == "google-checkout":
            claim_msg = vendor_claim_msg
            vendor_url = "https://wallet.google.com/manage"
        elif vendor == "coinbase":
            claim_msg = _("thanks for buying reddit gold! your transaction is "
                          "being processed. if you have any questions please "
                          "email us at %(gold_email)s")
            claim_msg = claim_msg % {'gold_email': g.goldthanks_email}
        else:
            abort(404)

        if g.lounge_reddit and not lounge_md:
            lounge_url = "/r/" + g.lounge_reddit
            lounge_md = strings.lounge_msg % {'link': lounge_url}

        return BoringPage(_("thanks"), show_sidebar=False,
                          content=GoldThanks(claim_msg=claim_msg,
                                             vendor_url=vendor_url,
                                             lounge_md=lounge_md)).render()

    @validate(VUser(),
              token=VOneTimeToken(AwardClaimToken, "code"))
    def GET_confirm_award_claim(self, token):
        if not token:
            abort(403)

        award = Award._by_fullname(token.awardfullname)
        trophy = FakeTrophy(c.user, award, token.description, token.url)
        content = ConfirmAwardClaim(trophy=trophy, user=c.user.name,
                                    token=token)
        return BoringPage(_("claim this award?"), content=content).render()

    @validate(VUser(),
              token=VOneTimeToken(AwardClaimToken, "code"))
    def POST_claim_award(self, token):
        if not token:
            abort(403)

        token.consume()

        award = Award._by_fullname(token.awardfullname)
        trophy, preexisting = Trophy.claim(c.user, token.uid, award,
                                           token.description, token.url)
        redirect = '/awards/received?trophy=' + trophy._id36
        if preexisting:
            redirect += '&duplicate=true'
        self.redirect(redirect)

    @validate(trophy=VTrophy('trophy'),
              preexisting=VBoolean('duplicate'))
    def GET_received_award(self, trophy, preexisting):
        content = AwardReceived(trophy=trophy, preexisting=preexisting)
        return BoringPage(_("award claim"), content=content).render()

    def GET_gold_info(self):
        return GoldInfoPage(_("gold"), show_sidebar=False).render()

    def GET_gold_partners(self):
        return GoldPartnersPage(_("gold partners"), show_sidebar=False).render()


class FormsController(RedditController):

    def GET_password(self):
        """The 'what is my password' page"""
        return BoringPage(_("password"), content=Password()).render()

    @validate(VUser(),
              dest=VDestination(),
              reason=nop('reason'))
    def GET_verify(self, dest, reason):
        if c.user.email_verified:
            content = InfoBar(message=strings.email_verified)
            if dest:
                return self.redirect(dest)
        else:
            if reason == "submit":
                infomsg = strings.verify_email_submit
            else:
                infomsg = strings.verify_email

            content = PaneStack(
                [InfoBar(message=infomsg),
                 PrefUpdate(email=True, verify=True,
                            password=False)])
        return BoringPage(_("verify email"), content=content).render()

    @validate(VUser(),
              token=VOneTimeToken(EmailVerificationToken, "key"),
              dest=VDestination(default="/prefs/update"))
    def GET_verify_email(self, token, dest):
        if token and token.user_id != c.user._fullname:
            # wrong user. log them out and try again.
            self.logout()
            return self.redirect(request.fullpath)
        elif c.user.email_verified:
            # they've already verified.
            if token:
                # consume and ignore this token (if not already consumed).
                token.consume()
            return self.redirect(dest)
        elif token and token.valid_for_user(c.user):
            # successful verification!
            token.consume()
            c.user.email_verified = True
            c.user._commit()
            Award.give_if_needed("verified_email", c.user)
            return self.redirect(dest)
        else:
            # failure. let 'em know.
            content = PaneStack(
                [InfoBar(message=strings.email_verify_failed),
                 PrefUpdate(email=True,
                            verify=True,
                            password=False)])
            return BoringPage(_("verify email"), content=content).render()

    @validate(token=VOneTimeToken(PasswordResetToken, "key"),
              key=nop("key"))
    def GET_resetpassword(self, token, key):
        """page hit once a user has been sent a password reset email
        to verify their identity before allowing them to update their
        password."""

        #if another user is logged-in, log them out
        if c.user_is_loggedin:
            self.logout()
            return self.redirect(request.path)

        done = False
        if not key and request.referer:
            referer_path = request.referer.split(g.domain)[-1]
            done = referer_path.startswith(request.fullpath)
        elif not token:
            return self.redirect("/password?expired=true")
        return BoringPage(_("reset password"),
                          content=ResetPassword(key=key, done=done)).render()

    @prevent_framing_and_css()
    @validate(VUser(),
              location=nop("location"))
    def GET_prefs(self, location=''):
        """Preference page"""
        content = None
        infotext = None
        if not location or location == 'options':
            content = PrefOptions(done=request.get.get('done'))
        elif location == 'friends':
            content = PaneStack()
            infotext = strings.friends % Friends.path
            content.append(FriendList())
            content.append(EnemyList())
        elif location == 'update':
            content = PrefUpdate()
        elif location == 'apps':
            content = PrefApps(my_apps=OAuth2Client._by_user(c.user),
                               developed_apps=OAuth2Client._by_developer(c.user))
        elif location == 'feeds' and c.user.pref_private_feeds:
            content = PrefFeeds()
        elif location == 'delete':
            content = PrefDelete()
        elif location == 'otp':
            content = PrefOTP()
        else:
            return self.abort404()

        return PrefsPage(content=content, infotext=infotext).render()


    @validate(dest=VDestination())
    def GET_login(self, dest):
        """The /login form.  No link to this page exists any more on
        the site (all actions invoking it now go through the login
        cover).  However, this page is still used for logging the user
        in during submission or voting from the bookmarklets."""

        if (c.user_is_loggedin and
            not request.environ.get('extension') == 'embed'):
            return self.redirect(dest)
        return LoginPage(dest=dest).render()


    @validate(dest=VDestination())
    def GET_register(self, dest):
        if (c.user_is_loggedin and
            not request.environ.get('extension') == 'embed'):
            return self.redirect(dest)
        return RegisterPage(dest=dest).render()

    @validate(VUser(),
              VModhash(),
              dest=VDestination())
    def GET_logout(self, dest):
        return self.redirect(dest)

    @validate(VUser(),
              VModhash(),
              dest=VDestination())
    def POST_logout(self, dest):
        """wipe login cookie and redirect to referer."""
        self.logout()
        return self.redirect(dest)


    @validate(VUser(),
              dest=VDestination())
    def GET_adminon(self, dest):
        """Enable admin interaction with site"""
        #check like this because c.user_is_admin is still false
        if not c.user.name in g.admins:
            return self.abort404()

        c.deny_frames = True
        return AdminModeInterstitial(dest=dest).render()

    @validate(VAdmin(),
              dest=VDestination())
    def GET_adminoff(self, dest):
        """disable admin interaction with site."""
        if not c.user.name in g.admins:
            return self.abort404()
        self.disable_admin_mode(c.user)
        return self.redirect(dest)

    def _render_opt_in_out(self, msg_hash, leave):
        """Generates the form for an optin/optout page"""
        email = Email.handler.get_recipient(msg_hash)
        if not email:
            return self.abort404()
        sent = (has_opted_out(email) == leave)
        return BoringPage(_("opt out") if leave else _("welcome back"),
                          content=OptOut(email=email, leave=leave,
                                           sent=sent,
                                           msg_hash=msg_hash)).render()

    @validate(msg_hash=nop('x'))
    def GET_optout(self, msg_hash):
        """handles /mail/optout to add an email to the optout mailing
        list.  The actual email addition comes from the user posting
        the subsequently rendered form and is handled in
        ApiController.POST_optout."""
        return self._render_opt_in_out(msg_hash, True)

    @validate(msg_hash=nop('x'))
    def GET_optin(self, msg_hash):
        """handles /mail/optin to remove an email address from the
        optout list. The actual email removal comes from the user
        posting the subsequently rendered form and is handled in
        ApiController.POST_optin."""
        return self._render_opt_in_out(msg_hash, False)

    @validate(dest=VDestination("dest"))
    def GET_try_compact(self, dest):
        c.render_style = "compact"
        return TryCompact(dest=dest).render()

    @validate(VUser(),
              secret=VPrintable("secret", 50))
    def GET_claim(self, secret):
        """The page to claim reddit gold trophies"""
        return BoringPage(_("thanks"), content=Thanks(secret)).render()

    @validate(VUser(),
              passthrough=nop('passthrough'))
    def GET_creditgild(self, passthrough):
        """Used only for setting up credit card payments for gilding."""
        try:
            payment_blob = validate_blob(passthrough)
        except GoldException:
            self.abort404()

        if c.user != payment_blob['buyer']:
            self.abort404()

        if not payment_blob['goldtype'] == 'gift':
            self.abort404()

        recipient = payment_blob['recipient']
        comment = payment_blob['comment']
        summary = strings.gold_summary_comment_page
        summary = summary % {'recipient': recipient.name}
        months = 1
        price = g.gold_month_price * months

        content = CreditGild(
            summary=summary,
            price=price,
            months=months,
            stripe_key=g.STRIPE_PUBLIC_KEY,
            passthrough=passthrough,
            comment=comment,
        )

        return BoringPage(_("reddit gold"),
                          show_sidebar=False,
                          content=content).render()

    @validate(VUser(),
              goldtype=VOneOf("goldtype",
                              ("autorenew", "onetime", "creddits", "gift")),
              period=VOneOf("period", ("monthly", "yearly")),
              months=VInt("months"),
              # variables below are just for gifts
              signed=VBoolean("signed"),
              recipient_name=VPrintable("recipient", max_length=50),
              comment=VByName("comment", thing_cls=Comment),
              giftmessage=VLength("giftmessage", 10000))
    def GET_gold(self, goldtype, period, months,
                 signed, recipient_name, giftmessage, comment):

        if comment:
            comment_sr = Subreddit._byID(comment.sr_id, data=True)
            if (comment._deleted or
                    comment._spam or
                    not comment_sr.allow_comment_gilding):
                comment = None

        start_over = False
        recipient = None
        if goldtype == "autorenew":
            if period is None:
                start_over = True
        elif goldtype in ("onetime", "creddits"):
            if months is None or months < 1:
                start_over = True
        elif goldtype == "gift":
            if months is None or months < 1:
                start_over = True

            if comment:
                recipient = Account._byID(comment.author_id, data=True)
                if recipient._deleted:
                    comment = None
                    recipient = None
                    start_over = True
            else:
                try:
                    recipient = Account._by_name(recipient_name or "")
                except NotFound:
                    start_over = True
        else:
            goldtype = ""
            start_over = True

        if start_over:
            return BoringPage(_("reddit gold"),
                              show_sidebar=False,
                              content=Gold(goldtype, period, months, signed,
                                           recipient, recipient_name)).render()
        else:
            payment_blob = dict(goldtype=goldtype,
                                account_id=c.user._id,
                                account_name=c.user.name,
                                status="initialized")

            if goldtype == "gift":
                payment_blob["signed"] = signed
                payment_blob["recipient"] = recipient.name
                payment_blob["giftmessage"] = _force_utf8(giftmessage)
                if comment:
                    payment_blob["comment"] = comment._fullname

            passthrough = generate_blob(payment_blob)

            return BoringPage(_("reddit gold"),
                              show_sidebar=False,
                              content=GoldPayment(goldtype, period, months,
                                                  signed, recipient,
                                                  giftmessage, passthrough,
                                                  comment)
                              ).render()
