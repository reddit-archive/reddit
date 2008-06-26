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
from validator import *
from pylons.i18n import _, ungettext
from reddit_base import RedditController, base_listing
from api import link_listing_by_url
from r2 import config
from r2.models import *
from r2.lib.pages import *
from r2.lib.menus import *
from r2.lib.utils import  to36, sanitize_url, check_cheating
from r2.lib.db.operators import desc
from r2.lib.strings import strings
import r2.lib.db.thing as thing
from listingcontroller import ListingController
from pylons import c, request

import random as rand
import re

from admin import admin_profile_query

class FrontController(RedditController):

    def GET_oldinfo(self, name, rest):
        """Legacy: supporting permalink pages from '06"""
        #this could go in config, but it should never change
        max_link_id = 10000000
        new_id = max_link_id - int(name)
        return self.redirect('/info/' + to36(new_id) + '/' + rest)

    def GET_random(self):
        """The Serendipity button"""
        n = rand.randint(0, 9)
        links = Link._query(*c.site.query_rules())
        links._sort = desc('_date') if n > 5 else desc('_hot')
        links._limit = 50
        links = list(links)
        l = links[rand.randint(0, len(links)-1)]
        l._load()
        return self.redirect(l.url)

    def GET_password(self):
        """The 'what is my password' page"""
        return BoringPage(_("password"), content=Password()).render()

    @validate(user = VCacheKey('reset', ('key', 'name')),
              key = nop('key'))
    def GET_resetpassword(self, user, key):
        """page hit once a user has been sent a password reset email
        to verify their identity before allowing them to update their
        password."""
        done = False
        if not key and request.referer:
            referer_path =  request.referer.split(c.domain)[-1]
            done = referer_path.startswith(request.fullpath)
        elif not user:
            return self.abort404()
        return BoringPage(_("reset password"),
                          content=ResetPassword(key=key, done=done)).render()

    @validate(VAdmin(),
              article = VLink('article'))
    def GET_details(self, article):
        """The (now depricated) details page.  Content on this page
        has been subsubmed by the presence of the LinkInfoBar on the
        rightbox, so it is only useful for Admin-only wizardry."""
        return DetailsPage(link = article).render()
    

    @validate(article      = VLink('article'),
              comment      = VCommentID('comment'),
              context      = VInt('context', min = 0, max = 8),
              sort         = VMenu('controller', CommentSortMenu),
              num_comments = VMenu('controller', NumCommentsMenu))
    def GET_comments(self, article, comment, context, sort, num_comments):
        """Comment page for a given 'article'."""
        if not c.default_sr and c.site._id != article.sr_id: 
            return self.abort404()

        # if there is a focal comment, communicate down to comment_skeleton.html who
        # that will be
        if comment:
            c.focal_comment = comment._id36

        # check if we just came from the submit page
        infotext = None
        if request.get.get('already_submitted'):
            infotext = strings.already_submitted % article.resubmit_link()

        check_cheating('comments')

        # figure out number to show based on the menu
        user_num = c.user.pref_num_comments or g.num_comments
        num = g.max_comments if num_comments == 'true' else user_num

        builder = CommentBuilder(article, CommentSortMenu.operator(sort), 
                                 comment, context)
        listing = NestedListing(builder, num = num,
                                parent_name = article._fullname)
        
        displayPane = PaneStack()

        # if permalink page, add that message first to the content
        if comment:
            displayPane.append(PermalinkMessage(article.permalink))

        # insert reply box only for logged in user
        if c.user_is_loggedin and article.subreddit_slow.can_comment(c.user):
            displayPane.append(CommentReplyBox())
            #no comment box for permalinks
            if not comment:
                displayPane.append(CommentReplyBox(link_name = 
                                                   article._fullname))
        # finally add the comment listing
        displayPane.append(listing.listing())

        loc = None if c.focal_comment or context is not None else 'comments'
        
        res = LinkInfoPage(link = article, 
                           content = displayPane, 
                           nav_menus = [CommentSortMenu(default = sort), 
                                        NumCommentsMenu(article.num_comments,
                                                        default=num_comments)],
                           infotext = infotext).render()
        return res
    

    @base_listing
    @validate(vuser    = VExistingUname('username'),
              location = nop('location', default = ''),
              sort     = VMenu('location', SortMenu),
              time     = VMenu('location', TimeMenu))
    def GET_user(self, num, vuser, sort, time, after, reverse, count, location, **env):
        """user profile pages"""

        # the validator will ensure that vuser is a valid account
        if not vuser:
            return self.abort404()

        # hide spammers profile pages
        if (not c.user_is_loggedin or 
            (c.user._id != vuser._id and not c.user_is_admin)) \
               and vuser._spam:
            return self.abort404()

        check_cheating('user')
        
        content_pane = PaneStack()

        # enable comments displaying with their titles when rendering
        c.profilepage = True
        listing = None

        db_sort = SortMenu.operator(sort)
        db_time = TimeMenu.operator(time)

        # function for extracting the proper thing if query is a relation (see liked)
        prewrap_fn = None

        # default (nonexistent) query to trip an error on if location is unhandles
        query      = None
        
        # build the sort menus for the space above the content
        sortbar = [SortMenu(default = sort), TimeMenu(default = time)]

        # overview page is a merge of comments and links
        if location == 'overview':
            links = Link._query(Link.c.author_id == vuser._id,
                                Link.c._spam == (True, False))
            comments = Comment._query(Comment.c.author_id == vuser._id,
                                      Comment.c._spam == (True, False))
            query = thing.Merge((links, comments), sort = db_sort, data = True)

        elif location == 'comments':
            query = Comment._query(Comment.c.author_id == vuser._id,
                                   Comment.c._spam == (True, False),
                                   sort = db_sort)

        elif location == 'submitted':
            query = Link._query(Link.c.author_id == vuser._id,
                                Link.c._spam == (True, False),
                                sort = db_sort)

        # (dis)liked page: pull votes and extract thing2
        elif ((location == 'liked' or location == 'disliked') and
              votes_visible(vuser)):
            rel = Vote.rel(vuser, Link)
            query = rel._query(rel.c._thing1_id == vuser._id,
                               rel.c._t2_deleted == False)
            query._eager(True, True)
            
            if location == 'liked':
                query._filter(rel.c._name == '1')
            else:
                query._filter(rel.c._name == '-1')
            sortbar = []
            query._sort = desc('_date')
            prewrap_fn = lambda x: x._thing2

        # TODO: this should be handled with '' above once merges work
        elif location == 'hidden' and votes_visible(vuser):
            db_time = None
            query = SaveHide._query(SaveHide.c._thing1_id == vuser._id,
                                    SaveHide.c._name == 'hide',
                                    eager_load = True,
                                    thing_data = True)
            sortbar = []
            query._sort = desc('_date')
            prewrap_fn = lambda x: x._thing2

        # any admin pages live here.
        elif c.user_is_admin:
            db_time = None
            query, prewrap_fn = admin_profile_query(vuser, location, db_sort)

        if query is None:
            return self.abort404()

        if db_time:
            query._filter(db_time)


        builder = QueryBuilder(query, num = num, prewrap_fn = prewrap_fn,
                               after = after, count = count, reverse = reverse,
                               wrap = ListingController.builder_wrapper)
        listing = LinkListing(builder)

        if listing:
            content_pane.append(listing.listing())

        titles = {'':          _("overview for %(user)s on %(site)s"),
                  'comments':  _("comments by %(user)s on %(site)s"),
                  'submitted': _("submitted by %(user)s on %(site)s"),
                  'liked':     _("liked by %(user)s on %(site)s"),
                  'disliked':  _("disliked by %(user)s on %(site)s"),
                  'hidden':    _("hidden by %(user)s on %(site)s")}
        title = titles.get(location, _('profile for %(user)s')) \
               % dict(user = vuser.name, site = c.site.name)

        return ProfilePage(vuser, title = title,
                           nav_menus = sortbar, 
                           content = content_pane).render()


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
        elif location == 'delete':
            content = PrefDelete()

        return PrefsPage(content = content, infotext=infotext).render()

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

    @base_listing
    @validate(location = nop('location'))
    def GET_editreddit(self, location, num, after, reverse, count):
        """Edit reddit form. """
        if isinstance(c.site, FakeSubreddit):
            return self.abort404()

        # moderator is either reddit's moderator or an admin
        is_moderator = c.user_is_loggedin and c.site.is_moderator(c.user) or c.user_is_admin

        if is_moderator and location == 'edit':
            pane = CreateSubreddit(site = c.site)
        elif location == 'moderators':
            pane = ModList(editable = is_moderator)
        elif is_moderator and location == 'banned':
            pane = BannedList(editable = is_moderator)
        elif location == 'contributors' and c.site.type != 'public':
            pane = ContributorList(editable = is_moderator)
        elif is_moderator and location == 'spam':
            links = Link._query(Link.c._spam == True)
            comments = Comment._query(Comment.c._spam == True)
            query = thing.Merge((links, comments),
                                sort = desc('_date'),
                                data = True,
                                *c.site.query_rules())
            
            builder = QueryBuilder(query, num = num, after = after, 
                                   count = count, reverse = reverse,
                                   wrap = ListingController.builder_wrapper)
            listing = LinkListing(builder)
            pane = listing.listing()
        else:
            return self.abort404()

        return EditReddit(content = pane).render()
                              
    def GET_stats(self):
        """The stats page."""
        return BoringPage(_("stats"), content = UserStats()).render()

    # filter for removing punctuation which could be interpreted as lucene syntax
    related_replace_regex = re.compile('[?\\&|!{}+~^()":*-]+')
    related_replace_with  = ' '

    @base_listing
    @validate(article = VLink('article'))
    def GET_related(self, num, article, after, reverse, count):
        """Related page: performs a search using title of article as
        the search query."""
        title = c.site.name + ((': ' + article.title) if hasattr(article, 'title') else '')

        query = self.related_replace_regex.sub(self.related_replace_with,
                                               article.title)
        if len(query) > 1024:
            # could get fancier and break this into words, but titles
            # longer than this are typically ascii art anyway
            query = query[0:1023]

        num, t, pane = self._search(query, time = 'all',
                                    count = count,
                                    after = after, reverse = reverse, num = num,
                                    ignore = [article._fullname],
                                    types = [Link])
        res = LinkInfoPage(link = article, content = pane).render()
        return res

    @base_listing
    @validate(query = nop('q'))
    def GET_search_reddits(self, query, reverse, after,  count, num):
        """Search reddits by title and description."""
        num, t, spane = self._search(query, num = num, types = [Subreddit],
                                     sort='points desc', time='all',
                                     after = after, reverse = reverse, 
                                     count = count)
        
        res = SubredditsPage(content=spane, 
                             prev_search = query,
                             elapsed_time = t,
                             num_results = num,
                             title = _("search results")).render()
        return res

    verify_langs_regex = re.compile(r"^[a-z][a-z](,[a-z][a-z])*$")
    @base_listing
    @validate(query=nop('q'),
              time = VMenu('action', TimeMenu, remember = False),
              langs = nop('langs'))
    def GET_search(self, query, num, time, reverse, after, count, langs):
        """Search links page."""
        if query and '.' in query:
            url = sanitize_url(query, require_scheme = True)
            if url:
                return self.redirect("/submit" + query_string({'url':url}))

        if langs and self.verify_langs_regex.match(langs):
            langs = langs.split(',')
        else:
            langs = None

        num, t, spane = self._search(query, time=time,
                                     num = num, after = after, 
                                     reverse = reverse,
                                     count = count, types = [Link])

        res = SearchPage(_('search results'), query, t, num, content=spane,
                         nav_menus = [TimeMenu(default = time)]).render()
        
        return res
        
    def _search(self, query = '', time=None,
                sort = 'hot desc',
                after = None, reverse = False, num = 25, 
                ignore = None, count=0, types = None,
                langs = None):
        """Helper function for interfacing with search.  Basically a
        thin wrapper for SearchBuilder."""
        builder = SearchBuilder(query, num = num,
                                sort = sort,
                                after = after, reverse = reverse,
                                count = count, types = types, 
                                time = time, ignore = ignore,
                                langs = langs,
                                wrap = ListingController.builder_wrapper)
        listing = LinkListing(builder, show_nums=True)

        # have to do it in two steps since total_num and timing are only
        # computed after fetch_more
        res = listing.listing()
        return builder.total_num, builder.timing, res



    def GET_login(self):
        """The /login form.  No link to this page exists any more on
        the site (all actions invoking it now go through the login
        cover).  However, this page is still used for logging the user
        in during submission or voting from the bookmarklets."""

        # dest is the location to redirect to upon completion
        dest = request.get.get('dest','') or request.referer or '/'
        return LoginPage(dest = dest).render()

    def GET_logout(self):
        """wipe login cookie and redirect to referer."""
        self.logout()
        dest = request.referer or '/'
        return self.redirect(dest)

    
    @validate(VUser())
    def GET_adminon(self):
        """Enable admin interaction with site"""
        #check like this because c.user_is_admin is still false
        if not c.user.name in g.admins:
            return self.abort404()
        self.login(c.user, admin = True)
        
        dest = request.referer or '/'
        return self.redirect(dest)

    @validate(VAdmin())
    def GET_adminoff(self):
        """disable admin interaction with site."""
        if not c.user.name in g.admins:
            return self.abort404()
        self.login(c.user, admin = False)
        
        dest = request.referer or '/'
        return self.redirect(dest)

    def GET_validuser(self):
        """checks login cookie to verify that a user is logged in and
        returns their user name"""
        c.response_content_type = 'text/plain'
        if c.user_is_loggedin:
            return c.user.name
        else:
            return ''


    @validate(VUser(),
              VSRSubmitPage(),
              url = VRequired('url', None),
              title = VRequired('title', None))
    def GET_submit(self, url, title):
        """Submit form."""
        if url and not request.get.get('resubmit'):
            # check to see if the url has already been submitted
            listing = link_listing_by_url(url)
            redirect_link = None
            if listing.things:
                # if there is only one submission, the operation is clear
                if len(listing.things) == 1:
                    redirect_link = listing.things[0]
                # if there is more than one, check the users' subscriptions
                else:
                    subscribed = [l for l in listing.things
                                  if c.user_is_loggedin 
                                  and l.subreddit.is_subscriber_defaults(c.user)]
                    
                    #if there is only 1 link to be displayed, just go there
                    if len(subscribed) == 1:
                        redirect_link = subscribed[0]
                    else:
                        infotext = strings.multiple_submitted % \
                                   listing.things[0].resubmit_link()
                        res = BoringPage(_("seen it"),
                                         content = listing,
                                         infotext = infotext).render()
                        return res

            # we've found a link already.  Redirect to its permalink page
            if redirect_link:
                return self.redirect(redirect_link.already_submitted_link)
            
        captcha = Captcha() if c.user.needs_captcha() else None
        sr_names = Subreddit.submit_sr_names(c.user) if c.default_sr else ()

        return FormPage(_("submit"), 
                        content=NewLink(url=url or '',
                                        title=title or '',
                                        subreddits = sr_names,
                                        captcha=captcha)).render()
