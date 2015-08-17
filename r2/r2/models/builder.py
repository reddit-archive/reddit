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
# All portions of the code written by reddit are Copyright (c) 2006-2015 reddit
# Inc. All Rights Reserved.
###############################################################################

from collections import defaultdict
from copy import deepcopy
from itertools import izip
import datetime
import heapq
from random import shuffle
import time

from pylons import request
from pylons import tmpl_context as c
from pylons import app_globals as g
from pylons.i18n import _

from r2.config import feature
from r2.config.extensions import API_TYPES, RSS_TYPES
from r2.lib.comment_tree import (
    conversation,
    link_comments_and_sort,
    moderator_messages,
    sr_conversation,
    subreddit_messages,
    tree_sort_fn,
    user_messages,
)
from r2.lib.wrapped import Wrapped
from r2.lib.db import operators, tdb_cassandra
from r2.lib.filters import _force_unicode
from r2.lib.utils import Storage, timesince, tup, to36
from r2.lib.utils.comment_tree_utils import get_num_children

from r2.models import (
    Account,
    Comment,
    CommentSavesByAccount,
    Link,
    LinkSavesByAccount,
    Message,
    MoreChildren,
    MoreMessages,
    MoreRecursion,
    Subreddit,
    Thing,
    wiki,
)
from r2.models.admintools import compute_votes, ip_span
from r2.models.flair import Flair
from r2.models.listing import Listing


EXTRA_FACTOR = 1.5
MAX_RECURSION = 10

class Builder(object):
    def __init__(self, wrap=Wrapped, prewrap_fn=None, keep_fn=None, stale=True,
                 spam_listing=False):
        self.wrap = wrap
        self.prewrap_fn = prewrap_fn
        self.keep_fn = keep_fn
        self.stale = stale
        self.spam_listing = spam_listing

    def keep_item(self, item):
        if self.keep_fn:
            return self.keep_fn(item)
        else:
            return item.keep_item(item)

    def wrap_items(self, items):
        from r2.lib.db import queries
        from r2.lib.template_helpers import add_attr

        user = c.user if c.user_is_loggedin else None
        aids = set(l.author_id for l in items if hasattr(l, 'author_id')
                   and l.author_id is not None)

        authors = Account._byID(aids, data=True, stale=self.stale)
        now = datetime.datetime.now(g.tz)
        cakes = {a._id for a in authors.itervalues()
                       if a.cake_expiration and a.cake_expiration >= now}
        friend_rels = user.friend_rels() if user and user.gold else {}

        subreddits = Subreddit.load_subreddits(items, stale=self.stale)
        can_ban_set = set()

        if user:
            for sr_id, sr in subreddits.iteritems():
                if sr.can_ban(user):
                    can_ban_set.add(sr_id)

        #get likes/dislikes
        try:
            likes = queries.get_likes(user, items)
        except tdb_cassandra.TRANSIENT_EXCEPTIONS as e:
            g.log.warning("Cassandra vote lookup failed: %r", e)
            likes = {}

        types = {}
        wrapped = []

        modlink = {}
        modlabel = {}
        for s in subreddits.values():
            modlink[s._id] = '/r/%s/about/moderators' % s.name
            modlabel[s._id] = (_('moderator of /r/%(reddit)s, '
                                 'speaking officially') % {'reddit': s.name})

        for item in items:
            w = self.wrap(item)
            wrapped.append(w)
            # add for caching (plus it should be bad form to use _
            # variables in templates)
            w.fullname = item._fullname
            types.setdefault(w.render_class, []).append(w)

            w.author = None
            w.friend = False

            # List of tuples (see add_attr() for details)
            w.attribs = []

            w.distinguished = None
            if hasattr(item, "distinguished"):
                if item.distinguished == 'yes':
                    w.distinguished = 'moderator'
                elif item.distinguished in ('admin', 'special',
                                            'gold', 'gold-auto'):
                    w.distinguished = item.distinguished

            try:
                w.author = authors.get(item.author_id)
                author_id = item.author_id

                # if display_author exists, then author_id is unknown to the
                # receiver, so don't display friend relationship details
                if hasattr(item, 'display_author') and item.display_author:
                    author_id = item.display_author
                if user and author_id in user.friends:
                    # deprecated old way:
                    w.friend = True

                    # new way:
                    label = None
                    if friend_rels:
                        rel = friend_rels[author_id]
                        note = getattr(rel, "note", None)
                        if note:
                            label = u"%s (%s)" % (_("friend"), 
                                                  _force_unicode(note))
                    add_attr(w.attribs, 'F', label)

            except AttributeError:
                pass

            if (w.distinguished == 'admin' and w.author):
                add_attr(w.attribs, 'A')

            if w.distinguished == 'moderator':
                add_attr(w.attribs, 'M', label=modlabel[item.sr_id],
                         link=modlink[item.sr_id])
            
            if w.distinguished == 'special':
                args = w.author.special_distinguish()
                args.pop('name')
                if not args.get('kind'):
                    args['kind'] = 'special'
                add_attr(w.attribs, **args)

            # if display_author exists, then author_id is unknown to the
            # receiver, so don't display the cake day
            if (not hasattr(item, 'display_author') and
                    w.author and w.author._id in cakes and not c.profilepage):
                add_attr(
                    w.attribs,
                    kind="cake",
                    label=(_("%(user)s just celebrated a reddit birthday!") %
                           {"user": w.author.name}),
                    link="/user/%s" % w.author.name,
                )

            if hasattr(item, "sr_id") and item.sr_id is not None:
                w.subreddit = subreddits[item.sr_id]

            w.likes = likes.get((user, item))

            # update vote tallies
            compute_votes(w, item)

            w.score = w.upvotes - w.downvotes

            if w.likes:
                base_score = w.score - 1
            elif w.likes is None:
                base_score = w.score
            else:
                base_score = w.score + 1

            # store the set of available scores based on the vote
            # for ease of i18n when there is a label
            w.voting_score = [(base_score + x - 1) for x in range(3)]

            w.deleted = item._deleted

            w.link_notes = []

            if c.user_is_admin:
                if item._deleted:
                    w.link_notes.append("deleted link")
                if getattr(item, "verdict", None):
                    if not item.verdict.endswith("-approved"):
                        w.link_notes.append(w.verdict)

            if c.user_is_admin and getattr(item, 'ip', None):
                w.ip_span = ip_span(item.ip)
            else:
                w.ip_span = ""

            # if the user can ban things on a given subreddit, or an
            # admin, then allow them to see that the item is spam, and
            # add the other spam-related display attributes
            w.show_reports = False
            w.show_spam    = False
            w.can_ban      = False
            w.use_big_modbuttons = self.spam_listing

            if (c.user_is_admin
                or (user
                    and hasattr(item,'sr_id')
                    and item.sr_id in can_ban_set)):
                if getattr(item, "promoted", None) is None:
                    w.can_ban = True

                ban_info = getattr(item, 'ban_info', {})
                w.unbanner = ban_info.get('unbanner')

                if item._spam:
                    w.show_spam = True
                    w.moderator_banned = ban_info.get('moderator_banned', False)
                    w.autobanned = ban_info.get('auto', False)
                    w.banner = ban_info.get('banner')
                    w.banned_at = ban_info.get("banned_at", None)
                    if ban_info.get('note', None) and w.banner:
                        w.banner += ' (%s)' % ban_info['note']
                    w.use_big_modbuttons = True
                    if getattr(w, "author", None) and w.author._spam:
                        w.show_spam = "author"

                    if c.user == w.author and c.user._spam:
                        w.show_spam = False
                        w._spam = False
                        w.use_big_modbuttons = False

                elif (getattr(item, 'reported', 0) > 0
                      and (not getattr(item, 'ignore_reports', False) or
                           c.user_is_admin)):
                    w.show_reports = True
                    w.use_big_modbuttons = True

                    # report_count isn't used in any template, but add it to
                    # the Wrapped so it's pulled into the render cache key in
                    # instances when reported will be used in the template
                    w.report_count = item.reported

            w.approval_checkmark = None
            if w.can_ban:
                verdict = getattr(w, "verdict", None)
                if verdict in ('admin-approved', 'mod-approved'):
                    approver = None
                    approval_time = None
                    baninfo = getattr(w, "ban_info", None)
                    if baninfo:
                        approver = baninfo.get("unbanner", None)
                        approval_time = baninfo.get("unbanned_at", None)

                    approver = approver or _("a moderator")

                    if approval_time:
                        text = _("approved by %(who)s %(when)s ago") % {
                                    "who": approver,
                                    "when": timesince(approval_time)}
                    else:
                        text = _("approved by %s") % approver
                    w.approval_checkmark = text

        # recache the user object: it may be None if user is not logged in,
        # whereas now we are happy to have the UnloggedUser object
        user = c.user
        for cls in types.keys():
            cls.add_props(user, types[cls])

        return wrapped

    def get_items(self):
        raise NotImplementedError

    def convert_items(self, items):
        """Convert a list of items to the desired output format"""
        if self.prewrap_fn:
            items = [self.prewrap_fn(i) for i in items]

        if self.wrap:
            items = self.wrap_items(items)
        else:
            # make a copy of items so the converted items can be mutated without
            # changing the original items
            items = items[:]
        return items

    def valid_after(self, after):
        """
        Return whether `after` could ever be shown to the user.

        Necessary because an attacker could use info about the presence
        and position of `after` within a listing to leak info about `after`s
        that the attacker could not normally access.
        """
        w = self.convert_items((after,))[0]
        return not self.must_skip(w)

    def item_iter(self, a):
        """Iterates over the items returned by get_items"""
        raise NotImplementedError

    def must_skip(self, item):
        """whether or not to skip any item regardless of whether the builder
        was contructed with skip=true"""
        user = c.user if c.user_is_loggedin else None

        if hasattr(item, "promoted") and item.promoted is not None:
            return False

        # can_view_slow only exists for Messages, but checking was_comment
        # is also necessary because items may also be comments that are being
        # viewed from the inbox page where their render class is overridden.
        # This check needs to be done before looking at whether they can view
        # the subreddit, or modmail to/from private subreddits that the user
        # doesn't have access to will be skipped.
        if hasattr(item, 'can_view_slow') and not item.was_comment:
            return not item.can_view_slow()

        if hasattr(item, 'subreddit') and not item.subreddit.can_view(user):
            return True

class QueryBuilder(Builder):
    def __init__(self, query, skip=False, num=None, sr_detail=None, count=0,
                 after=None, reverse=False, **kw):
        self.query = query
        self.skip = skip
        self.num = num
        self.sr_detail = sr_detail
        self.start_count = count or 0
        self.after = after
        self.reverse = reverse
        Builder.__init__(self, **kw)

    def __repr__(self):
        return "<%s(%r)>" % (self.__class__.__name__, self.query)

    def item_iter(self, a):
        """Iterates over the items returned by get_items"""
        for i in a[0]:
            yield i

    def init_query(self):
        q = self.query

        if self.reverse:
            q._reverse()

        q._data = True
        self.orig_rules = deepcopy(q._rules)
        if self.after:
            q._after(self.after)

    def fetch_more(self, last_item, num_have):
        done = False
        q = self.query
        if self.num:
            num_need = self.num - num_have
            if num_need <= 0:
                #will cause the loop below to break
                return True, None
            else:
                #q = self.query
                #check last_item if we have a num because we may need to iterate
                if last_item:
                    q._rules = deepcopy(self.orig_rules)
                    q._after(last_item)
                    last_item = None
                q._limit = max(int(num_need * EXTRA_FACTOR), self.num // 2, 1)
        else:
            done = True
        new_items = list(q)

        return done, new_items

    def get_items(self):
        self.init_query()

        num_have = 0
        done = False
        items = []
        count = self.start_count
        fetch_after = None
        loopcount = 0
        stopped_early = False

        while not done:
            done, fetched_items = self.fetch_more(fetch_after, num_have)

            #log loop
            loopcount += 1
            if loopcount == 20:
                done = True
                stopped_early = True

            #no results, we're done
            if not fetched_items:
                break

            #if fewer results than we wanted, we're done
            elif self.num and len(fetched_items) < self.num - num_have:
                done = True

            # Wrap the fetched items if necessary
            new_items = self.convert_items(fetched_items)

            #skip and count
            while new_items and (not self.num or num_have < self.num):
                i = new_items.pop(0)

                if not (self.must_skip(i) or
                        self.skip and not self.keep_item(i)):
                    items.append(i)
                    num_have += 1
                    count = count - 1 if self.reverse else count + 1
                    if self.wrap:
                        i.num = count

            fetch_after = fetched_items[-1]

        # Is there a next page or not?
        have_next = True
        if self.num and num_have < self.num and not stopped_early:
            have_next = False

        if getattr(self, 'sr_detail', False):
            for item in items:
                item.sr_detail = True

        # Make sure first_item and last_item refer to things in items
        # NOTE: could retrieve incorrect item if there were items with
        # duplicate _id
        first_item = None
        last_item = None
        if items:
            if self.start_count > 0:
                first_item = items[0]
            last_item = items[-1]

        if self.reverse:
            items.reverse()
            last_item, first_item = first_item, have_next and last_item
            before_count = count
            after_count = self.start_count - 1
        else:
            last_item = have_next and last_item
            before_count = self.start_count + 1
            after_count = count

        #listing is expecting (things, prev, next, bcount, acount)
        return (items,
                first_item,
                last_item,
                before_count,
                after_count)

class IDBuilder(QueryBuilder):
    def thing_lookup(self, names):
        return Thing._by_fullname(names, data=True, return_dict=False,
                                  stale=self.stale)

    def init_query(self):
        names = list(tup(self.query))

        after = self.after._fullname if self.after else None

        self.names = self._get_after(names,
                                     after,
                                     self.reverse)

    @staticmethod
    def _get_after(l, after, reverse):
        names = list(l)

        if reverse:
            names.reverse()

        if after:
            try:
                i = names.index(after)
            except ValueError:
                names = ()
            else:
                names = names[i + 1:]

        return names

    def fetch_more(self, last_item, num_have):
        done = False
        names = self.names
        if self.num:
            num_need = self.num - num_have
            if num_need <= 0:
                return True, None
            else:
                if last_item:
                    last_item = None
                slice_size = max(int(num_need * EXTRA_FACTOR), self.num // 2, 1)
        else:
            slice_size = len(names)
            done = True

        self.names, new_names = names[slice_size:], names[:slice_size]
        new_items = self.thing_lookup(new_names)
        return done, new_items


class ActionBuilder(IDBuilder):
    def init_query(self):
        self.actions = {}
        ids = []
        for id, date, action in self.query:
            ids.append(id)
            self.actions[id] = action
        self.query = ids

        super(ActionBuilder, self).init_query()

    def thing_lookup(self, names):
        items = super(ActionBuilder, self).thing_lookup(names)

        for item in items:
            if item._fullname in self.actions:
                item.action_type = self.actions[item._fullname]
        return items


class CampaignBuilder(IDBuilder):
    """Build on a list of PromoTuples."""
    @staticmethod
    def _get_after(promo_tuples, after, reverse):
        promo_tuples = list(promo_tuples)

        if not after:
            return promo_tuples

        if reverse:
            promo_tuples.reverse()

        fullname_to_index = {pt.link: i for i, pt in enumerate(promo_tuples)}
        try:
            i = fullname_to_index[after]
        except KeyError:
            promo_tuples = ()
        else:
            promo_tuples = promo_tuples[i + 1:]

        return promo_tuples

    def thing_lookup(self, tuples):
        links = Link._by_fullname([t.link for t in tuples], data=True,
                                  return_dict=True, stale=self.stale)

        return [Storage({'thing': links[t.link],
                         '_id': links[t.link]._id,
                         '_fullname': links[t.link]._fullname,
                         'weight': t.weight,
                         'campaign': t.campaign}) for t in tuples]

    def wrap_items(self, items):
        links = [i.thing for i in items]
        wrapped = IDBuilder.wrap_items(self, links)
        by_link = defaultdict(list)
        for w in wrapped:
            by_link[w._fullname].append(w)

        ret = []
        for i in items:
            w = by_link[i.thing._fullname].pop()
            w.campaign = i.campaign
            w.weight = i.weight
            ret.append(w)

        return ret

    def valid_after(self, after):
        # CampaignBuilder has special wrapping logic to operate on
        # PromoTuples and PromoCampaigns. `after` is just a Link, so bypass
        # the special wrapping logic and use the base class.
        if self.prewrap_fn:
            after = self.prewrap_fn(after)
        if self.wrap:
            after = Builder.wrap_items(self, (after,))[0]
        return not self.must_skip(after)


class ModActionBuilder(QueryBuilder):
    def wrap_items(self, items):
        wrapped = []
        by_render_class = defaultdict(list)

        for item in items:
            w = self.wrap(item)
            wrapped.append(w)
            w.fullname = item._fullname
            by_render_class[w.render_class].append(w)

        for render_class, _items in by_render_class.iteritems():
            render_class.add_props(c.user, _items)

        return wrapped


class SimpleBuilder(IDBuilder):
    def thing_lookup(self, names):
        return names

    def init_query(self):
        items = list(tup(self.query))

        if self.reverse:
            items.reverse()

        if self.after:
            for i, item in enumerate(items):
                if item._id == self.after:
                    self.names = items[i + 1:]
                    break
            else:
                self.names = ()
        else:
            self.names = items

    def get_items(self):
        items, prev_item, next_item, bcount, acount = IDBuilder.get_items(self)
        prev_item_id = prev_item._id if prev_item else None
        next_item_id = next_item._id if next_item else None
        return (items, prev_item_id, next_item_id, bcount, acount)


class SearchBuilder(IDBuilder):
    def __init__(self, query, skip_deleted_authors=True, **kw):
        self.skip_deleted_authors = skip_deleted_authors
        IDBuilder.__init__(self, query, **kw)

    def init_query(self):
        self.skip = True

        self.start_time = time.time()

        self.results = self.query.run()
        names = list(self.results.docs)
        self.total_num = self.results.hits
        self.subreddit_facets = self.results.subreddit_facets

        after = self.after._fullname if self.after else None

        self.names = self._get_after(names,
                                     after,
                                     self.reverse)

    def keep_item(self, item):
        # doesn't use the default keep_item because we want to keep
        # things that were voted on, even if they've chosen to hide
        # them in normal listings
        user = c.user if c.user_is_loggedin else None

        if item._spam or item._deleted:
            return False
        # If checking (wrapped) links, filter out banned subreddits
        elif hasattr(item, 'subreddit') and item.subreddit.spammy():
            return False
        elif (hasattr(item, 'subreddit') and
              not c.user_is_admin and
              not item.subreddit.is_exposed(user)):
            return False
        elif (self.skip_deleted_authors and
              getattr(item, "author", None) and item.author._deleted):
            return False
        elif isinstance(item.lookups[0], Subreddit) and not item.is_exposed(user):
            return False

        # show NSFW to API and RSS users unless obey_over18=true
        is_api_or_rss = (c.render_style in API_TYPES
                         or c.render_style in RSS_TYPES)
        if is_api_or_rss:
            include_over18 = not c.obey_over18 or c.over18
        elif feature.is_enabled('safe_search'):
            include_over18 = c.over18
        else:
            include_over18 = True

        is_nsfw = (item.over_18 or
            (hasattr(item, 'subreddit') and item.subreddit.over_18))
        if is_nsfw and not include_over18:
            return False

        return True


class WikiRevisionBuilder(QueryBuilder):
    show_extended = True

    def __init__(self, revisions, user=None, sr=None, page=None, **kw):
        self.user = user
        self.sr = sr
        self.page = page
        QueryBuilder.__init__(self, revisions, **kw)

    def wrap_items(self, items):
        from r2.lib.validator.wiki import this_may_revise
        types = {}
        wrapped = []
        extended = self.show_extended and c.is_wiki_mod
        extended = extended and this_may_revise(self.page)
        for item in items:
            w = self.wrap(item)
            w.show_extended = extended
            w.show_compare = self.show_extended
            types.setdefault(w.render_class, []).append(w)
            wrapped.append(w)

        user = c.user
        for cls in types.keys():
            cls.add_props(user, types[cls])

        return wrapped

    def must_skip(self, item):
        return item.admin_deleted and not c.user_is_admin

    def keep_item(self, item):
        from r2.lib.validator.wiki import may_view
        return ((not item.is_hidden) and
                may_view(self.sr, self.user, item.wikipage))

class WikiRecentRevisionBuilder(WikiRevisionBuilder):
    show_extended = False

    def must_skip(self, item):
        if WikiRevisionBuilder.must_skip(self, item):
            return True
        item_age = datetime.datetime.now(g.tz) - item.date
        return item_age.days >= wiki.WIKI_RECENT_DAYS


def add_child_listing(parent, *things):
    l = Listing(None, nextprev=None)
    l.things = list(things)
    parent.child = Wrapped(l)
    parent_name = parent._fullname if not parent.deleted else "deleted"
    parent.child.parent_name = parent_name


def make_wrapper(parent_wrapper = Wrapped, **params):
    def wrapper_fn(thing):
        w = parent_wrapper(thing)
        for k, v in params.iteritems():
            setattr(w, k, v)
        return w
    return wrapper_fn


class CommentBuilder(Builder):
    def __init__(self, link, sort, comment=None, children=None, context=None,
                 load_more=True, continue_this_thread=True,
                 max_depth=MAX_RECURSION, edits_visible=True, num=None,
                 show_deleted=False, **kw):
        self.link = link
        self.comment = comment
        self.children = children
        self.context = context or 0
        self.load_more = load_more
        self.max_depth = max_depth
        self.show_deleted = show_deleted or c.user_is_admin
        self.edits_visible = edits_visible
        self.num = num
        self.continue_this_thread = continue_this_thread
        self.sort = sort
        self.rev_sort = isinstance(sort, operators.desc)
        self.comments = None
        Builder.__init__(self, **kw)

    def update_candidates(self, candidates, sorter, to_add=None):
        for comment in (comment for comment in tup(to_add)
                                if comment in sorter):
            sort_val = -sorter[comment] if self.rev_sort else sorter[comment]
            heapq.heappush(candidates, (sort_val, comment))

    def get_items(self):
        if self.comments is None:
            self._get_comments()
        return self._make_wrapped_tree()

    def _get_comments(self):
        timer = g.stats.get_timer("CommentBuilder.get_items")
        timer.start()
        r = link_comments_and_sort(self.link, self.sort.col)
        cids, cid_tree, depth, parents, sorter = r
        timer.intermediate("load_storage")

        if self.comment and not self.comment._id in depth:
            g.log.error("Hack - self.comment (%d) not in depth. Defocusing..."
                        % self.comment._id)
            self.comment = None

        more_recursions = {}
        dont_collapse = []
        candidates = []
        offset_depth = 0

        if self.children:
            # requested specific child comments
            children = [cid for cid in self.children if cid in cids]
            self.update_candidates(candidates, sorter, children)
            dont_collapse.extend(comment for sort_val, comment in candidates)

        elif self.comment:
            # requested the tree from a specific comment

            # construct path back to top level from this comment, a maximum of
            # `context` levels
            comment = self.comment._id
            path = []
            while comment and len(path) <= self.context:
                path.append(comment)
                comment = parents[comment]

            dont_collapse.extend(path)

            # rewrite cid_tree so the parents lead only to the requested comment
            for comment in path:
                parent = parents[comment]
                cid_tree[parent] = [comment]

            # start building comment tree from earliest comment
            self.update_candidates(candidates, sorter, path[-1])

            # set offset_depth because we may not be at the top level and can
            # show deeper levels
            offset_depth = depth.get(path[-1], 0)

        else:
            # full tree requested, start with the top level comments
            top_level_comments = cid_tree.get(None, ())
            self.update_candidates(candidates, sorter, top_level_comments)

        timer.intermediate("pick_candidates")

        # choose which comments to show
        items = []
        while (self.num is None or len(items) < self.num) and candidates:
            sort_val, comment_id = heapq.heappop(candidates)
            if comment_id not in cids:
                continue

            comment_depth = depth[comment_id] - offset_depth
            if comment_depth < self.max_depth:
                items.append(comment_id)

                # add children
                if comment_id in cid_tree:
                    children = cid_tree[comment_id]
                    self.update_candidates(candidates, sorter, children)

            elif (self.continue_this_thread and
                  parents.get(comment_id) is not None):
                # the comment is too deep to add, so add a MoreRecursion for
                # its parent
                parent_id = parents[comment_id]
                if parent_id not in more_recursions:
                    w = Wrapped(MoreRecursion(self.link, depth=0,
                                              parent_id=parent_id))
                else:
                    w = more_recursions[parent_id]
                w.children.append(comment_id)
                more_recursions[parent_id] = w

        timer.intermediate("pick_comments")

        self.top_level_candidates = [comment for sort_val, comment in candidates
            if depth.get(comment, 0) == 0]
        self.comments = Comment._byID(
            items, data=True, return_dict=False, stale=self.stale)
        timer.intermediate("lookup_comments")

        self.timer = timer
        self.cid_tree = cid_tree
        self.depth = depth
        self.more_recursions = more_recursions
        self.offset_depth = offset_depth
        self.dont_collapse = dont_collapse

    def _make_wrapped_tree(self):
        timer = self.timer
        comments = self.comments
        cid_tree = self.cid_tree
        top_level_candidates = self.top_level_candidates
        depth = self.depth
        more_recursions = self.more_recursions
        offset_depth = self.offset_depth
        dont_collapse = self.dont_collapse
        timer.intermediate("waiting")

        if not comments and not top_level_candidates:
            timer.stop()
            return []

        # retrieve num_children for the visible comments
        needs_num_children = [c._id for c in comments] + top_level_candidates
        num_children = get_num_children(needs_num_children, cid_tree)
        timer.intermediate("calc_num_children")

        wrapped = self.wrap_items(comments)
        timer.intermediate("wrap_comments")
        wrapped_by_id = {comment._id: comment for comment in wrapped}

        if self.children:
            # rewrite the parent links to use anchor tags
            for comment_id in self.children:
                if comment_id in wrapped_by_id:
                    item = wrapped_by_id[comment_id]
                    if item.parent_id:
                        item.parent_permalink = '#' + to36(item.parent_id)

        final = []

        # We have some special collapsing rules for the Q&A sort type.
        # However, we want to show everything when we're building a specific
        # set of children (like from "load more" links) or when viewing a
        # comment permalink.
        qa_sort_hiding = ((self.sort.col == '_qa') and not self.children and
                          self.comment is None)
        if qa_sort_hiding:
            special_responder_ids = self.link.responder_ids
        else:
            special_responder_ids = ()

        max_relation_walks = g.max_comment_parent_walk
        for comment in wrapped:
            # skip deleted comments with no children
            if (comment.deleted and not cid_tree.has_key(comment._id)
                and not self.show_deleted):
                comment.hidden_completely = True
                continue

            comment.num_children = num_children[comment._id]
            comment.edits_visible = self.edits_visible

            parent = wrapped_by_id.get(comment.parent_id)
            if qa_sort_hiding:
                author_is_special = comment.author_id in special_responder_ids
            else:
                author_is_special = False

            # In the Q&A sort type, we want to collapse all comments other than
            # those that are:
            #
            # 1. Top-level comments,
            # 2. Responses from the OP(s),
            # 3. Responded to by the OP(s) (dealt with below),
            # 4. Within one level of an OP reply, or
            # 5. Otherwise normally prevented from collapse (eg distinguished
            #    comments).
            if (qa_sort_hiding and
                    depth[comment._id] != 0 and  # (1)
                    not author_is_special and  # (2)
                    not (parent and
                         parent.author_id in special_responder_ids) and # (4)
                    not comment.prevent_collapse):  # (5)
                comment.hidden = True

            if comment.collapsed:
                if comment._id in dont_collapse or author_is_special:
                    comment.collapsed = False
                    comment.hidden = False

            if parent:
                if author_is_special:
                    # Un-collapse parents as necessary.  It's a lot easier to
                    # do this here, upwards, than to check through all the
                    # children when we were iterating at the parent.
                    ancestor = parent
                    counter = 0
                    while (ancestor and
                            not getattr(ancestor, 'walked', False) and
                            counter < max_relation_walks):
                        ancestor.hidden = False
                        # In case we haven't processed this comment yet.
                        ancestor.prevent_collapse = True
                        # This allows us to short-circuit when the rest of the
                        # tree has already been uncollapsed.
                        ancestor.walked = True

                        ancestor = wrapped_by_id.get(ancestor.parent_id)
                        counter += 1

        # One more time through to actually add things to the final list.  We
        # couldn't do that the first time because in the Q&A sort we don't know
        # if a comment should be visible until after we've processed all its
        # children.
        for comment in wrapped:
            if getattr(comment, 'hidden_completely', False):
                # Don't add it to the tree, don't put it in "load more", don't
                # acknowledge its existence at all.
                continue

            if getattr(comment, 'hidden', False):
                # Remove it from the list of visible comments so it'll
                # automatically be a candidate for the "load more" links.
                del wrapped_by_id[comment._id]
                # And don't add it to the tree.
                continue

            # add the comment as a child of its parent or to the top level of
            # the tree if it has no parent
            parent = wrapped_by_id.get(comment.parent_id)
            if parent:
                if not hasattr(parent, 'child'):
                    add_child_listing(parent, comment)
                else:
                    parent.child.things.append(comment)
            else:
                final.append(comment)

        for parent_id, more_recursion in more_recursions.iteritems():
            if parent_id not in wrapped_by_id:
                continue

            parent = wrapped_by_id[parent_id]
            add_child_listing(parent, more_recursion)

        timer.intermediate("build_comments")

        if not self.load_more:
            timer.stop()
            return final

        # build MoreChildren for visible comments
        visible_comments = wrapped_by_id.keys()
        for visible_id in visible_comments:
            if visible_id in more_recursions:
                # don't add a MoreChildren if we already have a MoreRecursion
                continue

            children = cid_tree.get(visible_id, ())
            missing_children = [child for child in children
                                      if child not in visible_comments]
            if missing_children:
                visible_children = (child for child in children
                                          if child in visible_comments)
                visible_count = sum(1 + num_children[child]
                                    for child in visible_children)
                missing_count = num_children[visible_id] - visible_count
                missing_depth = depth.get(visible_id, 0) + 1 - offset_depth

                if missing_depth < self.max_depth:
                    mc = MoreChildren(self.link, self.sort, depth=missing_depth,
                                      parent_id=visible_id)
                    mc.children.extend(missing_children)
                    w = Wrapped(mc)
                    w.count = missing_count
                else:
                    mr = MoreRecursion(self.link, depth=missing_depth,
                                       parent_id=visible_id)
                    w = Wrapped(mr)

                # attach the MoreChildren
                parent = wrapped_by_id[visible_id]
                if hasattr(parent, 'child'):
                    parent.child.things.append(w)
                else:
                    add_child_listing(parent, w)

        # build MoreChildren for missing root level comments
        if top_level_candidates:
            mc = MoreChildren(self.link, self.sort, depth=0, parent_id=None)
            mc.children.extend(top_level_candidates)
            w = Wrapped(mc)
            w.count = sum(1 + num_children[comment]
                          for comment in top_level_candidates)
            final.append(w)

        if isinstance(self.sort, operators.shuffled):
            shuffle(final)

        timer.intermediate("build_morechildren")
        timer.stop()
        return final

    def item_iter(self, a):
        for i in a:
            yield i
            if hasattr(i, 'child'):
                for j in self.item_iter(i.child.things):
                    yield j


class MessageBuilder(Builder):
    def __init__(self, skip=True, num=None, parent=None, after=None,
                 reverse=False, threaded=False, **kw):
        self.skip = skip
        self.num = num
        self.parent = parent
        self.after = after
        self.reverse = reverse
        self.threaded = threaded
        Builder.__init__(self, **kw)

    def get_tree(self):
        raise NotImplementedError, "get_tree"

    def valid_after(self, after):
        w = self.convert_items((after,))[0]
        return self._viewable_message(w)

    def _viewable_message(self, m):
        if (c.user_is_admin or
                getattr(m, "author_id", 0) == c.user._id or
                getattr(m, "to_id", 0) == c.user._id):
            return True

        # m is wrapped at this time, so it should have an SR
        subreddit = getattr(m, "subreddit", None)
        if subreddit and subreddit.is_moderator_with_perms(c.user, 'mail'):
            return True

        return False

    def _apply_pagination(self, tree):
        if self.parent or self.num is None:
            return tree, None, None

        prev_item = None
        next_item = None

        if self.after:
            # truncate the tree to only show before/after requested message
            if self.reverse:
                next_item = self.after._id
                tree = [
                    (parent_id, child_ids) for parent_id, child_ids in tree
                    if tree_sort_fn((parent_id, child_ids)) >= next_item
                ]

                # special handling for after+reverse (before link): truncate
                # the tree so it has num messages before the requested one
                if len(tree) > self.num:
                    first_id, first_children = tree[-(self.num + 1)]
                    prev_item = tree_sort_fn((first_id, first_children))
                    tree = tree[-self.num:]
            else:
                prev_item = self.after._id
                tree = [
                    (parent_id, child_ids) for parent_id, child_ids in tree
                    if tree_sort_fn((parent_id, child_ids)) < prev_item
                ]

        if len(tree) > self.num:
            # truncate the tree to show only num conversations
            tree = tree[:self.num]
            last_id, last_children = tree[-1]
            next_item = tree_sort_fn((last_id, last_children))
        return tree, prev_item, next_item

    @classmethod
    def should_collapse(cls, message):
        # don't collapse this message if it has a new direct child
        if hasattr(message, "child"):
            has_new_child = any(child.new for child in message.child.things)
        else:
            has_new_child = False

        return (message.is_collapsed and
            not message.new and
            not has_new_child)

    def get_items(self):
        tree = self.get_tree()
        tree, prev_item, next_item = self._apply_pagination(tree)

        message_ids = []
        for parent_id, child_ids in tree:
            message_ids.append(parent_id)
            message_ids.extend(child_ids)

        if prev_item:
            message_ids.append(prev_item)

        messages = Message._byID(message_ids, data=True, return_dict=False)
        wrapped = {m._id: m for m in self.wrap_items(messages)}

        if prev_item:
            prev_item = wrapped[prev_item]
        if next_item:
            next_item = wrapped[next_item]

        final = []
        for parent_id, child_ids in tree:
            if parent_id not in wrapped:
                continue

            parent = wrapped[parent_id]

            if not self._viewable_message(parent):
                continue

            children = [
                wrapped[child_id] for child_id in child_ids
                if child_id in wrapped
            ]

            depth = {parent_id: 0}
            substitute_parents = {}

            if (children and self.skip and not self.threaded and
                    not self.parent and not parent.new and parent.is_collapsed):
                for i, child in enumerate(children):
                    if child.new or not child.is_collapsed:
                        break
                else:
                    i = -1
                # in flat view replace collapsed chain with MoreMessages
                add_child_listing(parent)
                parent = Wrapped(MoreMessages(parent, parent.child))
                children = children[i:]

            for child in sorted(children, key=lambda child: child._id):
                # iterate from the root outwards so we can check the depth
                if self.threaded:
                    try:
                        child_parent = wrapped[child.parent_id]
                    except KeyError:
                        # the stored comment tree was missing this message's
                        # parent, treat it as a top level reply
                        child_parent = parent
                else:
                    # for flat view all messages are decendants of the
                    # parent message
                    child_parent = parent
                parent_depth = depth[child_parent._id]
                child_depth = parent_depth + 1
                depth[child._id] = child_depth

                if child_depth == MAX_RECURSION:
                    # current message is at maximum depth level, all its
                    # children will be displayed as children of its parent
                    substitute_parents[child._id] = child_parent._id

                if child_depth > MAX_RECURSION:
                    child_parent_id = substitute_parents[child.parent_id]
                    substitute_parents[child._id] = child_parent_id
                    child_parent = wrapped[child_parent_id]

                if not hasattr(child_parent, "child"):
                    add_child_listing(child_parent)
                child.is_child = True
                child_parent.child.things.append(child)

            for child in children:
                # look over the children again to decide whether they can be
                # collapsed
                child.threaded = self.threaded
                child.collapsed = self.should_collapse(child)

            if self.threaded and children:
                most_recent_child_id = max(child._id for child in children)
                most_recent_child = wrapped[most_recent_child_id]
                most_recent_child.most_recent = True

            parent.is_parent = True
            parent.threaded = self.threaded
            parent.collapsed = self.should_collapse(parent)
            final.append(parent)

        return (final, prev_item, next_item, len(final), len(final))

    def item_iter(self, builder_items):
        items = builder_items[0]

        def _item_iter(_items):
            for i in _items:
                yield i
                if hasattr(i, "child"):
                    for j in _item_iter(i.child.things):
                        yield j

        return _item_iter(items)


class ModeratorMessageBuilder(MessageBuilder):
    def __init__(self, user, **kw):
        self.user = user
        MessageBuilder.__init__(self, **kw)

    def get_tree(self):
        if self.parent:
            sr = Subreddit._byID(self.parent.sr_id)
            return sr_conversation(sr, self.parent)
        sr_ids = Subreddit.reverse_moderator_ids(self.user)
        return moderator_messages(sr_ids)


class MultiredditMessageBuilder(MessageBuilder):
    def __init__(self, sr, **kw):
        self.sr = sr
        MessageBuilder.__init__(self, **kw)

    def get_tree(self):
        if self.parent:
            sr = Subreddit._byID(self.parent.sr_id)
            return sr_conversation(sr, self.parent)
        return moderator_messages(self.sr.sr_ids)


class TopCommentBuilder(CommentBuilder):
    """A comment builder to fetch only the top-level, non-spam,
       non-deleted comments"""
    def __init__(self, link, sort, num=None, wrap=Wrapped):
        CommentBuilder.__init__(self, link, sort, load_more=False,
            continue_this_thread=False, max_depth=1, wrap=wrap, num=num)

    def get_items(self):
        final = CommentBuilder.get_items(self)
        return [ cm for cm in final if not cm.deleted ]


class SrMessageBuilder(MessageBuilder):
    def __init__(self, sr, **kw):
        self.sr = sr
        MessageBuilder.__init__(self, **kw)

    def get_tree(self):
        if self.parent:
            return sr_conversation(self.sr, self.parent)
        return subreddit_messages(self.sr)


class UserMessageBuilder(MessageBuilder):
    def __init__(self, user, **kw):
        self.user = user
        MessageBuilder.__init__(self, **kw)

    def _viewable_message(self, message):
        is_author = message.author_id == c.user._id
        if not c.user_is_admin and not is_author and message._spam:
            return False

        return super(UserMessageBuilder, self)._viewable_message(message)

    def get_tree(self):
        if self.parent:
            return conversation(self.user, self.parent)
        return user_messages(self.user)

    def valid_after(self, after):
        # Messages that have been spammed are still valid afters
        w = self.convert_items((after,))[0]
        return MessageBuilder._viewable_message(self, w)


class UserListBuilder(QueryBuilder):
    def thing_lookup(self, rels):
        accounts = Account._byID([rel._thing2_id for rel in rels], data=True)
        for rel in rels:
            rel._thing2 = accounts.get(rel._thing2_id)
        return rels

    def must_skip(self, item):
        return item.user._deleted

    def valid_after(self, after):
        # Users that have been deleted are still valid afters
        return True

    def wrap_items(self, rels):
        return [self.wrap(rel) for rel in rels]

class SavedBuilder(IDBuilder):
    def wrap_items(self, items):
        from r2.lib.template_helpers import add_attr
        categories = LinkSavesByAccount.fast_query(c.user, items).items()
        categories += CommentSavesByAccount.fast_query(c.user, items).items()
        categories = {item[1]._id: category for item, category in categories if category}
        wrapped = QueryBuilder.wrap_items(self, items)
        for w in wrapped:
            category = categories.get(w._id, '')
            w.savedcategory = category
        return wrapped


class FlairListBuilder(UserListBuilder):
    def init_query(self):
        q = self.query

        if self.reverse:
            q._reverse()

        q._data = True
        self.orig_rules = deepcopy(q._rules)
        # FlairLists use Accounts for afters
        if self.after:
            if self.reverse:
                q._filter(Flair.c._thing2_id < self.after._id)
            else:
                q._filter(Flair.c._thing2_id > self.after._id)
