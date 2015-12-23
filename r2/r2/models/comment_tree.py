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

from r2.lib.db import tdb_cassandra
from r2.lib import utils
from r2.models.link import Comment

from pycassa import batch, types
from pycassa.cassandra import ttypes
from pycassa.system_manager import ASCII_TYPE, COUNTER_COLUMN_TYPE

from pylons import app_globals as g


"""Storage for comment trees

CommentTree is a class that provides an interface to the actual storage.
Whatever the underlying storage is, it must be able to generate the following
structures:
* tree: dict of comment id -> list of child comment ids. The `None` entry is
  top level comments
* cids: list of all comment ids in the comment tree
* depth: dict of comment id -> depth
* parents: dict of comment id -> parent comment id

CommentTreeStorageV1 uses permacache as the storage, and stores cids, tree, and
depth as a tuple in one key, and parents in a second key.

Attempts were made to move to a different data model that would take advantage
of the column based storage of Cassandra and eliminate the need for locking when
adding a comment to the comment tree.

CommentTreeStorageV2: for each comment, write a column where the column name is
(parent_comment id, comment_id) and the column value is a counter giving the
size of the subtree rooted at the comment. This data model was abandoned because
counters ended up being unreliable and the shards put too much GC pressure on
the Cassandra JVM.

CommentTreeStorageV3: for each comment, write a column where the column name is
(depth, parent_comment_id, comment_id) and the column value is not used. This
data model was abandoned because of more unexpected GC problems after longer
time periods and generally insufficient regular-case performance.

"""


class CommentTreeStorageBase(object):
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
    def write_from_comment_tree(cls, link, comment_tree):
        """Write the storage from a full version of the comment tree.

        Can be used to switch storage methods.

        """

        raise NotImplementedError

    @classmethod
    def add_comments(cls, tree, comments):
        cids = tree.cids
        depth = tree.depth

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

            #if this comment had a parent, find the parent's parents
            if p_id:
                new_parents[cid] = p_id

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
        pass

    @classmethod
    def prepare_new_storage(cls, link):
        """Do whatever's needed to initialize the storage for a new link."""
        pass


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
    def prepare_new_storage(cls, link):
        """Write an empty storage to permacache"""
        with cls.mutation_context(link):
            # probably don't need the lock because this should run immediately
            # when the link is created and before the response is returned
            key = cls._comments_key(link._id)
            pkey = cls._parent_comments_key(link._id)

            cids = []
            tree = {}
            depth = {}
            parents = {}

            to_set = {
                key: (cids, tree, depth),
                pkey: parents,
            }
            g.permacache.set_multi(to_set)

    @classmethod
    def by_link(cls, link):
        key = cls._comments_key(link._id)
        p_key = cls._parent_comments_key(link._id)
        # prefetch both values, they'll be locally cached
        g.permacache.get_multi([key, p_key])

        r = g.permacache.get(key)
        if not r:
            # this link has not had an empty tree written for it. make an empty
            # tree here and return it. the downside is that until a comment is
            # added every time the storage for this link is requested it will
            # have a cache miss and fall through to cassandra
            return dict(cids=[], tree={}, depth={}, parents={})

        try:
            cids, cid_tree, depth = r
        except ValueError:
            # We got the old version that includes num_children
            cids, cid_tree, depth, num_children = r

        parents = g.permacache.get(p_key)
        if parents is None:
            parents = {}
        return dict(cids=cids, tree=cid_tree, depth=depth, parents=parents)

    @classmethod
    def write_from_comment_tree(cls, link, comment_tree):
        cids = comment_tree.cids
        tree = comment_tree.tree
        depth = comment_tree.depth
        parents = comment_tree.parents

        key = cls._comments_key(link._id)
        pkey = cls._parent_comments_key(link._id)
        to_set = {
            key: (cids, tree, depth),
            pkey: parents,
        }
        g.permacache.set_multi(to_set)

    @classmethod
    def add_comments(cls, tree, comments):
        with cls.mutation_context(tree.link):
            CommentTreeStorageBase.add_comments(tree, comments)
            # for read safety write parents first
            g.permacache.set(cls._parent_comments_key(tree.link_id),
                             tree.parents)
            g.permacache.set(cls._comments_key(tree.link_id),
                             (tree.cids, tree.tree, tree.depth))


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
      - parents: dict of int to int; each entry in cids has a key in this dict,
          and the corresponding value is the ID of that comment's parent (or
          None in the case of top-level comments)
    """

    IMPLEMENTATIONS = {
        1: CommentTreeStorageV1,
        2: None,    # placeholder for abandoned CommentTreeStorageV2
        3: None,    # placeholder for abandoned CommentTreeStorageV3
    }

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
        return cls(link, **data)

    @classmethod
    def on_new_link(cls, link):
        impl = cls.IMPLEMENTATIONS[link.comment_tree_version]
        impl.prepare_new_storage(link)

    def add_comments(self, comments):
        impl = self.IMPLEMENTATIONS[self.link.comment_tree_version]
        impl.add_comments(self, comments)

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
        tree = cls(link, cids=[], tree={}, depth={}, parents={})
        impl = cls.IMPLEMENTATIONS[link.comment_tree_version]
        impl.rebuild(tree, comments)

        link.num_comments = sum(1 for c in comments if not c._deleted)
        link._commit()

        return tree

    @classmethod
    def change_storage_version(cls, link, to_version):
        """Switch a link's comment tree storage"""

        if to_version == link.comment_tree_version:
            return

        with cls.mutation_context(link):
            # get the lock to prevent writes to the comment tree we're moving
            # away from
            comment_tree = cls.by_link(link)
            new_storage_cls = cls.IMPLEMENTATIONS[to_version]
            new_storage_cls.write_from_comment_tree(link, comment_tree)
            link.comment_tree_version = to_version
            link._commit()

    @staticmethod
    def parent_dict_from_tree(tree):
        parents = {}
        for parent, children in tree.iteritems():
            for child in children:
                parents[child] = parent
        return parents
