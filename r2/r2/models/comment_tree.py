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

from r2.lib.db import tdb_cassandra
from r2.lib import utils
from r2.models.last_modified import LastModified
from r2.models.link import Comment

from pycassa import batch, types
from pycassa.cassandra import ttypes
from pycassa.system_manager import ASCII_TYPE, COUNTER_COLUMN_TYPE

from pylons import g


class CommentTreeStorageBase(object):
    _maintain_num_children = True

    class NoOpContext:
        def __enter__(self):
            pass

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    @classmethod
    def mutation_context(cls, link, timeout=None):
        return cls.NoOpContext()

    @classmethod
    def by_link(cls, link):
        raise NotImplementedError

    @classmethod
    def rebuild(cls, tree, comments):
        return cls.add_comments(tree, comments)

    @classmethod
    def add_comments(cls, tree, comments):
        cids = tree.cids
        depth = tree.depth
        num_children = tree.num_children

        #dfs to find the list of parents for the new comment
        def find_parents(cid):
            # initialize stack with copy of top-level cids
            stack = tree.tree[None][:]
            parents = []
            while stack:
                cur = stack.pop()
                if cur == cid:
                    return parents
                elif cur in tree.tree:
                    #make cur the end of the parents list
                    parents = parents[:depth[cur]] + [cur]
                    stack.extend(tree.tree[cur])

        new_parents = {}
        for comment in comments:
            cid = comment._id
            p_id = comment.parent_id

            #make sure we haven't already done this before (which would happen
            #if the tree isn't cached when you add a comment)
            if cid in cids:
                continue

            #add to comment list
            cids.append(cid)

            #add to tree
            tree.tree.setdefault(p_id, []).append(cid)

            #add to depth
            depth[cid] = depth[p_id] + 1 if p_id else 0

            #update children
            if cls._maintain_num_children:
                num_children[cid] = 0

            #if this comment had a parent, find the parent's parents
            if p_id:
                new_parents[cid] = p_id
                if cls._maintain_num_children:
                    for p_id in find_parents(cid):
                        num_children[p_id] += 1

        # update our cache of children -> parents as well:
        if not tree.parents:
            tree.parents = tree.parent_dict_from_tree(tree.tree)

        parents = tree.parents

        for cid, p_id in new_parents.iteritems():
            parents[cid] = p_id

        for comment in comments:
            cid = comment._id
            if cid not in new_parents:
                parents[cid] = None

    @classmethod
    def delete_comment(cls, tree, comment):
        # only remove leaf comments from the tree
        if comment._id not in tree.tree:
            if comment._id in tree.cids:
                tree.cids.remove(comment._id)
            if comment._id in tree.depth:
                del tree.depth[comment._id]
            if comment._id in tree.num_children:
                del tree.num_children[comment._id]


class CommentTreeStorageV2(CommentTreeStorageBase):
    """Cassandra column-based storage for comment trees.

    Under this implementation, each column in a link's row corresponds to a
    comment on that link. The column name is an encoding of the tuple of
    (comment.parent_id, comment._id), and the value is a counter giving the
    size of the subtree rooted at the comment.

    Key features:
        - does not use permacache!
        - does not require locking for updates
    """

    __metaclass__ = tdb_cassandra.ThingMeta
    _connection_pool = 'main'
    _use_db = True

    _type_prefix = None
    _cf_name = 'CommentTree'

    # column keys are tuples of (depth, parent_id, comment_id)
    _compare_with = types.CompositeType(
        types.LongType(),
        types.LongType(),
        types.LongType())

    # column values are counters
    _extra_schema_creation_args = {
        'default_validation_class': COUNTER_COLUMN_TYPE,
        'replicate_on_write': True,
    }

    COLUMN_READ_BATCH_SIZE = tdb_cassandra.max_column_count
    COLUMN_WRITE_BATCH_SIZE = 1000

    @staticmethod
    def _key(link):
        revision = getattr(link, 'comment_tree_id', 0)
        if revision:
            return '%s:%s' % (utils.to36(link._id), utils.to36(revision))
        else:
            return utils.to36(link._id)

    @staticmethod
    def _column_to_obj(cols):
        for col in cols:
            for (depth, pid, cid), val in col.iteritems():
                yield (depth, None if pid == -1 else pid, cid), val

    @classmethod
    def by_link(cls, link):
        try:
            row = cls.get_row(cls._key(link))
        except ttypes.NotFoundException:
            row = {}
        return cls._from_row(row)

    @classmethod
    def get_row(cls, key):
        row = []
        size = 0
        column_start = ''
        while True:
            batch = cls._cf.get(key, column_count=cls.COLUMN_READ_BATCH_SIZE,
                                column_start=column_start)
            row.extend(batch.iteritems())
            num_fetched = len(row) - size
            size = len(row)
            if num_fetched < cls.COLUMN_READ_BATCH_SIZE:
                break
            depth, pid, cid = row[-1][0]
            column_start = (depth, pid if pid is not None else -1, cid + 1)
        return row

    @classmethod
    def _from_row(cls, row):
        # row is a dict of {(depth, parent_id, comment_id): subtree_size}
        cids = []
        tree = {}
        depth = {}
        parents = {}
        num_children = {}
        for (d, pid, cid), val in row:
            if cid == -1:
                continue
            if pid == -1:
                pid = None
            cids.append(cid)
            tree.setdefault(pid, []).append(cid)
            depth[cid] = d
            parents[cid] = pid
            num_children[cid] = val - 1
        return dict(cids=cids, tree=tree, depth=depth,
                    num_children=num_children, parents=parents)

    @classmethod
    @tdb_cassandra.will_write
    def rebuild(cls, tree, comments):
        with batch.Mutator(g.cassandra_pools[cls._connection_pool]) as m:
            g.log.debug('removing tree from %s', cls._key(tree.link))
            m.remove(cls._cf, cls._key(tree.link))
        tree.link._incr('comment_tree_id')
        g.log.debug('link %s comment tree revision bumped up to %s',
                    tree.link._fullname, tree.link.comment_tree_id)

        # make sure all comments have parents attribute filled in
        parents = {c._id: c.parent_id for c in comments}
        for c in comments:
            if c.parent_id and c.parents is None:
                path = []
                pid = c.parent_id
                while pid:
                    path.insert(0, pid)
                    pid = parents[pid]
                c.parents = ':'.join(utils.to36(i) for i in path)
                c._commit()

        return cls.add_comments(tree, comments)

    @classmethod
    @tdb_cassandra.will_write
    def add_comments(cls, tree, comments):
        CommentTreeStorageBase.add_comments(tree, comments)
        g.log.debug('building updates dict')
        updates = {}
        for c in comments:
            pids = c.parent_path()
            pids.append(c._id)
            for d, (pid, cid) in enumerate(zip(pids, pids[1:])):
                k = (d, pid, cid)
                updates[k] = updates.get(k, 0) + 1

        g.log.debug('writing %d updates to %s',
                    len(updates), cls._key(tree.link))
        # increment counters in slices of 100
        cols = updates.keys()
        for i in xrange(0, len(updates), cls.COLUMN_WRITE_BATCH_SIZE):
            g.log.debug(
                'adding updates %d..%d', i, i + cls.COLUMN_WRITE_BATCH_SIZE)
            update_batch = {c: updates[c]
                            for c in cols[i:i + cls.COLUMN_WRITE_BATCH_SIZE]}
            with batch.Mutator(g.cassandra_pools[cls._connection_pool]) as m:
                m.insert(cls._cf, cls._key(tree.link), update_batch)
        g.log.debug('added %d comments with %d updates',
                    len(comments), len(updates))

    @classmethod
    @tdb_cassandra.will_write
    def delete_comment(cls, tree, comment):
        CommentTreeStorageBase.delete_comment(tree, comment)
        pids = comment.parent_path()
        pids.append(comment._id)
        updates = {}
        for d, (pid, cid) in enumerate(zip(pids, pids[1:])):
            updates[(d, pid, cid)] = -1
        with batch.Mutator(g.cassandra_pools[cls._connection_pool]) as m:
            m.insert(cls._cf, cls._key(tree.link), updates)

    @classmethod
    @tdb_cassandra.will_write
    def upgrade(cls, tree, link):
        cids = []
        for parent, children in tree.tree.iteritems():
            cids.extend(children)

        comments = {}
        for i in xrange(0, len(cids), 100):
            g.log.debug('  loading comments %d..%d', i, i + 100)
            comments.update(Comment._byID(cids[i:i + 100], data=True))

        # need to fill in parents attr for each comment
        modified = []
        stack = [None]
        while stack:
            pid = stack.pop()
            if pid is None:
                parents = ''
            else:
                parents = comments[pid].parents + ':' + comments[pid]._id36
            children = tree.tree.get(pid, [])
            stack.extend(children)
            for cid in children:
                if comments[cid].parents != parents:
                    comments[cid].parents = parents
                    modified.append(comments[cid])

        for i, comment in enumerate(modified):
            comment._commit()

        cls.add_comments(tree, comments.values())


class CommentTreeStorageV1(CommentTreeStorageBase):
    """Cassandra storage of comment trees, using permacache."""

    @staticmethod
    def _comments_key(link_id):
        return 'comments_' + str(link_id)

    @staticmethod
    def _parent_comments_key(link_id):
        return 'comments_parents_' + str(link_id)

    @staticmethod
    def _lock_key(link_id):
        return 'comment_lock_' + str(link_id)

    @classmethod
    def mutation_context(cls, link, timeout=None):
        return g.make_lock("comment_tree", cls._lock_key(link._id),
                           timeout=timeout)

    @classmethod
    def by_link(cls, link):
        key = cls._comments_key(link._id)
        p_key = cls._parent_comments_key(link._id)
        # prefetch both values, they'll be locally cached
        g.permacache.get_multi([key, p_key])

        r = g.permacache.get(key)
        if not r:
            return None
        cids, cid_tree, depth, num_children = r
        parents = g.permacache.get(p_key)
        if parents is None:
            parents = {}
        return dict(cids=cids, tree=cid_tree, depth=depth,
                    num_children=num_children, parents=parents)

    @classmethod
    def add_comments(cls, tree, comments):
        with cls.mutation_context(tree.link):
            CommentTreeStorageBase.add_comments(tree, comments)
            g.permacache.set(cls._comments_key(tree.link_id),
                             (tree.cids, tree.tree, tree.depth,
                             tree.num_children))
            g.permacache.set(cls._parent_comments_key(tree.link_id),
                             tree.parents)


class CommentTree:
    """Storage for pre-computed relationships between a link's comments.

    An instance of this class serves as a snapshot of a single link's comment
    tree. The actual storage implementation is separated to allow for different
    schemes for different links.

    Attrs:
      - cids: list of ints; link's comment IDs
      - tree: dict of int to list of ints; each non-leaf entry in cids has a
          key in this dict, and the corresponding value is the list of IDs for
          that comment's immediate children
      - depth: dict of int to int; each entry in cids has a key in this dict,
          and the corresponding value is that comment's depth in the tree
          (with a value of 0 for top-level comments)
      - num_children: dict of int to int; each entry in cids has a key in this
          dict, and the corresponding value is the count of that comment's
          descendents in the tree
      - parents: dict of int to int; each entry in cids has a key in this dict,
          and the corresponding value is the ID of that comment's parent (or
          None in the case of top-level comments)
    """

    IMPLEMENTATIONS = {
        1: CommentTreeStorageV1,
        2: CommentTreeStorageV2,
    }

    DEFAULT_IMPLEMENTATION = 2

    def __init__(self, link, **kw):
        self.link = link
        self.link_id = link._id
        self.__dict__.update(kw)

    @classmethod
    def mutation_context(cls, link, timeout=None):
        impl = cls.IMPLEMENTATIONS[link.comment_tree_version]
        return impl.mutation_context(link, timeout=timeout)

    @classmethod
    def by_link(cls, link):
        impl = cls.IMPLEMENTATIONS[link.comment_tree_version]
        data = impl.by_link(link)
        if data is None:
            return None
        else:
            return cls(link, **data)

    def add_comments(self, comments):
        impl = self.IMPLEMENTATIONS[self.link.comment_tree_version]
        impl.add_comments(self, comments)
        utils.set_last_modified(self.link, 'comments')
        LastModified.touch(self.link._fullname, 'Comments')

    def add_comment(self, comment):
        return self.add_comments([comment])

    def delete_comment(self, comment, link):
        impl = self.IMPLEMENTATIONS[link.comment_tree_version]
        impl.delete_comment(self, comment)
        self.link._incr('num_comments', -1)

    @classmethod
    def rebuild(cls, link):
        # fetch all comments and sort by parent_id, so parents are added to the
        # tree before their children
        q = Comment._query(Comment.c.link_id == link._id,
                           Comment.c._deleted == (True, False),
                           Comment.c._spam == (True, False),
                           optimize_rules=True,
                           data=True)
        comments = sorted(q, key=lambda c: c.parent_id)

        # build tree from scratch (for V2 results in double-counting in cass)
        tree = cls(link, cids=[], tree={}, depth={}, num_children={},
                   parents={})
        impl = cls.IMPLEMENTATIONS[link.comment_tree_version]
        impl.rebuild(tree, comments)

        link.num_comments = sum(1 for c in comments if not c._deleted)
        link._commit()

        return tree

    @classmethod
    def upgrade(cls, link, to_version=None):
        if to_version is None:
            to_version = cls.DEFAULT_IMPLEMENTATION
        while link.comment_tree_version < to_version:
            tree = cls.by_link(link)
            new_impl = cls.IMPLEMENTATIONS[link.comment_tree_version + 1]
            new_impl.upgrade(tree, link)
            link.comment_tree_version += 1
            link._commit()

    @staticmethod
    def parent_dict_from_tree(tree):
        parents = {}
        for parent, children in tree.iteritems():
            for child in children:
                parents[child] = parent
        return parents
