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

import heapq
from random import shuffle

from builder import Builder, MAX_RECURSION, empty_listing
from r2.lib.wrapped import Wrapped
from r2.lib.comment_tree import link_comments_and_sort, tree_sort_fn
from r2.models.link import *
from r2.lib.db import operators
from r2.lib import utils

class _CommentBuilder(Builder):
    def __init__(self, link, sort, comment=None, children=None, context=None,
                 load_more=True, continue_this_thread=True,
                 max_depth = MAX_RECURSION, **kw):
        Builder.__init__(self, **kw)
        self.link = link
        self.comment = comment
        self.children = children
        self.context = context or 0
        self.load_more = load_more
        self.max_depth = max_depth

        # This is almost always True, except in the toolbar comments panel,
        # where we never want to see "continue this thread" links
        self.continue_this_thread = continue_this_thread

        self.sort = sort
        self.rev_sort = isinstance(sort, operators.desc)

    def update_candidates(self, candidates, sorter, to_add=None):
        for comment in (comment for comment in utils.tup(to_add)
                                if comment in sorter):
            sort_val = -sorter[comment] if self.rev_sort else sorter[comment]
            heapq.heappush(candidates, (sort_val, comment))

    def get_items(self, num):
        cdef list cid
        cdef dict cid_tree
        cdef dict depth
        cdef dict parents
        cdef dict sorter

        timer = g.stats.get_timer("CommentBuilder.get_items")
        timer.start()
        r = link_comments_and_sort(self.link, self.sort.col)
        cids, cid_tree, depth, parents, sorter = r
        timer.intermediate("load_storage")

        if self.comment and not self.comment._id in depth:
            g.log.error("Hack - self.comment (%d) not in depth. Defocusing..."
                        % self.comment._id)
            self.comment = None

        cdef dict more_recursions = {}
        cdef list dont_collapse = []
        cdef list candidates = []
        cdef int offset_depth = 0

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
        cdef list items = []
        while len(items) < num and candidates:
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
        cdef list comments = Comment._byID(items, data=True, return_dict=False,
                                           stale=self.stale)
        cdef list wrapped = self.wrap_items(comments)
        cdef dict wrapped_by_id = {comment._id: comment for comment in wrapped}
        cdef list final = []

        # retrieve num_children for the wrapped comments
        visible_comments = wrapped_by_id.keys()
        top_level_candidates = [comment for sort_val, comment in candidates
                                        if depth.get(comment, 0) == 0]
        needs_num_children = visible_comments + top_level_candidates
        cdef dict num_children = get_num_children(needs_num_children, cid_tree)

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

        timer.stop("build_morechildren")
        return final


cdef dict get_num_children(list comments, dict tree):
    """Count the number of children for each comment."""

    cdef dict num_children = {}
    cdef list stack = []
    cdef list children = []
    cdef list missing = []
    cdef long current
    cdef long child

    for comment in sorted(comments):
        stack.append(comment)

    while stack:
        current = stack[-1]

        if current in num_children:
            stack.pop()
            continue

        children = tree.get(current, [])

        for child in children:
            if child not in num_children and not tree.get(child, None):
                num_children[child] = 0

        missing = [child for child in children if not child in num_children]

        if not missing:
            num_children[current] = 0
            stack.pop()
            for child in children:
                num_children[current] += 1 + num_children[child]
        else:
            stack.extend(missing)

    return num_children


class _MessageBuilder(Builder):
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
        if (c.user_is_admin
            or getattr(m, "author_id", 0) == c.user._id
            or getattr(m, "to_id", 0)     == c.user._id):
                return True

        # m is wrapped at this time, so it should have an SR
        subreddit = getattr(m, "subreddit", None)
        if subreddit and subreddit.is_moderator_with_perms(c.user, 'mail'):
            return True

        return False


    def get_items(self):
        tree = self.get_tree()

        prev = next = None
        if not self.parent:
            if self.num is not None:
                if self.after:
                    if self.reverse:
                        tree = filter(
                            self._tree_filter_reverse,
                            tree)
                        next = self.after._id
                        if len(tree) > self.num:
                            first = tree[-(self.num+1)]
                            prev = first[1][-1] if first[1] else first[0]
                            tree = tree[-self.num:]
                    else:
                        prev = self.after._id
                        tree = filter(
                            self._tree_filter,
                            tree)
                if len(tree) > self.num:
                    tree = tree[:self.num]
                    last = tree[-1]
                    next = last[1][-1] if last[1] else last[0]

        # generate the set of ids to look up and look them up
        message_ids = []
        for root, thread in tree:
            message_ids.append(root)
            message_ids.extend(thread)
        if prev:
            message_ids.append(prev)

        messages = Message._byID(message_ids, data = True, return_dict = False)
        wrapped = {}
        for m in self.wrap_items(messages):
            if not self._viewable_message(m):
                g.log.warning("%r is not viewable by %s; path is %s" %
                                 (m, c.user.name, request.fullpath))
                continue
            wrapped[m._id] = m

        if prev:
            prev = wrapped[prev]
        if next:
            next = wrapped[next]

        final = []
        for parent, children in tree:
            if parent not in wrapped:
                continue
            parent = wrapped[parent]
            if children:
                # if no parent is specified, check if any of the messages are
                # uncollapsed, and truncate the thread
                children = [wrapped[child] for child in children if child in wrapped]
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

        return (final, prev, next, len(final), len(final))

