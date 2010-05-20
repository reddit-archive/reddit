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
# All portions of the code written by CondeNet are Copyright (c) 2006-2010
# CondeNet, Inc. All Rights Reserved.
################################################################################
from validator import *
from pylons.i18n import _, ungettext
from reddit_base import RedditController, base_listing
from r2 import config
from r2.models import *
from r2.lib.pages import *
from r2.lib.pages.things import wrap_links
from r2.lib.jsontemplates import is_api
from r2.lib.menus import *
from r2.lib.utils import to36, sanitize_url, check_cheating, title_to_url
from r2.lib.utils import query_string, UrlParser, link_from_url, link_duplicates
from r2.lib.template_helpers import get_domain
from r2.lib.filters import unsafe
from r2.lib.emailer import has_opted_out, Email
from r2.lib.db.operators import desc
from r2.lib.db import queries
from r2.lib.strings import strings
from r2.lib.solrsearch import RelatedSearchQuery, SubredditSearchQuery, LinkSearchQuery
from r2.lib.contrib.pysolr import SolrError
from r2.lib import jsontemplates
from r2.lib import sup
import r2.lib.db.thing as thing
from listingcontroller import ListingController
from pylons import c, request, request, Response

import random as rand
import re
import time as time_module
from urllib import quote_plus

class FrontController(RedditController):

    allow_stylesheets = True

    @validate(article = VLink('article'),
              comment = VCommentID('comment'))
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

    def GET_random(self):
        """The Serendipity button"""
        sort = 'new' if rand.choice((True,False)) else 'hot'
        links = c.site.get_links(sort, 'all')
        if isinstance(links, thing.Query):
            links._limit = g.num_serendipity
            links = [x._fullname for x in links]
        else:
            links = list(links)[:g.num_serendipity]

        rand.shuffle(links)

        builder = IDBuilder(links, skip = True,
                            keep_fn = lambda x: x.fresh,
                            num = 1)
        links = builder.get_items()[0]

        if links:
            l = links[0]
            return self.redirect(add_sr("/tb/" + l._id36))
        else:
            return self.redirect(add_sr('/'))

    @validate(VAdmin(),
              article = VLink('article'))
    def GET_details(self, article):
        """The (now depricated) details page.  Content on this page
        has been subsubmed by the presence of the LinkInfoBar on the
        rightbox, so it is only useful for Admin-only wizardry."""
        return DetailsPage(link = article, expand_children=False).render()


    def GET_selfserviceoatmeal(self
):
        return BoringPage(_("self service help"), 
                          show_sidebar = False,
                          content = SelfServiceOatmeal()).render()


    @validate(article = VLink('article'))
    def GET_shirt(self, article):
        if not can_view_link_comments(article):
            abort(403, 'forbidden')
        if g.spreadshirt_url:
            from r2.lib.spreadshirt import ShirtPage
            return ShirtPage(link = article).render()
        return self.abort404()

    @validate(article      = VLink('article'),
              comment      = VCommentID('comment'),
              context      = VInt('context', min = 0, max = 8),
              sort         = VMenu('controller', CommentSortMenu),
              num_comments = VMenu('controller', NumCommentsMenu),
              limit        = VInt('limit'),
              depth        = VInt('depth'))
    def GET_comments(self, article, comment, context, sort, num_comments,
                     limit, depth):
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

        # if there is a focal comment, communicate down to
        # comment_skeleton.html who that will be
        if comment:
            c.focal_comment = comment._id36

        # check if we just came from the submit page
        infotext = None
        if request.get.get('already_submitted'):
            infotext = strings.already_submitted % article.resubmit_link()

        check_cheating('comments')

        # figure out number to show based on the menu (when num_comments
        # is 'true', the user wants to temporarily override their
        # comments limit pref
        user_num = c.user.pref_num_comments or g.num_comments
        num = g.max_comments if num_comments == 'true' else user_num

        kw = {}
        # allow depth to be reset (I suspect I'll turn the VInt into a
        # validator on my next pass of .compact)
        if depth is not None and 0 < depth < MAX_RECURSION:
            kw['max_depth'] = depth
        # allow the user's total count preferences to be overwritten
        # (think of .embed as the use case together with depth=1)x
        if limit is not None and 0 < limit < g.max_comments:
            num = limit

        displayPane = PaneStack()

        # if permalink page, add that message first to the content
        if comment:
            displayPane.append(PermalinkMessage(article.make_permalink_slow()))

        # insert reply box only for logged in user
        if c.user_is_loggedin and can_comment_link(article) and not is_api():
            #no comment box for permalinks
            display = not bool(comment)
            displayPane.append(UserText(item = article, creating = True,
                                        post_form = 'comment',
                                        display = display,
                                        cloneable = True))

        # finally add the comment listing
        displayPane.append(CommentPane(article, CommentSortMenu.operator(sort),
                                       comment, context, num, **kw))

        loc = None if c.focal_comment or context is not None else 'comments'

        res = LinkInfoPage(link = article, comment = comment,
                           content = displayPane, 
                           subtitle = _("comments"),
                           nav_menus = [CommentSortMenu(default = sort), 
                                        NumCommentsMenu(article.num_comments,
                                                        default=num_comments)],
                           infotext = infotext).render()
        return res

    @validate(VUser(),
              name = nop('name'))
    def GET_newreddit(self, name):
        """Create a reddit form"""
        title = _('create a reddit')
        content=CreateSubreddit(name = name or '')
        res = FormPage(_("create a reddit"), 
                       content = content,
                       ).render()
        return res

    def GET_stylesheet(self):
        if hasattr(c.site,'stylesheet_contents') and not g.css_killswitch:
            c.allow_loggedin_cache = True
            self.check_modified(c.site,'stylesheet_contents',
                                private=False, max_age=7*24*60*60,
                                must_revalidate=False)
            c.response_content_type = 'text/css'
            c.response.content =  c.site.stylesheet_contents
            return c.response
        else:
            return self.abort404()

    def _make_spamlisting(self, location, num, after, reverse, count):
        if location == 'reports':
            query = c.site.get_reported()
        elif location == 'spam':
            query = c.site.get_spam()
        elif location == 'trials':
            query = c.site.get_trials()
            num = 1000
        elif location == 'modqueue':
            query = c.site.get_modqueue()
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
            if x.hidden or x._deleted:
                return False

            if location == "reports":
                return x.reported > 0 and not x._spam
            elif location == "spam":
                return x._spam
            elif location == "trials":
                return not getattr(x, "verdict", None)
            elif location == "modqueue":
                if x.reported > 0 and not x._spam:
                    return True # reported but not banned
                verdict = getattr(x, "verdict", None)
                if verdict is None:
                    return True # anything without a verdict (i.e., trials)
                if x._spam and verdict != 'mod-removed':
                    return True # spam, unless banned by a moderator
                return False
            else:
                raise ValueError

        builder = builder_cls(query,
                              skip = True,
                              num = num, after = after,
                              keep_fn = keep_fn,
                              count = count, reverse = reverse,
                              wrap = ListingController.builder_wrapper)
        listing = LinkListing(builder)
        pane = listing.listing()

        return pane

    def _edit_modcontrib_reddit(self, location, num, after, reverse, count, created):
        extension_handling = False

        if not c.user_is_loggedin:
            return self.abort404()
        if isinstance(c.site, ModSR):
            level = 'mod'
        elif isinstance(c.site, ContribSR):
            level = 'contrib'
        elif isinstance(c.site, AllSR):
            level = 'all'
        else:
            raise ValueError

        if ((level == 'mod' and
             location in ('reports', 'spam', 'trials', 'modqueue'))
            or
            (level == 'all' and
             location == 'trials')):
            pane = self._make_spamlisting(location, num, after, reverse, count)
            if c.user.pref_private_feeds:
                extension_handling = "private"
        else:
            return self.abort404()

        return EditReddit(content = pane,
                          extension_handling = extension_handling).render()

    def _edit_normal_reddit(self, location, num, after, reverse, count, created):
        # moderator is either reddit's moderator or an admin
        is_moderator = c.user_is_loggedin and c.site.is_moderator(c.user) or c.user_is_admin
        extension_handling = False
        if is_moderator and location == 'edit':
            pane = PaneStack()
            if created == 'true':
                pane.append(InfoBar(message = strings.sr_created))
            pane.append(CreateSubreddit(site = c.site))
        elif location == 'moderators':
            pane = ModList(editable = is_moderator)
        elif is_moderator and location == 'banned':
            pane = BannedList(editable = is_moderator)
        elif (location == 'contributors' and
              # On public reddits, only moderators can see the whitelist.
              # On private reddits, all contributors can see each other.
              (c.site.type != 'public' or
               (c.user_is_loggedin and
                (c.site.is_moderator(c.user) or c.user_is_admin)))):
                pane = ContributorList(editable = is_moderator)
        elif (location == 'stylesheet'
              and c.site.can_change_stylesheet(c.user)
              and not g.css_killswitch):
            if hasattr(c.site,'stylesheet_contents_user') and c.site.stylesheet_contents_user:
                stylesheet_contents = c.site.stylesheet_contents_user
            elif hasattr(c.site,'stylesheet_contents') and c.site.stylesheet_contents:
                stylesheet_contents = c.site.stylesheet_contents
            else:
                stylesheet_contents = ''
            pane = SubredditStylesheet(site = c.site,
                                       stylesheet_contents = stylesheet_contents)
        elif location in ('reports', 'spam', 'trials', 'modqueue') and is_moderator:
            pane = self._make_spamlisting(location, num, after, reverse, count)
            if c.user.pref_private_feeds:
                extension_handling = "private"
        elif is_moderator and location == 'traffic':
            pane = RedditTraffic()
        elif c.user_is_sponsor and location == 'ads':
            pane = RedditAds()
        else:
            return self.abort404()

        return EditReddit(content = pane,
                          extension_handling = extension_handling).render()

    @base_listing
    @validate(location = nop('location'),
              created = VOneOf('created', ('true','false'),
                               default = 'false'))
    def GET_editreddit(self, location, num, after, reverse, count, created):
        """Edit reddit form."""
        if isinstance(c.site, ModContribSR):
            return self._edit_modcontrib_reddit(location, num, after, reverse,
                                                count, created)
        elif isinstance(c.site, AllSR) and c.user_is_admin:
            return self._edit_modcontrib_reddit(location, num, after, reverse,
                                                count, created)
        elif isinstance(c.site, FakeSubreddit):
            return self.abort404()
        else:
            return self._edit_normal_reddit(location, num, after, reverse,
                                            count, created)


    def GET_awards(self):
        """The awards page."""
        return BoringPage(_("awards"), content = UserAwards()).render()

    # filter for removing punctuation which could be interpreted as lucene syntax
    related_replace_regex = re.compile('[?\\&|!{}+~^()":*-]+')
    related_replace_with  = ' '

    @base_listing
    @validate(article = VLink('article'))
    def GET_related(self, num, article, after, reverse, count):
        """Related page: performs a search using title of article as
        the search query."""

        if not can_view_link_comments(article):
            abort(403, 'forbidden')

        title = c.site.name + ((': ' + article.title) if hasattr(article, 'title') else '')

        query = self.related_replace_regex.sub(self.related_replace_with,
                                               article.title)
        if len(query) > 1024:
            # could get fancier and break this into words, but titles
            # longer than this are typically ascii art anyway
            query = query[0:1023]

        q = RelatedSearchQuery(query, ignore = [article._fullname])
        num, t, pane = self._search(q,
                                    num = num, after = after, reverse = reverse,
                                    count = count)

        return LinkInfoPage(link = article, content = pane,
                            subtitle = _('related')).render()

    @base_listing
    @validate(article = VLink('article'))
    def GET_duplicates(self, article, num, after, reverse, count):
        if not can_view_link_comments(article):
            abort(403, 'forbidden')

        links = link_duplicates(article)
        builder = IDBuilder([ link._fullname for link in links ],
                            num = num, after = after, reverse = reverse,
                            count = count, skip = False)
        listing = LinkListing(builder).listing()

        res = LinkInfoPage(link = article,
                           comment = None,
                           duplicates = links,
                           content = listing,
                           subtitle = _('other discussions')).render()
        return res


    @base_listing
    @validate(query = nop('q'))
    def GET_search_reddits(self, query, reverse, after,  count, num):
        """Search reddits by title and description."""
        q = SubredditSearchQuery(query)

        num, t, spane = self._search(q, num = num, reverse = reverse,
                                     after = after, count = count)
        
        res = SubredditsPage(content=spane,
                             prev_search = query,
                             elapsed_time = t,
                             num_results = num,
                             # update if we ever add sorts
                             search_params = {},
                             title = _("search results")).render()
        return res

    verify_langs_regex = re.compile(r"^[a-z][a-z](,[a-z][a-z])*$")
    @base_listing
    @validate(query = nop('q'),
              time = VMenu('action', TimeMenu),
              sort = VMenu('sort', SearchSortMenu),
              langs = nop('langs'))
    def GET_search(self, query, num, time, reverse, after, count, langs, sort):
        """Search links page."""
        if query and '.' in query:
            url = sanitize_url(query, require_scheme = True)
            if url:
                return self.redirect("/submit" + query_string({'url':url}))

        if langs and self.verify_langs_regex.match(langs):
            langs = langs.split(',')
        else:
            langs = c.content_langs

        subreddits = None
        authors = None
        if c.site == subreddit.Friends and c.user_is_loggedin and c.user.friends:
            authors = c.user.friends
        elif isinstance(c.site, MultiReddit):
            subreddits = c.site.sr_ids
        elif not isinstance(c.site, FakeSubreddit):
            subreddits = [c.site._id]

        q = LinkSearchQuery(q = query, timerange = time, langs = langs,
                            subreddits = subreddits, authors = authors,
                            sort = SearchSortMenu.operator(sort))

        num, t, spane = self._search(q, num = num, after = after, reverse = reverse,
                                     count = count)

        if not isinstance(c.site,FakeSubreddit) and not c.cname:
            all_reddits_link = "%s/search%s" % (subreddit.All.path,
                                                query_string({'q': query}))
            d =  {'reddit_name':      c.site.name,
                  'reddit_link':      "http://%s/"%get_domain(cname = c.cname),
                  'all_reddits_link': all_reddits_link}
            infotext = strings.searching_a_reddit % d
        else:
            infotext = None

        res = SearchPage(_('search results'), query, t, num, content=spane,
                         nav_menus = [TimeMenu(default = time),
                                      SearchSortMenu(default=sort)],
                         search_params = dict(sort = sort, t = time),
                         infotext = infotext).render()

        return res

    def _search(self, query_obj, num, after, reverse, count=0):
        """Helper function for interfacing with search.  Basically a
        thin wrapper for SearchBuilder."""

        builder = SearchBuilder(query_obj,
                                after = after, num = num, reverse = reverse,
                                count = count,
                                wrap = ListingController.builder_wrapper)

        listing = LinkListing(builder, show_nums=True)

        # have to do it in two steps since total_num and timing are only
        # computed after fetch_more
        try:
            res = listing.listing()
        except SolrError, e:
            try:
                errmsg = "SolrError: %r %r" % (e, query_obj)
            except UnicodeEncodeError:
                errmsg = "SolrError involving unicode"

            if (str(e) == 'None'):
                # Production error logs only get non-None errors
                g.log.debug(errmsg)
            else:
                g.log.error(errmsg)

            sf = SearchFail()
            sb = SearchBar(prev_search = query_obj.q)

            us = unsafe(sb.render() + sf.render())

            errpage = pages.RedditError(_('search failed'), us)

            c.response = Response()
            c.response.status_code = 503
            request.environ['usable_error_content'] = errpage.render()
            request.environ['retry_after'] = 60

            abort(503)

        timing = time_module.time() - builder.start_time

        return builder.total_num, timing, res

    @validate(VAdmin(),
              comment = VCommentByID('comment_id'))
    def GET_comment_by_id(self, comment):
        href = comment.make_permalink_slow(context=5, anchor=True)
        return self.redirect(href)

    @validate(VUser(), 
              VSRSubmitPage(),
              url = VRequired('url', None),
              title = VRequired('title', None),
              then = VOneOf('then', ('tb','comments'), default = 'comments'))
    def GET_submit(self, url, title, then):
        """Submit form."""
        if url and not request.get.get('resubmit'):
            # check to see if the url has already been submitted
            links = link_from_url(url)
            if links and len(links) == 1:
                return self.redirect(links[0].already_submitted_link)
            elif links:
                infotext = (strings.multiple_submitted
                            % links[0].resubmit_link())
                res = BoringPage(_("seen it"),
                                 content = wrap_links(links),
                                 infotext = infotext).render()
                return res

        captcha = Captcha() if c.user.needs_captcha() else None
        sr_names = (Subreddit.submit_sr_names(c.user) or
                    Subreddit.submit_sr_names(None))

        return FormPage(_("submit"),
                        show_sidebar = True,
                        content=NewLink(url=url or '',
                                        title=title or '',
                                        subreddits = sr_names,
                                        captcha=captcha,
                                        then = then)).render()

    def _render_opt_in_out(self, msg_hash, leave):
        """Generates the form for an optin/optout page"""
        email = Email.handler.get_recipient(msg_hash)
        if not email:
            return self.abort404()
        sent = (has_opted_out(email) == leave)
        return BoringPage(_("opt out") if leave else _("welcome back"),
                          content = OptOut(email = email, leave = leave, 
                                           sent = sent, 
                                           msg_hash = msg_hash)).render()

    def GET_frame(self):
        """used for cname support.  makes a frame and
        puts the proper url as the frame source"""
        sub_domain = request.environ.get('sub_domain')
        original_path = request.environ.get('original_path')
        sr = Subreddit._by_domain(sub_domain)
        return Cnameframe(original_path, sr, sub_domain).render()


    def GET_framebuster(self, what = None, blah = None):
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
            return FrameBuster(login = (what == "login")).render()
        else:
            path = "/framebuster/"
            if c.user_is_loggedin:
                path += "login/"
            u = UrlParser(path + str(random.random()))
            u.mk_cname(require_frame = False, subreddit = c.site,
                       port = request.port)
            return self.redirect(u.unparse())
        # the user is not logged in or there is no cname.
        return FrameBuster(login = False).render()

    def GET_catchall(self):
        return self.abort404()

    @validate(period = VInt('seconds',
                            min = sup.MIN_PERIOD,
                            max = sup.MAX_PERIOD,
                            default = sup.MIN_PERIOD))
    def GET_sup(self, period):
        #dont cache this, it's memoized elsewhere
        c.used_cache = True
        sup.set_expires_header()

        if c.extension == 'json':
            c.response.content = sup.sup_json(period)
            return c.response
        else:
            return self.abort404()


    @validate(VTrafficViewer('article'),
              article = VLink('article'))
    def GET_traffic(self, article):
        content = PromotedTraffic(article)
        if c.render_style == 'csv':
            c.response.content = content.as_csv()
            return c.response

        return LinkInfoPage(link = article,
                           comment = None,
                           content = content).render()

    @validate(VAdmin())
    def GET_site_traffic(self):
        return BoringPage("traffic",
                          content = RedditTraffic()).render()

class FormsController(RedditController):

    def GET_password(self):
        """The 'what is my password' page"""
        return BoringPage(_("password"), content=Password()).render()

    @validate(VUser(),
              dest = VDestination(),
              reason = nop('reason'))
    def GET_verify(self, dest, reason):
        if c.user.email_verified:
            content = InfoBar(message = strings.email_verified)
            if dest:
                return self.redirect(dest)
        else:
            if reason == "submit":
                infomsg = strings.verify_email_submit
            else:
                infomsg = strings.verify_email

            content = PaneStack(
                [InfoBar(message = infomsg),
                 PrefUpdate(email = True, verify = True,
                            password = False)])
        return BoringPage(_("verify email"), content = content).render()

    @validate(VUser(),
              cache_evt = VCacheKey('email_verify', ('key',)),
              key = nop('key'),
              dest = VDestination(default = "/prefs/update"))
    def GET_verify_email(self, cache_evt, key, dest):
        if c.user_is_loggedin and c.user.email_verified:
            cache_evt.clear()
            return self.redirect(dest)
        elif not (cache_evt.user and
                key == passhash(cache_evt.user.name, cache_evt.user.email)):
            content = PaneStack(
                [InfoBar(message = strings.email_verify_failed),
                 PrefUpdate(email = True, verify = True,
                            password = False)])
            return BoringPage(_("verify email"), content = content).render()
        elif c.user != cache_evt.user:
            # wrong user.  Log them out and try again. 
            self.logout()
            return self.redirect(request.fullpath)
        else:
            cache_evt.clear()
            c.user.email_verified = True
            c.user._commit()
            Award.give_if_needed("verified_email", c.user)
            return self.redirect(dest)

    @validate(cache_evt = VCacheKey('reset', ('key',)),
              key = nop('key'))
    def GET_resetpassword(self, cache_evt, key):
        """page hit once a user has been sent a password reset email
        to verify their identity before allowing them to update their
        password."""

        #if another user is logged-in, log them out
        if c.user_is_loggedin:
            self.logout()
            return self.redirect(request.path)

        done = False
        if not key and request.referer:
            referer_path =  request.referer.split(g.domain)[-1]
            done = referer_path.startswith(request.fullpath)
        elif not getattr(cache_evt, "user", None):
            return self.abort404()
        return BoringPage(_("reset password"),
                          content=ResetPassword(key=key, done=done)).render()

    @validate(VUser())
    def GET_depmod(self):
        displayPane = PaneStack()

        active_trials = {}
        finished_trials = {}

        juries = Jury.by_account(c.user)

        trials = trial_info([j._thing2 for j in juries])

        for j in juries:
            defendant = j._thing2

            if trials.get(defendant._fullname, False):
                active_trials[defendant._fullname] = j._name
            else:
                finished_trials[defendant._fullname] = j._name

        if active_trials:
            fullnames = sorted(active_trials.keys(), reverse=True)

            def my_wrap(thing):
                w = Wrapped(thing)
                w.hide_score = True
                w.likes = None
                w.trial_mode = True
                w.render_class = LinkOnTrial
                w.juryvote = active_trials[thing._fullname]
                return w

            listing = wrap_links(fullnames, wrapper=my_wrap)
            displayPane.append(InfoBar(strings.active_trials,
                                       extra_class="mellow"))
            displayPane.append(listing)

        if finished_trials:
            fullnames = sorted(finished_trials.keys(), reverse=True)
            listing = wrap_links(fullnames)
            displayPane.append(InfoBar(strings.finished_trials,
                                       extra_class="mellow"))
            displayPane.append(listing)

        displayPane.append(InfoBar(strings.more_info_link %
                                       dict(link="/help/deputies"),
                                   extra_class="mellow"))

        return Reddit(content = displayPane).render()

    @validate(VUser(),
              location = nop("location"))
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
        elif location == 'update':
            content = PrefUpdate()
        elif location == 'feeds' and c.user.pref_private_feeds:
            content = PrefFeeds()
        elif location == 'delete':
            content = PrefDelete()
        else:
            return self.abort404()

        return PrefsPage(content = content, infotext=infotext).render()


    @validate(dest = VDestination())
    def GET_login(self, dest):
        """The /login form.  No link to this page exists any more on
        the site (all actions invoking it now go through the login
        cover).  However, this page is still used for logging the user
        in during submission or voting from the bookmarklets."""

        if (c.user_is_loggedin and
            not request.environ.get('extension') == 'embed'):
            return self.redirect(dest)
        return LoginPage(dest = dest).render()

    @validate(VUser(),
              VModhash(),
              dest = VDestination())
    def GET_logout(self, dest):
        return self.redirect(dest)

    @validate(VUser(),
              VModhash(),
              dest = VDestination())
    def POST_logout(self, dest):
        """wipe login cookie and redirect to referer."""
        self.logout()
        return self.redirect(dest)


    @validate(VUser(),
              dest = VDestination())
    def GET_adminon(self, dest):
        """Enable admin interaction with site"""
        #check like this because c.user_is_admin is still false
        if not c.user.name in g.admins:
            return self.abort404()
        self.login(c.user, admin = True, rem = True)
        return self.redirect(dest)

    @validate(VAdmin(),
              dest = VDestination())
    def GET_adminoff(self, dest):
        """disable admin interaction with site."""
        if not c.user.name in g.admins:
            return self.abort404()
        self.login(c.user, admin = False, rem = True)
        return self.redirect(dest)

    def GET_validuser(self):
        """checks login cookie to verify that a user is logged in and
        returns their user name"""
        c.response_content_type = 'text/plain'
        if c.user_is_loggedin:
            perm = str(c.user.can_wiki())
            c.response.content = c.user.name + "," + perm
        else:
            c.response.content = ''
        return c.response

    @validate(msg_hash = nop('x'))
    def GET_optout(self, msg_hash):
        """handles /mail/optout to add an email to the optout mailing
        list.  The actual email addition comes from the user posting
        the subsequently rendered form and is handled in
        ApiController.POST_optout."""
        return self._render_opt_in_out(msg_hash, True)

    @validate(msg_hash = nop('x'))
    def GET_optin(self, msg_hash):
        """handles /mail/optin to remove an email address from the
        optout list. The actual email removal comes from the user
        posting the subsequently rendered form and is handled in
        ApiController.POST_optin."""
        return self._render_opt_in_out(msg_hash, False)

