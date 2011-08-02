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
from reddit_base import RedditController, base_listing, organic_pos
from validator import *

from r2.models import *
from r2.lib.pages import *
from r2.lib.pages.things import wrap_links
from r2.lib.menus import NewMenu, TimeMenu, SortMenu, RecSortMenu, ProfileSortMenu
from r2.lib.menus import ControversyTimeMenu
from r2.lib.rising import get_rising
from r2.lib.wrapped import Wrapped
from r2.lib.normalized_hot import normalized_hot, get_hot
from r2.lib.db.thing import Query, Merge, Relations
from r2.lib.db import queries
from r2.lib.strings import Score
from r2.lib import organic
from r2.lib.jsontemplates import is_api
from r2.lib.solrsearch import SearchQuery
from r2.lib.indextank import IndextankQuery
from r2.lib.utils import iters, check_cheating, timeago
from r2.lib.utils.trial_utils import populate_spotlight
from r2.lib import sup
from r2.lib.promote import randomized_promotion_list, get_promote_srid
import socket

from admin import admin_profile_query

from pylons.i18n import _
from pylons import Response

import random

class ListingController(RedditController):
    """Generalized controller for pages with lists of links."""

    # toggle skipping of links based on the users' save/hide/vote preferences
    skip = True

    # allow stylesheets on listings
    allow_stylesheets = True

    # toggles showing numbers 
    show_nums = True

    # any text that should be shown on the top of the page
    infotext = None

    # builder class to use to generate the listing. if none, we'll try
    # to figure it out based on the query type
    builder_cls = None

    # page title
    title_text = ''

    # login box, subreddit box, submit box, etc, visible
    show_sidebar = True

    # class (probably a subclass of Reddit) to use to render the page.
    render_cls = Reddit

    #extra parameters to send to the render_cls constructor
    render_params = {}

    @property
    def menus(self):
        """list of menus underneat the header (e.g., sort, time, kind,
        etc) to be displayed on this listing page"""
        return []

    @base_listing
    def build_listing(self, num, after, reverse, count):
        """uses the query() method to define the contents of the
        listing and renders the page self.render_cls(..).render() with
        the listing as contents"""
        self.num = num
        self.count = count
        self.after = after
        self.reverse = reverse

        self.query_obj = self.query()
        self.builder_obj = self.builder()
        self.listing_obj = self.listing()
        content = self.content()

        res = self.render_cls(content = content,
                              show_sidebar = self.show_sidebar,
                              nav_menus = self.menus,
                              title = self.title(),
                              robots = getattr(self, "robots", None),
                              **self.render_params).render()
        return res


    def content(self):
        """Renderable object which will end up as content of the render_cls"""
        return self.listing_obj
        
    def query(self):
        """Query to execute to generate the listing"""
        raise NotImplementedError

    def builder(self):
        #store the query itself so it can be used elsewhere
        if self.builder_cls:
            builder_cls = self.builder_cls
        elif isinstance(self.query_obj, Query):
            builder_cls = QueryBuilder
        elif isinstance(self.query_obj, (SearchQuery,IndextankQuery)):
            builder_cls = SearchBuilder
        elif isinstance(self.query_obj, iters):
            builder_cls = IDBuilder
        elif isinstance(self.query_obj, (queries.CachedResults, queries.MergedCachedResults)):
            builder_cls = IDBuilder

        b = builder_cls(self.query_obj,
                        num = self.num,
                        skip = self.skip,
                        after = self.after,
                        count = self.count,
                        reverse = self.reverse,
                        keep_fn = self.keep_fn(),
                        wrap = self.builder_wrapper)

        return b

    def keep_fn(self):
        def keep(item):
            wouldkeep = item.keep_item(item)
            if getattr(item, "promoted", None) is not None:
                return False
            if item._deleted and not c.user_is_admin:
                return False
            return wouldkeep
        return keep

    def listing(self):
        """Listing to generate from the builder"""
        if (getattr(c.site, "_id", -1) == get_promote_srid() and 
            not c.user_is_sponsor):
            abort(403, 'forbidden')
        listing = LinkListing(self.builder_obj, show_nums = self.show_nums)
        return listing.listing()

    def title(self):
        """Page <title>"""
        return _(self.title_text) + " : " + c.site.name

    def rightbox(self):
        """Contents of the right box when rendering"""
        pass

    builder_wrapper = staticmethod(default_thing_wrapper())

    def GET_listing(self, **env):
        check_cheating('site')
        return self.build_listing(**env)

class FixListing(object):
    """When sorting by hotness, computing a listing when the before/after
    link has a hottness of 0 is very slow. This class avoids drawing
    next/prev links when that will happen."""
    fix_listing = True

    def listing(self):
        listing = ListingController.listing(self)

        if not self.fix_listing:
            return listing

        #404 existing bad pages
        if self.after and self.after._hot == 0:
            self.abort404()

        #don't draw next/prev links for 
        if listing.things:
            if listing.things[-1]._hot == 0:
                listing.next = None

            if listing.things[0]._hot == 0:
                listing.prev = None

        return listing

class HotController(FixListing, ListingController):
    where = 'hot'

    def spotlight(self):
        if (isinstance(c.site, DefaultSR)
            and (not c.user_is_loggedin
                 or (c.user_is_loggedin and c.user.pref_organic))):

            spotlight_links = organic.organic_links(c.user)
            pos = organic_pos()

            if not spotlight_links:
                pos = 0
            elif pos != 0:
                pos = pos % len(spotlight_links)

            if c.user.pref_show_sponsors or not c.user.gold:
                spotlight_links, pos = promote.insert_promoted(spotlight_links, pos)
            trial = populate_spotlight()

            # Need to do this again, because if there was a duplicate removed,
            # pos might be pointing outside the list.
            if not spotlight_links:
                pos = 0
            elif pos != 0:
                pos = pos % len(spotlight_links)

            if trial:
                spotlight_links.insert(pos, trial._fullname)

            if not spotlight_links:
                return None

            # get links in proximity to pos
            num_tl = len(spotlight_links)
            if num_tl <= 3:
                disp_links = spotlight_links
            else:
                left_side = max(-1, min(num_tl - 3, 8))
                disp_links = [spotlight_links[(i + pos) % num_tl]
                              for i in xrange(-2, left_side)]

            def trial_keep_fn(item):
                if trial and trial._fullname == item._fullname:
                    return True
                return organic.keep_fresh_links(item)

            def trial_wrap(item):
               if item is trial:
                   w = Wrapped(item)
                   w.trial_mode = True
                   w.render_class = LinkOnTrial
                   return w
               return self.builder_wrapper(item)

            b = IDBuilder(disp_links,
                          wrap = trial_wrap if trial else self.builder_wrapper,
                          num = organic.organic_length,
                          skip = True,
                          keep_fn = trial_keep_fn if trial else organic.keep_fresh_links)

            try:
                vislink = spotlight_links[pos]
            except IndexError:
                g.log.error("spotlight_links = %r" % spotlight_links)
                g.log.error("pos = %d" % pos)
                raise

            s = SpotlightListing(b, spotlight_links = spotlight_links,
                                 visible_link = vislink,
                                 max_num = self.listing_obj.max_num,
                                 max_score = self.listing_obj.max_score).listing()

            if len(s.things) > 0:
                # only pass through a listing if the links made it
                # through our builder
                organic.update_pos(pos+1)
                return s

        # no organic box on a hot page, then show a random promoted link
        elif not isinstance(c.site, DefaultSR) and c.user.pref_show_sponsors:
            link_ids = randomized_promotion_list(c.user, c.site)
            if link_ids:
                res = wrap_links(link_ids, wrapper = self.builder_wrapper,
                                 num = 1, keep_fn = lambda x: x.fresh, 
                                 skip = True)
                if res.things:
                    return res

    def query(self):
        #no need to worry when working from the cache
        if g.use_query_cache or isinstance(c.site, DefaultSR):
            self.fix_listing = False

        if isinstance(c.site, DefaultSR):
            if c.user_is_loggedin:
                srlimit = Subreddit.DEFAULT_LIMIT
                over18 = c.user.has_subscribed and c.over18
            else:
                srlimit = g.num_default_reddits
                over18 = False

            sr_ids = Subreddit.user_subreddits(c.user,
                                               limit=srlimit,
                                               over18=over18)
            return normalized_hot(sr_ids)
        #if not using the query_cache we still want cached front pages
        elif (not g.use_query_cache
              and not isinstance(c.site, FakeSubreddit)
              and self.after is None
              and self.count == 0):
            return get_hot([c.site])
        else:
            return c.site.get_links('hot', 'all')

    def content(self):
        # only send a spotlight listing for HTML rendering
        if c.render_style == "html":
            spotlight = self.spotlight()
            if spotlight:
                return PaneStack([spotlight, self.listing_obj], css_class='spacer')
        return self.listing_obj

    def title(self):
        return c.site.title

    def GET_listing(self, **env):
        self.infotext = request.get.get('deleted') and strings.user_deleted
        return ListingController.GET_listing(self, **env)

class SavedController(ListingController):
    where = 'saved'
    skip = False
    title_text = _('saved')

    def query(self):
        return queries.get_saved(c.user)

    @validate(VUser())
    def GET_listing(self, **env):
        return ListingController.GET_listing(self, **env)

class NewController(ListingController):
    where = 'new'
    title_text = _('newest submissions')

    @property
    def menus(self):
        return [NewMenu(default = self.sort)]

    def keep_fn(self):
        def keep(item):
            """Avoid showing links that are too young, to give time
            for things like the spam filter and thumbnail fetcher to
            act on them before releasing them into the wild"""
            wouldkeep = item.keep_item(item)
            if item.promoted is not None:
                return False
            elif c.user_is_loggedin and (c.user_is_admin or
                                         item.subreddit.is_moderator(c.user)):
                # let admins and moderators see them regardless
                return wouldkeep
            elif wouldkeep and c.user_is_loggedin and c.user._id == item.author_id:
                # also let the author of the link see them
                return True
            else:
                # otherwise, fall back to the regular logic (don't
                # show hidden links, etc)
                return wouldkeep

        return keep

    def query(self):
        if self.sort == 'rising':
            return get_rising(c.site)
        else:
            return c.site.get_links('new', 'all')

    @validate(sort = VMenu('controller', NewMenu))
    def POST_listing(self, sort, **env):
        # VMenu validator will save the value of sort before we reach this
        # point. Now just redirect to GET mode.
        return self.redirect(request.fullpath + query_string(dict(sort=sort)))

    @validate(sort = VMenu('controller', NewMenu))
    def GET_listing(self, sort, **env):
        self.sort = sort
        return ListingController.GET_listing(self, **env)

class BrowseController(ListingController):
    where = 'browse'

    def keep_fn(self):
        """For merged time-listings, don't show items that are too old
           (this can happen when mr_top hasn't run in a while)"""
        if self.time != 'all' and c.default_sr:
            oldest = timeago('1 %s' % (str(self.time),))
            def keep(item):
                return item._date > oldest and item.keep_item(item)
            return keep
        else:
            return ListingController.keep_fn(self)

    @property
    def menus(self):
        return [ControversyTimeMenu(default = self.time)]

    def query(self):
        return c.site.get_links(self.sort, self.time)

    # TODO: this is a hack with sort.
    @validate(sort = VOneOf('sort', ('top', 'controversial')),
              t = VMenu('sort', ControversyTimeMenu))
    def POST_listing(self, sort, t, **env):
        # VMenu validator will save the value of time before we reach this
        # point. Now just redirect to GET mode.
        return self.redirect(
            request.fullpath + query_string(dict(sort=sort, t=t)))

    # TODO: this is a hack with sort.
    @validate(sort = VOneOf('sort', ('top', 'controversial')),
              t = VMenu('sort', ControversyTimeMenu))
    def GET_listing(self, sort, t, **env):
        self.sort = sort
        if sort == 'top':
            self.title_text = _('top scoring links')
        elif sort == 'controversial':
            self.title_text = _('most controversial links')
        self.time = t
        return ListingController.GET_listing(self, **env)


class RandomrisingController(ListingController):
    where = 'randomrising'
    title_text = _('you\'re really bored now, eh?')

    def query(self):
        links = get_rising(c.site)

        if not links:
            # just pull from the new page if the rising page isn't
            # populated for some reason
            links = c.site.get_links('new', 'all')
            if isinstance(links, Query):
                links._limit = 200
                links = [x._fullname for x in links]

        links = list(links)
        random.shuffle(links)

        return links

class ByIDController(ListingController):
    title_text = _('API')
    skip = False

    def query(self):
        return self.names

    @validate(links = VByName("names", thing_cls = Link, multiple = True))
    def GET_listing(self, links, **env):
        if not links:
            return self.abort404()
        self.names = [l._fullname for l in links]
        return ListingController.GET_listing(self, **env)


#class RecommendedController(ListingController):
#    where = 'recommended'
#    title_text = _('recommended for you')
#
#    @property
#    def menus(self):
#        return [RecSortMenu(default = self.sort)]
#
#    def query(self):
#        return get_recommended(c.user._id, sort = self.sort)
#
#    @validate(VUser(),
#              sort = VMenu("controller", RecSortMenu))
#    def GET_listing(self, sort, **env):
#        self.sort = sort
#        return ListingController.GET_listing(self, **env)

class UserController(ListingController):
    render_cls = ProfilePage
    show_nums = False

    @property
    def menus(self):
        res = []
        if (self.where in ('overview', 'submitted', 'comments')):
            res.append(ProfileSortMenu(default = self.sort))
            if self.sort not in ("hot", "new"):
                res.append(TimeMenu(default = self.time))
        return res

    def title(self):
        titles = {'overview': _("overview for %(user)s"),
                  'comments': _("comments by %(user)s"),
                  'submitted': _("submitted by %(user)s"),
                  'liked': _("liked by %(user)s"),
                  'disliked': _("disliked by %(user)s"),
                  'hidden': _("hidden by %(user)s")}
        title = titles.get(self.where, _('profile for %(user)s')) \
            % dict(user = self.vuser.name, site = c.site.name)
        return title

    # TODO: this might not be the place to do this
    skip = True
    def keep_fn(self):
        # keep promotions off of profile pages.
        def keep(item):
            wouldkeep = True
            # TODO: Consider a flag to disable this (and see below plus builder.py)
            if item._deleted and not c.user_is_admin:
                return False
            if self.time != 'all':
                wouldkeep = (item._date > utils.timeago('1 %s' % str(self.time)))
            if c.user == self.vuser:
                if not item.likes and self.where == 'liked':
                    return False
                if item.likes is not False and self.where == 'disliked':
                    return False
            return wouldkeep and (getattr(item, "promoted", None) is None and
                    (self.where == "deleted" or
                     not getattr(item, "deleted", False)))
        return keep

    def query(self):
        q = None
        if self.where == 'overview':
            self.check_modified(self.vuser, 'overview')
            q = queries.get_overview(self.vuser, self.sort, self.time)

        elif self.where == 'comments':
            sup.set_sup_header(self.vuser, 'commented')
            self.check_modified(self.vuser, 'commented')
            q = queries.get_comments(self.vuser, self.sort, self.time)

        elif self.where == 'submitted':
            sup.set_sup_header(self.vuser, 'submitted')
            self.check_modified(self.vuser, 'submitted')
            q = queries.get_submitted(self.vuser, self.sort, self.time)

        elif self.where in ('liked', 'disliked'):
            sup.set_sup_header(self.vuser, self.where)
            self.check_modified(self.vuser, self.where)
            if self.where == 'liked':
                q = queries.get_liked(self.vuser)
            else:
                q = queries.get_disliked(self.vuser)

        elif self.where == 'hidden':
            q = queries.get_hidden(self.vuser)

        elif c.user_is_admin:
            q = admin_profile_query(self.vuser, self.where, desc('_date'))

        if q is None:
            return self.abort404()

        return q

    @validate(vuser = VExistingUname('username'),
              sort = VMenu('sort', ProfileSortMenu, remember = False),
              time = VMenu('t', TimeMenu, remember = False))
    def GET_listing(self, where, vuser, sort, time, **env):
        self.where = where
        self.sort = sort
        self.time = time

        # the validator will ensure that vuser is a valid account
        if not vuser:
            return self.abort404()

        if self.sort in  ('hot', 'new'):
            self.time = 'all'


        # hide spammers profile pages
        if (not c.user_is_loggedin or
            (c.user._id != vuser._id and not c.user_is_admin)) \
               and vuser._spam:
            return self.abort404()

        if (where not in ('overview', 'submitted', 'comments')
            and not votes_visible(vuser)):
            return self.abort404()

        check_cheating('user')

        self.vuser = vuser
        self.render_params = {'user' : vuser}
        c.profilepage = True

        if vuser.pref_hide_from_robots:
            self.robots = 'noindex,nofollow'

        return ListingController.GET_listing(self, **env)

    @validate(vuser = VExistingUname('username'))
    def GET_about(self, vuser):
        if not is_api() or not vuser:
            return self.abort404()
        return Reddit(content = Wrapped(vuser)).render()

class MessageController(ListingController):
    show_sidebar = False
    show_nums = False
    render_cls = MessagePage
    allow_stylesheets = False

    @property
    def menus(self):
        if c.default_sr and self.where in ('inbox', 'messages', 'comments',
                          'selfreply', 'unread'):
            buttons = (NavButton(_("all"), "inbox"),
                       NavButton(_("unread"), "unread"),
                       NavButton(plurals.messages, "messages"),
                       NavButton(_("comment replies"), 'comments'),
                       NavButton(_("post replies"), 'selfreply'))

            return [NavMenu(buttons, base_path = '/message/',
                            default = 'inbox', type = "flatlist")]
        elif not c.default_sr or self.where == 'moderator':
            buttons = (NavButton(_("all"), "inbox"),
                       NavButton(_("unread"), "unread"))
            return [NavMenu(buttons, base_path = '/message/moderator/',
                            default = 'inbox', type = "flatlist")]
        return []


    def title(self):
        return _('messages') + ': ' + _(self.where)

    def keep_fn(self):
        def keep(item):
            wouldkeep = item.keep_item(item)

            # TODO: Consider a flag to disable this (and see above plus builder.py)
            if (item._deleted or item._spam) and not c.user_is_admin:
                return False
            if item.author_id in c.user.enemies:
                return False
            # don't show user their own unread stuff
            if ((self.where == 'unread' or self.subwhere == 'unread')
                and (item.author_id == c.user._id or not item.new)):
                return False

            return wouldkeep
        return keep

    @staticmethod
    def builder_wrapper(thing):
        if isinstance(thing, Comment):
            f = thing._fullname
            w = Wrapped(thing)
            w.render_class = Message
            w.to_id = c.user._id
            w.was_comment = True
            w._fullname = f
        else:
            w = ListingController.builder_wrapper(thing)

        return w

    def builder(self):
        if (self.where == 'messages' or
            (self.where == "moderator" and self.subwhere != "unread")):
            root = c.user
            message_cls = UserMessageBuilder
            if not c.default_sr:
                root = c.site
                message_cls = SrMessageBuilder
            elif self.where == 'moderator' and self.subwhere != 'unread':
                message_cls = ModeratorMessageBuilder

            parent = None
            skip = False
            if self.message:
                if self.message.first_message:
                    parent = Message._byID(self.message.first_message,
                                           data=True)
                else:
                    parent = self.message
            elif c.user.pref_threaded_messages:
                skip = (c.render_style == "html")

            return message_cls(root,
                               wrap = self.builder_wrapper,
                               parent = parent,
                               skip = skip,
                               num = self.num,
                               after = self.after,
                               keep_fn = self.keep_fn(),
                               reverse = self.reverse)
        return ListingController.builder(self)

    def listing(self):
        if (self.where == 'messages' and 
            (c.user.pref_threaded_messages or self.message)):
            return Listing(self.builder_obj).listing()
        return ListingController.listing(self)

    def query(self):
        if self.where == 'messages':
            q = queries.get_inbox_messages(c.user)
        elif self.where == 'comments':
            q = queries.get_inbox_comments(c.user)
        elif self.where == 'selfreply':
            q = queries.get_inbox_selfreply(c.user)
        elif self.where == 'inbox':
            q = queries.get_inbox(c.user)
        elif self.where == 'unread':
            q = queries.get_unread_inbox(c.user)
        elif self.where == 'sent':
            q = queries.get_sent(c.user)
        elif self.where == 'moderator' and self.subwhere == 'unread':
            if c.default_sr:
                srids = Subreddit.reverse_moderator_ids(c.user)
                srs = Subreddit._byID(srids, data = False, return_dict = False)
                q = queries.merge_results(
                    *[queries.get_unread_subreddit_messages(s) for s in srs])
            else:
                q = queries.get_unread_subreddit_messages(c.site)
        elif self.where == 'moderator':
            if c.have_mod_messages and self.mark != 'false':
                c.user.modmsgtime = False
                c.user._commit()
            # the query is handled by the builder on the moderator page
            return
        else:
            return self.abort404()
        if self.where != 'sent':
            #reset the inbox
            if c.have_messages and self.mark != 'false':
                c.user.msgtime = False
                c.user._commit()

        return q

    @validate(VUser(),
              message = VMessageID('mid'),
              mark = VOneOf('mark',('true','false')))
    def GET_listing(self, where, mark, message, subwhere = None, **env):
        if not (c.default_sr or c.site.is_moderator(c.user) or c.user_is_admin):
            abort(403, "forbidden")
        if not c.default_sr:
            self.where = "moderator"
        else:
            self.where = where
        self.subwhere = subwhere
        if mark is not None:
            self.mark = mark
        elif is_api():
            self.mark = 'false'
        elif c.render_style and c.render_style == "xml":
            self.mark = 'false'
        else:
            self.mark = 'true'
        self.message = message
        return ListingController.GET_listing(self, **env)

    @validate(VUser(),
              to = nop('to'),
              subject = nop('subject'),
              message = nop('message'),
              success = nop('success'))
    def GET_compose(self, to, subject, message, success):
        captcha = Captcha() if c.user.needs_captcha() else None
        content = MessageCompose(to = to, subject = subject,
                                 captcha = captcha,
                                 message = message,
                                 success = success)
        return MessagePage(content = content).render()

class RedditsController(ListingController):
    render_cls = SubredditsPage

    def title(self):
        return _('reddits')

    def query(self):
        if self.where == 'banned' and c.user_is_admin:
            reddits = Subreddit._query(Subreddit.c._spam == True,
                                       sort = desc('_date'),
                                       write_cache = True,
                                       read_cache = True,
                                       cache_time = 5 * 60)
        else:
            reddits = None
            if self.where == 'new':
                reddits = Subreddit._query( write_cache = True,
                                            read_cache = True,
                                            cache_time = 5 * 60)
                reddits._sort = desc('_date')
            else:
                reddits = Subreddit._query( write_cache = True,
                                            read_cache = True,
                                            cache_time = 60 * 60)
                reddits._sort = desc('_downs')
            # Consider resurrecting when it is not the World Cup
            #if c.content_langs != 'all':
            #    reddits._filter(Subreddit.c.lang == c.content_langs)

            if g.domain != 'reddit.com':
                # don't try to render special subreddits (like promos)
                reddits._filter(Subreddit.c.author_id != -1)

            if not c.over18:
                reddits._filter(Subreddit.c.over_18 == False)

        return reddits
    def GET_listing(self, where, **env):
        self.where = where
        return ListingController.GET_listing(self, **env)

class MyredditsController(ListingController):
    render_cls = MySubredditsPage

    @property
    def menus(self):
        buttons = (NavButton(plurals.subscriber,  'subscriber'),
                    NavButton(getattr(plurals, "approved submitter"), 'contributor'),
                    NavButton(plurals.moderator,   'moderator'))

        return [NavMenu(buttons, base_path = '/reddits/mine/',
                        default = 'subscriber', type = "flatlist")]

    def title(self):
        return _('reddits: ') + self.where

    def query(self):
        reddits = SRMember._query(SRMember.c._name == self.where,
                                  SRMember.c._thing2_id == c.user._id,
                                  #hack to prevent the query from
                                  #adding it's own date
                                  sort = (desc('_t1_ups'), desc('_t1_date')),
                                  eager_load = True,
                                  thing_data = True)
        reddits.prewrap_fn = lambda x: x._thing1
        return reddits

    def content(self):
        user = c.user if c.user_is_loggedin else None
        num_subscriptions = len(Subreddit.reverse_subscriber_ids(user))
        if self.where == 'subscriber' and num_subscriptions == 0:
            message = strings.sr_messages['empty']
        else:
            message = strings.sr_messages.get(self.where)

        stack = PaneStack()

        if message:
            stack.append(InfoBar(message=message))

        stack.append(self.listing_obj)

        return stack

    @validate(VUser())
    def GET_listing(self, where = 'inbox', **env):
        self.where = where
        return ListingController.GET_listing(self, **env)

class CommentsController(ListingController):
    title_text = _('comments')

    def query(self):
        return c.site.get_all_comments()

    def GET_listing(self, **env):
        c.profilepage = True
        return ListingController.GET_listing(self, **env)

