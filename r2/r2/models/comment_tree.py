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

from pycassa import batch, types
from pycassa.cassandra import ttypes
from pycassa.system_manager import ASCII_TYPE, COUNTER_COLUMN_TYPE
from pylons import app_globals as g

from r2.lib import utils
from r2.lib.db import tdb_cassandra
from r2.lib.utils import SimpleSillyStub
from r2.lib.utils.comment_tree_utils import get_tree_details, calc_num_children
from r2.models.link import Comment


"""Storage for comment trees

CommentTree is a class that provides an interface to the actual storage.
Whatever the underlying storage is, it must be able to generate the following
structures:
* tree: dict of comment id -> list of child comment ids. The `None` entry is
  top level comments
* cids: list of all comment ids in the comment tree
* depth: dict of comment id -> depth
* parents: dict of comment id -> parent comment id
* num_children: dict of comment id -> number of descendant comments, not just
  direct children

CommentTreePermacache uses permacache as the storage, and stores just the tree
structure. The cids, depth, parents and num_children are generated on the fly
from the tree.

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


class CommentTreePermacache(object):
    @staticmethod
    def _comments_key(link_id):
        return 'comments_' + str(link_id)

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
            tree = {}
            g.permacache.set(key, tree)

    @classmethod
    def get_tree_pieces(cls, link, timer):
        key = cls._comments_key(link._id)
        tree = g.permacache.get(key)
        timer.intermediate('load')

        tree = tree or {}   # assume empty tree on miss
        cids, depth, parents = get_tree_details(tree)
        num_children = calc_num_children(tree)
        num_children = defaultdict(int, num_children)
        timer.intermediate('calculate')

        return cids, tree, depth, parents, num_children

    @classmethod
    def add_comments(cls, tree, comments):
        if all(comment._id in tree.cids for comment in comments):
            # don't bother to write if this would be a no-op
            return

        with cls.mutation_context(tree.link):
            # NOTE: should really wait until here to get the tree to make
            # sure it's done under lock. r2.lib.comment_tree.add_comments is
            # the only current caller, and it does get the lock before calling
            # this method, but it should be enforced in the structure of this
            # class

            for comment in sorted(comments, key=lambda c: c._id):
                # sort the comments by id so we'll process a parent comment
                # before its child
                cid = comment._id
                p_id = comment.parent_id

                # don't add a comment that is already in the tree
                if cid in tree.cids:
                    continue

                if p_id and p_id not in tree.cids:
                    # can't add a comment to the CommentTree because its parent
                    # is missing. this comment will be lost forever unless the
                    # tree is rebuilt.
                    g.log.error(
                        "comment_tree_inconsistent: %s %s" % (tree.link, cid))
                    g.stats.simple_event('comment_tree_inconsistent')
                    continue

                tree.cids.append(cid)
                tree.tree.setdefault(p_id, []).append(cid)
                tree.depth[cid] = tree.depth[p_id] + 1 if p_id else 0
                tree.parents[cid] = p_id

            key = cls._comments_key(tree.link._id)
            g.permacache.set(key, tree.tree)

    @classmethod
    def rebuild(cls, tree, comments):
        return cls.add_comments(tree, comments)


class CommentTree:
    def __init__(self, link, cids, tree, depth, parents, num_children):
        self.link = link
        self.cids = cids
        self.tree = tree
        self.depth = depth
        self.parents = parents
        self.num_children = num_children

    @classmethod
    def mutation_context(cls, link, timeout=None):
        return CommentTreePermacache.mutation_context(link, timeout=timeout)

    @classmethod
    def by_link(cls, link, timer=None):
        if timer is None:
            timer = SimpleSillyStub()

        pieces = CommentTreePermacache.get_tree_pieces(link, timer)
        cids, tree, depth, parents, num_children = pieces
        comment_tree = cls(link, cids, tree, depth, parents, num_children)
        return comment_tree

    @classmethod
    def on_new_link(cls, link):
        CommentTreePermacache.prepare_new_storage(link)

    def add_comments(self, comments):
        CommentTreePermacache.add_comments(self, comments)

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

        # remove any comments with missing parents
        comment_ids = {comment._id for comment in comments}
        comments = [
            comment for comment in comments
            if not comment.parent_id or comment.parent_id in comment_ids 
        ]

        # build tree from scratch
        tree = cls(link, cids=[], tree={}, depth={}, parents={}, num_children={})
        CommentTreePermacache.rebuild(tree, comments)

        link.num_comments = sum(1 for c in comments if not c._deleted)
        link._commit()

        return tree
