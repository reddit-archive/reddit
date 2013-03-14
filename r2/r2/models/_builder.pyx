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

from random import shuffle

from builder import Builder, MAX_RECURSION, empty_listing
from r2.lib.wrapped import Wrapped
from r2.lib.comment_tree import link_comments_and_sort, tree_sort_fn, MAX_ITERATIONS
from r2.models.link import *
from r2.lib.db import operators
from r2.lib import utils

class _CommentBuilder(Builder):
    def __init__(self, link, sort, comment = None, context = None,
                 load_more=True, continue_this_thread=True,
                 max_depth = MAX_RECURSION, **kw):
        Builder.__init__(self, **kw)
        self.link = link
        self.comment = comment
        self.context = context
        self.load_more = load_more
        self.max_depth = max_depth

        # This is almost always True, except in the toolbar comments panel,
        # where we never want to see "continue this thread" links
        self.continue_this_thread = continue_this_thread

        self.sort = sort
        self.rev_sort = True if isinstance(sort, operators.desc) else False

    def get_items(self, num):
        from r2.lib.lock import TimeoutExpired
        cdef list cid
        cdef dict cid_tree
        cdef dict depth
        cdef dict parents
        cdef dict sorter

        r = link_comments_and_sort(self.link, self.sort.col)
        cids, cid_tree, depth, num_children, parents, sorter = r

        cdef dict debug_dict = dict(
            link = self.link,
            comment = self.comment,
            context = self.context,
            load_more = self.load_more,
            max_depth = self.max_depth,
            continue_this_thread = self.continue_this_thread,
            sort = self.sort,
            rev_sort = self.rev_sort,
            lcs_rv = repr(r))

        if (not isinstance(self.comment, utils.iters)
            and self.comment and not self.comment._id in depth):
            debug_dict["defocus_hack"] = "yes"
            g.log.error("Hack - self.comment (%d) not in depth. Defocusing..."
                        % self.comment._id)
            self.comment = None

        cdef list items = []
        cdef dict extra = {}
        cdef list dont_collapse = []
        cdef list ignored_parent_ids = []

        cdef int start_depth = 0

        cdef list candidates = []
        cdef int offset_depth = 0

        # more comments links:
        if isinstance(self.comment, utils.iters):
            debug_dict["was_instance"] = "yes"
            for cm in self.comment:
                # deleted comments will be removed from the cids list
                if cm._id in cids:
                    dont_collapse.append(cm._id)
                    candidates.append(cm._id)
            # if nothing but deleted comments, the candidate list might be empty
            if candidates:
                pid = parents[candidates[0]]
                if pid is not None:
                    ignored_parent_ids.append(pid)
                    start_depth = depth[pid]

        # permalinks:
        elif self.comment:
            debug_dict["was_permalink"] = "yes"
            # we are going to mess around with the cid_tree's contents
            # so better copy it
            cid_tree = cid_tree.copy()
            top = self.comment._id
            dont_collapse.append(top)
            #add parents for context
            pid = parents[top]
            while self.context > 0 and pid is not None:
                self.context -= 1
                pid = parents[top]
                cid_tree[pid] = [top]
                num_children[pid] = num_children[top] + 1
                dont_collapse.append(pid)
                # top will be appended to candidates, so stop updating
                # it if hit the top of the thread
                if pid is not None:
                    top = pid
            candidates.append(top)
            # the reference depth is that of the focal element
            if top is not None:
                offset_depth = depth[top]
        #else start with the root comments
        else:
            debug_dict["was_root"] = "yes"
            candidates.extend(cid_tree.get(None, ()))

        #find the comments
        cdef int num_have = 0
        if candidates:
            candidates = [x for x in candidates if sorter.get(x) is not None]
            # complain if we removed a candidate and now have nothing
            # to return to the user
            if not candidates:
                g.log.error("_builder.pyx: empty candidate list: %r" %
                            request.fullpath)
                return []
        candidates.sort(key = sorter.get, reverse = self.rev_sort)

        debug_dict["candidates_Before"] = repr(candidates)
        while num_have < num and candidates:
            to_add = candidates.pop(0)
            if to_add not in cids:
                continue
            if (depth[to_add] - offset_depth) < self.max_depth + start_depth:
                #add children
                if cid_tree.has_key(to_add):
                    candidates.extend([x for x in cid_tree[to_add]
                                       if sorter.get(x) is not None])
                    candidates.sort(key = sorter.get, reverse = self.rev_sort)
                items.append(to_add)
                num_have += 1
            elif self.continue_this_thread:
                #add the recursion limit
                p_id = parents[to_add]
                if p_id is None:
                    fmt = ("tree problem: Wanted to add 'continue this " +
                           "thread' for %s, which has depth %d, but we " +
                           "don't know the parent")
                    g.log.info(fmt % (to_add, depth[to_add]))
                else:
                    w = Wrapped(MoreRecursion(self.link, 0, p_id))
                    w.children.append(to_add)
                    extra[p_id] = w
        debug_dict["candidates_after"] = repr(candidates)

        # items is a list of things we actually care about so load them
        items = Comment._byID(items, data = True, return_dict = False, stale=self.stale)
        cdef list wrapped = self.wrap_items(items)


        # break here
        # -----
        cids = {}
        for cm in wrapped:
            cids[cm._id] = cm

        debug_dict["cids"] = [utils.to36(i) for i in sorted(cids.keys())]

        cdef list final = []
        #make tree

        for cm in wrapped:
            # don't show spam with no children
            if (cm.deleted and not cid_tree.has_key(cm._id)
                and not c.user_is_admin):
                continue
            cm.num_children = num_children[cm._id]
            if cm.collapsed and cm._id in dont_collapse:
                cm.collapsed = False
            parent = cids.get(cm.parent_id)
            if parent:
                if not hasattr(parent, 'child'):
                    parent.child = empty_listing()
                parent.child.parent_name = parent._fullname
                parent.child.things.append(cm)
            else:
                final.append(cm)

        debug_dict["final"] = [cm._id36 for cm in final]
        debug_dict["depth"] = depth
        debug_dict["extra"] = extra

        for p_id, morelink in extra.iteritems():
            try:
                parent = cids[p_id]
            except KeyError:
                if p_id in ignored_parent_ids:
                    raise KeyError("%r not in cids because it was ignored" % p_id)
                else:
                    if g.memcache.get("debug-comment-tree"):
                        g.memcache.delete("debug-comment-tree")
                        for k in sorted(debug_dict.keys()):
                            g.log.info("tree debug: %s = %r" % (k,debug_dict[k]))
                        g.log.info("tree debug: p_id = %r" % p_id)
                    raise KeyError("%r not in cids but it wasn't ignored" % p_id)

            parent.child = empty_listing(morelink)
            parent.child.parent_name = parent._fullname

        if not self.load_more:
            return final

        #put the remaining comments into the tree (the show more comments link)
        cdef dict more_comments = {}
        cdef int iteration_count = 0
        cdef int parentfinder_iteration_count
        while candidates:
            if iteration_count > MAX_ITERATIONS:
                raise Exception("bad comment tree for link %s" %
                                self.link._id36)

            to_add = candidates.pop(0)
            direct_child = True
            #ignore top-level comments for now
            p_id = parents[to_add]
            #find the parent actually being displayed
            #direct_child is whether the comment is 'top-level'
            parentfinder_iteration_count = 0
            while p_id and not cids.has_key(p_id):
                if parentfinder_iteration_count > MAX_ITERATIONS:
                    raise Exception("bad comment tree in link %s" %
                                    self.link._id36)
                p_id = parents[p_id]
                direct_child = False
                parentfinder_iteration_count += 1

            mc2 = more_comments.get(p_id)
            if not mc2:
                mc2 = MoreChildren(self.link, depth.get(to_add,0) - offset_depth,
                                   parent_id = p_id)
                more_comments[p_id] = mc2
                w_mc2 = Wrapped(mc2)
                if p_id is None:
                    final.append(w_mc2)
                else:
                    parent = cids[p_id]
                    if hasattr(parent, 'child'):
                        parent.child.things.append(w_mc2)
                    else:
                        parent.child = empty_listing(w_mc2)
                        parent.child.parent_name = parent._fullname

            #add more children
            if cid_tree.has_key(to_add):
                candidates.extend(cid_tree[to_add])

            if direct_child:
                mc2.children.append(to_add)

            mc2.count += 1
            iteration_count += 1

        if isinstance(self.sort, operators.shuffled):
            shuffle(final)

        return final

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

