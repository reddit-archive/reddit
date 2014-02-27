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

from collections import defaultdict
from copy import deepcopy
import datetime
import heapq
from random import shuffle
import time

from pylons import c, g, request
from pylons.i18n import _

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
from r2.lib.utils import Storage, timesince, tup
from r2.lib.utils.comment_tree_utils import get_num_children

from r2.models import (
    Account,
    Comment,
    Link,
    Message,
    MoreChildren,
    MoreMessages,
    MoreRecursion,
    Subreddit,
    Thing,
    wiki,
)
from r2.models.admintools import compute_votes, ip_span
from r2.models.listing import Listing


EXTRA_FACTOR = 1.5
MAX_RECURSION = 10

class Builder(object):
    def __init__(self, wrap=Wrapped, keep_fn=None, stale=True,
                 spam_listing=False):
        self.stale = stale
        self.wrap = wrap
        self.keep_fn = keep_fn
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
        can_flair_set = set()
        can_own_flair_set = set()
        if user:
            for sr_id, sr in subreddits.iteritems():
                if sr.can_ban(user):
                    can_ban_set.add(sr_id)
                if sr.is_moderator_with_perms(user, 'flair'):
                    can_flair_set.add(sr_id)
                if sr.link_flair_self_assign_enabled:
                    can_own_flair_set.add(sr_id)

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
                if user and item.author_id in user.friends:
                    # deprecated old way:
                    w.friend = True

                    # new way:
                    label = None
                    if friend_rels:
                        rel = friend_rels[item.author_id]
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

            if w.author and w.author._id in cakes and not c.profilepage:
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
            w.can_flair    = False
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

            if (c.user_is_admin
                or (user and hasattr(item, 'sr_id')
                    and (item.sr_id in can_flair_set
                         or (w.author and w.author._id == user._id
                             and item.sr_id in can_own_flair_set)))):
                w.can_flair = True

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
    def __init__(self, query, wrap=Wrapped, keep_fn=None, skip=False,
                 spam_listing=False, **kw):
        Builder.__init__(self, wrap=wrap, keep_fn=keep_fn,
                         spam_listing=spam_listing)
        self.query = query
        self.skip = skip
        self.num = kw.get('num')
        self.start_count = kw.get('count', 0) or 0
        self.after = kw.get('after')
        self.reverse = kw.get('reverse')
        self.prewrap_fn = getattr(query, 'prewrap_fn', None)

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
                q._limit = max(int(num_need * EXTRA_FACTOR), 1)
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
        first_item = None
        last_item = None
        have_next = True
        loopcount = 0

        while not done:
            done, new_items = self.fetch_more(last_item, num_have)

            #log loop
            loopcount += 1
            if loopcount == 20:
                done = True

            #no results, we're done
            if not new_items:
                break

            #if fewer results than we wanted, we're done
            elif self.num and len(new_items) < self.num - num_have:
                done = True
                have_next = False

            if not first_item and self.start_count > 0:
                first_item = new_items[0]

            if self.prewrap_fn:
                orig_items = {}
                new_items2 = []
                for i in new_items:
                    new = self.prewrap_fn(i)
                    orig_items[new._id] = i
                    new_items2.append(new)
                new_items = new_items2
            else:
                orig_items = dict((i._id, i) for i in new_items)

            if self.wrap:
                new_items = self.wrap_items(new_items)

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
                last_item = i
        
            # get original version of last item
            if last_item and (self.prewrap_fn or self.wrap):
                last_item = orig_items[last_item._id]

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
                slice_size = max(int(num_need * EXTRA_FACTOR), 1)
        else:
            slice_size = len(names)
            done = True

        self.names, new_names = names[slice_size:], names[:slice_size]
        new_items = self.thing_lookup(new_names)
        return done, new_items


class CampaignBuilder(IDBuilder):
    """Build on a list of PromoTuples."""

    def __init__(self, query, wrap=Wrapped, keep_fn=None, prewrap_fn=None,
                 skip=False, num=None):
        Builder.__init__(self, wrap=wrap, keep_fn=keep_fn)
        self.query = query
        self.skip = skip
        self.num = num
        self.start_count = 0
        self.after = None
        self.reverse = False
        self.prewrap_fn = prewrap_fn

    def thing_lookup(self, tuples):
        links = Link._by_fullname([t.link for t in tuples], data=True,
                                  return_dict=True, stale=self.stale)

        return [Storage({'thing': links[t.link],
                         '_id': links[t.link]._id,
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
    def __init__(self, query, wrap=Wrapped, keep_fn=None, skip=False,
                 skip_deleted_authors=True, **kw):
        IDBuilder.__init__(self, query, wrap, keep_fn, skip, **kw)
        self.skip_deleted_authors = skip_deleted_authors

    def init_query(self):
        self.skip = True

        self.start_time = time.time()

        self.results = self.query.run()
        names = list(self.results.docs)
        self.total_num = self.results.hits

        after = self.after._fullname if self.after else None

        self.names = self._get_after(names,
                                     after,
                                     self.reverse)

    def keep_item(self, item):
        # doesn't use the default keep_item because we want to keep
        # things that were voted on, even if they've chosen to hide
        # them in normal listings
        if item._spam or item._deleted:
            return False
        # If checking (wrapped) links, filter out banned subreddits
        elif hasattr(item, 'subreddit') and item.subreddit.spammy():
            return False
        elif (self.skip_deleted_authors and
              getattr(item, "author", None) and item.author._deleted):
            return False
        else:
            return True

class WikiRevisionBuilder(QueryBuilder):
    show_extended = True
    
    def __init__(self, *k, **kw):
        self.user = kw.pop('user', None)
        self.sr = kw.pop('sr', None)
        QueryBuilder.__init__(self, *k, **kw)
    
    def wrap_items(self, items):
        types = {}
        wrapped = []
        for item in items:
            w = self.wrap(item)
            w.show_extended = self.show_extended
            types.setdefault(w.render_class, []).append(w)
            wrapped.append(w)
        
        user = c.user
        for cls in types.keys():
            cls.add_props(user, types[cls])

        return wrapped
    
    def keep_item(self, item):
        from r2.lib.validator.wiki import may_view
        return ((not item.is_hidden) and
                may_view(self.sr, self.user, item.wikipage))

class WikiRecentRevisionBuilder(WikiRevisionBuilder):
    show_extended = False

    def must_skip(self, item):
        item_age = datetime.datetime.now(g.tz) - item.date
        return item_age.days >= wiki.WIKI_RECENT_DAYS


def empty_listing(*things):
    parent_name = None
    for t in things:
        try:
            parent_name = t.parent_name
            break
        except AttributeError:
            continue
    l = Listing(None, None, parent_name = parent_name)
    l.things = list(things)
    return Wrapped(l)

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
                 max_depth=MAX_RECURSION, num=None, **kw):
        Builder.__init__(self, **kw)
        self.link = link
        self.comment = comment
        self.children = children
        self.context = context or 0
        self.load_more = load_more
        self.max_depth = max_depth
        self.num = num
        self.continue_this_thread = continue_this_thread
        self.sort = sort
        self.rev_sort = isinstance(sort, operators.desc)

    def update_candidates(self, candidates, sorter, to_add=None):
        for comment in (comment for comment in tup(to_add)
                                if comment in sorter):
            sort_val = -sorter[comment] if self.rev_sort else sorter[comment]
            heapq.heappush(candidates, (sort_val, comment))

    def get_items(self):
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
            children = [child._id for child in self.children
                                  if child._id in cids]
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

        if not candidates:
            timer.stop()
            return []

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

        # retrieve num_children for the visible comments
        top_level_candidates = [comment for sort_val, comment in candidates
                                        if depth.get(comment, 0) == 0]
        needs_num_children = items + top_level_candidates
        num_children = get_num_children(needs_num_children, cid_tree)
        timer.intermediate("calc_num_children")

        comments = Comment._byID(items, data=True, return_dict=False,
                                 stale=self.stale)
        timer.intermediate("lookup_comments")
        wrapped = self.wrap_items(comments)
        timer.intermediate("wrap_comments")
        wrapped_by_id = {comment._id: comment for comment in wrapped}
        final = []

        for comment in wrapped:
            # skip deleted comments with no children
            if (comment.deleted and not cid_tree.has_key(comment._id)
                and not c.user_is_admin):
                continue

            comment.num_children = num_children[comment._id]

            if comment.collapsed and comment._id in dont_collapse:
                comment.collapsed = False

            # add the comment as a child of its parent or to the top level of
            # the tree if it has no parent
            parent = wrapped_by_id.get(comment.parent_id)
            if parent:
                if not hasattr(parent, 'child'):
                    parent.child = empty_listing()
                if not parent.deleted:
                    parent.child.parent_name = parent._fullname
                parent.child.things.append(comment)
            else:
                final.append(comment)

        for parent_id, more_recursion in more_recursions.iteritems():
            if parent_id not in wrapped_by_id:
                continue

            parent = wrapped_by_id[parent_id]
            parent.child = empty_listing(more_recursion)
            if not parent.deleted:
                parent.child.parent_name = parent._fullname

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
                mc = MoreChildren(self.link, depth=missing_depth,
                                  parent_id=visible_id)
                mc.children.extend(missing_children)
                w = Wrapped(mc)
                w.count = missing_count

                # attach the MoreChildren
                parent = wrapped_by_id[visible_id]
                if hasattr(parent, 'child'):
                    parent.child.things.append(w)
                else:
                    parent.child = empty_listing(w)
                    if not parent.deleted:
                        parent.child.parent_name = parent._fullname

        # build MoreChildren for missing root level comments
        if top_level_candidates:
            mc = MoreChildren(self.link, depth=0, parent_id=None)
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
    def __init__(self, parent = None, focal = None,
                 skip = True, **kw):

        self.num = kw.pop('num', None)
        self.focal = focal
        self.parent = parent
        self.skip = skip

        self.after = kw.pop('after', None)
        self.reverse = kw.pop('reverse', None)

        Builder.__init__(self, **kw)

    def get_tree(self):
        raise NotImplementedError, "get_tree"

    def _tree_filter_reverse(self, x):
        return tree_sort_fn(x) >= self.after._id

    def _tree_filter(self, x):
        return tree_sort_fn(x) < self.after._id

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

    def get_items(self):
        tree = self.get_tree()

        prev_item = next_item = None
        if not self.parent:
            if self.num is not None:
                if self.after:
                    if self.reverse:
                        tree = filter(
                            self._tree_filter_reverse,
                            tree)
                        next_item = self.after._id
                        if len(tree) > self.num:
                            first = tree[-(self.num+1)]
                            prev_item = first[1][-1] if first[1] else first[0]
                            tree = tree[-self.num:]
                    else:
                        prev_item = self.after._id
                        tree = filter(
                            self._tree_filter,
                            tree)
                if len(tree) > self.num:
                    tree = tree[:self.num]
                    last = tree[-1]
                    next_item = last[1][-1] if last[1] else last[0]

        # generate the set of ids to look up and look them up
        message_ids = []
        for root, thread in tree:
            message_ids.append(root)
            message_ids.extend(thread)
        if prev_item:
            message_ids.append(prev_item)

        messages = Message._byID(message_ids, data = True, return_dict = False)
        wrapped = {}
        for m in self.wrap_items(messages):
            if not self._viewable_message(m):
                g.log.warning("%r is not viewable by %s; path is %s" %
                                 (m, c.user.name, request.fullpath))
                continue
            wrapped[m._id] = m

        if prev_item:
            prev_item = wrapped[prev_item]
        if next_item:
            next_item = wrapped[next_item]

        final = []
        for parent, children in tree:
            if parent not in wrapped:
                continue
            parent = wrapped[parent]
            if children:
                # if no parent is specified, check if any of the messages are
                # uncollapsed, and truncate the thread
                children = [wrapped[child] for child in children
                                           if child in wrapped]
                parent.child = empty_listing()
                # if the parent is new, uncollapsed, or focal we don't
                # want it to become a moremessages wrapper.
                if (self.skip and 
                    not self.parent and not parent.new and parent.is_collapsed 
                    and not (self.focal and self.focal._id == parent._id)):
                    for i, child in enumerate(children):
                        if (child.new or not child.is_collapsed or
                            (self.focal and self.focal._id == child._id)):
                            break
                    else:
                        i = -1
                    parent = Wrapped(MoreMessages(parent, empty_listing()))
                    children = children[i:]

                parent.child.parent_name = parent._fullname
                parent.child.things = []

                for child in children:
                    child.is_child = True
                    if self.focal and child._id == self.focal._id:
                        # focal message is never collapsed
                        child.collapsed = False
                        child.focal = True
                    else:
                        child.collapsed = child.is_collapsed

                    parent.child.things.append(child)
            parent.is_parent = True
            # the parent might be the focal message on a permalink page
            if self.focal and parent._id == self.focal._id:
                parent.collapsed = False
                parent.focal = True
            else:
                parent.collapsed = parent.is_collapsed
            final.append(parent)

        return (final, prev_item, next_item, len(final), len(final))

    def item_iter(self, a):
        for i in a[0]:
            yield i
            if hasattr(i, 'child'):
                for j in i.child.things:
                    yield j


class ModeratorMessageBuilder(MessageBuilder):
    def __init__(self, user, **kw):
        self.user = user
        MessageBuilder.__init__(self, **kw)

    def get_tree(self):
        if self.parent:
            return conversation(self.user, self.parent)
        sr_ids = Subreddit.reverse_moderator_ids(self.user)
        return moderator_messages(sr_ids)

class MultiredditMessageBuilder(MessageBuilder):
    def __init__(self, user, **kw):
        self.user = user
        MessageBuilder.__init__(self, **kw)

    def get_tree(self):
        if self.parent:
            return conversation(self.user, self.parent)
        return moderator_messages(c.site.sr_ids)

class TopCommentBuilder(CommentBuilder):
    """A comment builder to fetch only the top-level, non-spam,
       non-deleted comments"""
    def __init__(self, link, sort, num=None, wrap=Wrapped):
        CommentBuilder.__init__(self, link, sort,
                                load_more = False,
                                continue_this_thread = False,
                                max_depth=1, wrap=wrap, num=num)

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

    def get_tree(self):
        if self.parent:
            return conversation(self.user, self.parent)
        return user_messages(self.user)

class UserListBuilder(QueryBuilder):
    def thing_lookup(self, rels):
        accounts = Account._byID([rel._thing2_id for rel in rels], data=True)
        for rel in rels:
            rel._thing2 = accounts.get(rel._thing2_id)
        return rels

    def must_skip(self, item):
        return item.user._deleted

    def wrap_items(self, rels):
        return [self.wrap(rel) for rel in rels]
