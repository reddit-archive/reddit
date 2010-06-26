from builder import Builder, MAX_RECURSION, empty_listing
from r2.lib.wrapped import Wrapped
from r2.lib.comment_tree import link_comments, link_comments_and_sort, tree_sort_fn
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
        self.continue_this_thread = continue_this_thread

        self.sort = sort
        self.rev_sort = True if isinstance(sort, operators.desc) else False

    def get_items(self, num):
        from r2.lib.lock import TimeoutExpired
        cdef list cid
        cdef dict cid_tree
        cdef dict depth
        cdef dict num_children
        cdef dict parents
        cdef dict sorter

        r = link_comments_and_sort(self.link._id, self.sort.col)
        cids, cid_tree, depth, num_children, parents, sorter = r

        if (not isinstance(self.comment, utils.iters)
            and self.comment and not self.comment._id in depth):
            g.log.error("Error - self.comment (%d) not in depth. Forcing update..."
                        % self.comment._id)

            try:
                r = link_comments(self.link._id, _update=True)
                cids, cid_tree, depth, num_children = r
            except TimeoutExpired:
                g.log.error("Error in _builder.pyx: timeout from tree reload (%r)" % self.link)
                raise

            if not self.comment._id in depth:
                g.log.error("Update didn't help. This is gonna end in tears.")

        cdef list items = []
        cdef dict extra = {}
        cdef list dont_collapse = []
        cdef list ignored_parent_ids = []

        cdef int start_depth = 0

        cdef list candidates = []
        cdef int offset_depth = 0

        # more comments links:
        if isinstance(self.comment, utils.iters):
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
            # we are going to messa round with the cid_tree's contents 
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
                w = Wrapped(MoreRecursion(self.link, 0, p_id))
                w.children.append(to_add)
                extra[p_id] = w


        # items is a list of things we actually care about so load them
        items = Comment._byID(items, data = True, return_dict = False)
        cdef list wrapped = self.wrap_items(items)


        # break here
        # -----
        cids = {}
        for cm in wrapped:
            cids[cm._id] = cm

        cdef list final = []
        #make tree

        for cm in wrapped:
            # don't show spam with no children
            if cm.deleted and not cid_tree.has_key(cm._id):
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

        for p_id, morelink in extra.iteritems():
            if p_id not in cids:
                if p_id in ignored_parent_ids:
                    raise KeyError("%r not in cids because it was ignored" % p_id)
                else:
                    raise KeyError("%r not in cids but it wasn't ignored" % p_id)
            parent = cids[p_id]
            parent.child = empty_listing(morelink)
            parent.child.parent_name = parent._fullname

        if not self.load_more:
            return final

        #put the remaining comments into the tree (the show more comments link)
        cdef dict more_comments = {}
        while candidates:
            to_add = candidates.pop(0)
            direct_child = True
            #ignore top-level comments for now
            p_id = parents[to_add]
            #find the parent actually being displayed
            #direct_child is whether the comment is 'top-level'
            while p_id and not cids.has_key(p_id):
                p_id = parents[p_id]
                direct_child = False

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
                            prev = tree[-(self.num+1)][0]
                            tree = tree[-self.num:]
                    else:
                        prev = self.after._id
                        tree = filter(
                            self._tree_filter,
                            tree)
                if len(tree) > self.num:
                    tree = tree[:self.num]
                    next = tree[-1][0]

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
            wrapped[m._id] = m

        if prev:
            prev = wrapped[prev]
        if next:
            next = wrapped[next]

        final = []
        for parent, children in tree:
            parent = wrapped[parent]
            if children:
                # if no parent is specified, check if any of the messages are
                # uncollapsed, and truncate the thread
                children = [wrapped[child] for child in children]
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

