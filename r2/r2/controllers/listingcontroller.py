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
from reddit_base import RedditController, base_listing
from validator import *

from r2.models import *
from r2.lib.pages import *
from r2.lib.menus import NewMenu, TimeMenu, SortMenu, RecSortMenu, ControversyTimeMenu
from r2.lib.rising import get_rising
from r2.lib.wrapped import Wrapped
from r2.lib.normalized_hot import normalized_hot, get_hot
from r2.lib.recommendation import get_recommended
from r2.lib.db.thing import Query
from r2.lib.strings import Score
from r2.lib import organic

from pylons.i18n import _

import random


class ListingController(RedditController):
    """Generalized controller for pages with lists of links."""

    # toggle skipping of links based on the users' save/hide/vote preferences
    skip = True

    # toggles showing numbers 
    show_nums = True

    # for use with builder inm build_listing.  function applied to the
    # elements of query() upon iteration
    prewrap_fn = None

    # any text that should be shown on the top of the page
    infotext = None

    # builder class to use to generate the listing
    builder_cls = QueryBuilder

    # page title
    title_text = ''

    # toggles the stat collector for keeping track of what queries are being run
    collect_stats = False

    # login box, subreddit box, submit box, etc, visible
    show_sidebar = True

    # class (probably a subclass of Reddit) to use to render the page.
    render_cls = Reddit

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

        if self.collect_stats and g.REDDIT_MAIN:
            self.query_obj._stats_collector = g.stats_collector

        self.builder_obj = self.builder()
        self.listing_obj = self.listing()
        content = self.content()
        res =  self.render_cls(content = content,
                               show_sidebar = self.show_sidebar, 
                               nav_menus = self.menus, 
                               title = self.title(),
                               infotext = self.infotext).render()
        return res


    def content(self):
        """Renderable object which will end up as content of the render_cls"""
        return self.listing_obj
        
    def query(self):
        """Query to execute to generate the listing"""
        raise NotImplementedError

    def builder(self):
        #store the query itself so it can be used elsewhere
        b = self.builder_cls(self.query_obj,
                             num = self.num,
                             skip = self.skip,
                             after = self.after,
                             count = self.count,
                             reverse = self.reverse,
                             prewrap_fn = self.prewrap_fn,
                             wrap = self.builder_wrapper)
        return b

    def listing(self):
        """Listing to generate from the builder"""
        listing = LinkListing(self.builder_obj, show_nums = self.show_nums)
        return listing.listing()

    def title(self):
        """Page <title>"""
        return c.site.name + ': ' + _(self.title_text)

    def rightbox(self):
        """Contents of the right box when rendering"""
        pass

    @staticmethod
    def builder_wrapper(thing):
        if c.user.pref_compress and isinstance(thing, Link):
            thing.__class__ = LinkCompressed
            thing.score_fmt = Score.points
        return Wrapped(thing)

    def GET_listing(self, **env):
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

    def organic(self):
        o_links, pos = organic.organic_links(c.user)
        if o_links:
            # get links in proximity to pos
            disp_links = [o_links[(i + pos) % len(o_links)] for i in xrange(-2, 8)]

            b = IDBuilder(disp_links,
                          wrap = self.builder_wrapper)
            o = OrganicListing(b,
                               org_links = o_links,
                               visible_link = o_links[pos],
                               max_num = self.listing_obj.max_num,
                               max_score = self.listing_obj.max_score)
            organic.update_pos(c.user, (pos + 1) % len(o_links))
            return o.listing()


    def query(self):
        if c.site == Default:
            self.fix_listing = False
            self.builder_cls = IDBuilder
            user = c.user if c.user_is_loggedin else None
            sr_ids = Subreddit.user_subreddits(user)
            links = normalized_hot(sr_ids)
            return links
        elif (not isinstance(c.site, FakeSubreddit)
              and self.after is None
              and self.count == 0):
            self.builder_cls = IDBuilder
            links = [l._fullname for l in get_hot(c.site)]
            return links
        else:
            q = Link._query(sort = desc('_hot'), *c.site.query_rules())
            q._read_cache = True
            self.collect_stats = True
            return q

    def content(self):
        # only send an organic listing for HTML rendering
        if (c.site == Default and c.render_style == "html"
            and c.user_is_loggedin and c.user.pref_organic):
            org = self.organic()
            if org:
                return PaneStack([org, self.listing_obj], css_class='spacer')
        return self.listing_obj

    def title(self):
        return c.site.title

    @validate(VSrMask('srs'))
    def GET_listing(self, **env):
        self.infotext = request.get.get('deleted') and strings.user_deleted
        return ListingController.GET_listing(self, **env)

class NormalizedController(ListingController):
    where = 'normalized'
    builder_cls = IDBuilder

    def query(self):
        user = c.user if c.user_is_loggedin else None
        srs = Subreddit._byID(Subreddit.user_subreddits(user),
                              data = True,
                              return_dict = False)
        links = normalized_hot(srs)
        return links

    def title(self):
        return c.site.title

class SavedController(ListingController):
    prewrap_fn = lambda self, x: x._thing2
    where = 'saved'
    skip = False
    title_text = _('saved')

    def query(self):
        q = SaveHide._query(SaveHide.c._thing1_id == c.user._id,
                            SaveHide.c._name == 'save',
                            sort = desc('_date'),
                            eager_load = True, thing_data = True)
        return q

    @validate(VUser())
    def GET_listing(self, **env):
        return ListingController.GET_listing(self, **env)

class ToplinksController(ListingController):
    where = 'toplinks'
    title_text = _('top scoring links')

    def query(self):
        q = Link._query(Link.c.top_link == True,
                        sort = desc('_hot'),
                        *c.site.query_rules())
        return q

    @validate(VSrMask('srs'))
    def GET_listing(self, **env):
        return ListingController.GET_listing(self, **env)

class NewController(ListingController):
    where = 'new'
    title_text = _('newest submissions')

    @property
    def menus(self):
        return [NewMenu(default = self.sort)]

    def query(self):
        sort = NewMenu.operator(self.sort)

        if not sort: # rising
            names = get_rising(c.site)
            return names
        else:
            q = Link._query(sort = sort, read_cache = True,
                            *c.site.query_rules() )
            self.collect_stats = True
            return q
        
    @validate(VSrMask('srs'),
              sort = VMenu('controller', NewMenu))
    def GET_listing(self, sort, **env):
        self.sort = sort
        if self.sort == 'rising':
            self.builder_cls = IDBuilder
        return ListingController.GET_listing(self, **env)

class BrowseController(ListingController):
    where = 'browse'

    @property
    def menus(self):
        return [ControversyTimeMenu(default = self.time)]
    
    def query(self):
        q = Link._query(sort = SortMenu.operator(self.sort),
                        read_cache = True,
                        *c.site.query_rules())

        if g.REDDIT_MAIN:
            q._stats_collector = g.stats_collector

        t = TimeMenu.operator(self.time)
        if t: q._filter(t)

        return q

    # TODO: this is a hack with sort.
    @validate(VSrMask('srs'),
              sort = VOneOf('sort', ('top', 'controversial')),
              time = VMenu('where', ControversyTimeMenu))
    def GET_listing(self, sort, time, **env):
        self.sort = sort
        if sort == 'top':
            self.title_text = _('top scoring links')
        elif sort == 'controversial':
            self.title_text = _('most controversial links')
        self.time = time
        return ListingController.GET_listing(self, **env)


class RandomrisingController(ListingController):
    where = 'randomrising'
    builder_cls = IDBuilder
    title_text = _('you\'re really bored now, eh?')

    def query(self):
        links = get_rising(c.site)

        if not links:
            # just pull from the new page if the rising page isn't
            # populated for some reason
            q = Link._query(limit = 200,
                            data  = True,
                            sort  = desc('_date'))
            links = [ x._fullname for x in q ]
        
        random.shuffle(links)

        return links

class RecommendedController(ListingController):
    where = 'recommended'
    builder_cls = IDBuilder
    title_text = _('recommended for you')
    
    @property
    def menus(self):
        return [RecSortMenu(default = self.sort)]
    
    def query(self):
        return get_recommended(c.user._id, sort = self.sort)
        
    @validate(VUser(),
              sort = VMenu("controller", RecSortMenu))
    def GET_listing(self, sort, **env):
        self.sort = sort
        return ListingController.GET_listing(self, **env)

class MessageController(ListingController):
    show_sidebar = False
    render_cls = MessagePage

    def title(self):
        return _('messages') + ': ' + _(self.where)

    @staticmethod
    def builder_wrapper(thing):
        if isinstance(thing, Comment):
            p = thing.permalink
            f = thing._fullname
            thing.__class__ = Message
            w = Wrapped(thing)
            w.to_id = c.user._id
            w.subject = 'comment reply'
            w.was_comment = True
            w.permalink, w._fullname = p, f
            return w
        else:
            return ListingController.builder_wrapper(thing)

    def query(self):
        if self.where == 'inbox':
            q = Inbox._query(Inbox.c._thing1_id == c.user._id,
                             eager_load = True,
                             thing_data = True)
            self.prewrap_fn = lambda x: x._thing2

            #reset the inbox
            if c.have_messages:
                c.user.msgtime = False
                c.user._commit()

        elif self.where == 'sent':
            q = Message._query(Message.c.author_id == c.user._id)

        q._sort = desc('_date')
        return q

    def content(self):
        self.page = self.listing_obj
        return self.page

    @validate(VUser())
    def GET_listing(self, where, **env):
        self.where = where
        c.msg_location = where
        return ListingController.GET_listing(self, **env)

    def GET_compose(self):
        i = request.get
        if not c.user_is_loggedin: return self.abort404()
        content = MessageCompose(to = i.get('to'), subject = i.get('subject'),
                                 message = i.get('message'),
                                 success = i.get('success'))
        return MessagePage(content = content).render()

    

class RedditsController(ListingController):
    render_cls = SubredditsPage

    def title(self):
        return _('reddits')

    def query(self):
        if self.where == 'banned' and c.user_is_admin:
            reddits = Subreddit._query(Subreddit.c._spam == True,
                                       sort = desc('_date'))
        else:
            reddits = Subreddit._query()
            if self.where == 'new':
                reddits._sort = desc('_date')
            else:
                reddits._sort = desc('_downs')
            if c.content_langs != 'all':
                reddits._filter(Subreddit.c.lang == c.content_langs)
            if not c.over18:
                reddits._filter(Subreddit.c.over_18 == False)
                
        return reddits
    def GET_listing(self, where, **env):
        self.where = where
        return ListingController.GET_listing(self, **env)

class MyredditsController(ListingController):
    prewrap_fn = lambda self, x: x._thing1
    render_cls = MySubredditsPage

    @property
    def menus(self):
        buttons = (NavButton(plurals.subscriber,  'subscriber'),
                    NavButton(plurals.contributor, 'contributor'),
                    NavButton(plurals.moderator,   'moderator'))

        return [NavMenu(buttons, base_path = '/reddits/mine/', default = 'subscriber', type = "flatlist")]

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
    def GET_listing(self, where, **env):
        self.where = where
        return ListingController.GET_listing(self, **env)
