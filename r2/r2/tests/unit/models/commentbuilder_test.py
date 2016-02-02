#!/usr/bin/env python
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

from collections import namedtuple, defaultdict
from mock import MagicMock

from r2.lib.utils.comment_tree_utils import get_tree_details, calc_num_children
from r2.lib.db import operators
from r2.models import builder
from r2.models import Comment
from r2.models.builder import CommentBuilder
from r2.models.comment_tree import CommentTree
from r2.tests import RedditTestCase


CommentTreeElement = namedtuple(
    "CommentTreeElement", ["id", "score", "children"])


TREE = [
    CommentTreeElement(id=100, score=100, children=[
        CommentTreeElement(id=101, score=90, children=[]),
        CommentTreeElement(id=102, score=80, children=[
            CommentTreeElement(id=104, score=95, children=[]),
            CommentTreeElement(id=105, score=85, children=[]),
            CommentTreeElement(id=106, score=75, children = []),
        ]),
        CommentTreeElement(id=103, score=70, children=[]),
    ]),
    CommentTreeElement(id=107, score=60, children=[]),
    CommentTreeElement(id=108, score=55, children=[
        CommentTreeElement(id=110, score=110, children=[]),
    ]),
    CommentTreeElement(id=109, score=50, children=[]),
]


def make_comment_tree(link):
    tree = {}

    def _add_comment(comment, parent):
        tree[comment.id] = [child.id for child in comment.children]
        for child in comment.children:
            _add_comment(child, parent=comment)

    tree[None] = [comment.id for comment in TREE]

    for comment in TREE:
        _add_comment(comment, parent=None)

    cids, depth, parents = get_tree_details(tree)
    num_children = calc_num_children(tree)
    num_children = defaultdict(int, num_children)

    return CommentTree(link, cids, tree, depth, parents, num_children)


def make_comment_scores():
    scores_by_id = {}

    def _add_comment(comment):
        scores_by_id[comment.id] = comment.score
        for child in comment.children:
            _add_comment(child)

    for comment in TREE:
        _add_comment(comment)

    return scores_by_id


class CommentOrderTest(RedditTestCase):
    def setUp(self):
        self.link = MagicMock()
        self.link._id = 1000
        self.link.sticky_comment_id = None

        comment_scores = make_comment_scores()
        self.autopatch(
            builder, "get_comment_scores", return_value=comment_scores)

        comment_tree_for_link = make_comment_tree(self.link)
        self.autopatch(
            CommentTree, "by_link", return_value=comment_tree_for_link)

        # make the lookup in _get_comments a noop
        self.autopatch(Comment, "_byID", return_value={})

        # side effect of building MoreRecursion objects
        self.autopatch(Comment, "_type_id", 1, create=True)

    def tearDown(self):
        self.link = None

    def test_comment_order_full(self):
        sort = operators.desc("_confidence")
        builder = CommentBuilder(self.link, sort, num=1500)
        builder._get_comments()
        self.assertEqual(builder.comment_order,
            [100, 101, 102, 104, 105, 106, 103, 107, 108, 110, 109])

    def test_comment_order_full_asc(self):
        sort = operators.asc("_confidence")
        builder = CommentBuilder(self.link, sort, num=1500)
        builder._get_comments()
        self.assertEqual(builder.comment_order,
            [109, 108, 107, 100, 103, 102, 106, 105, 101, 104, 110])

    def test_comment_order_limit(self):
        sort = operators.desc("_confidence")
        builder = CommentBuilder(self.link, sort, num=5)
        builder._get_comments()
        self.assertEqual(builder.comment_order, [100, 101, 102, 104, 105])

    def test_comment_order_depth(self):
        sort = operators.desc("_confidence")
        builder = CommentBuilder(self.link, sort, num=1500, max_depth=1)
        builder._get_comments()
        self.assertEqual(builder.comment_order, [100, 107, 108, 109])

    def test_comment_order_sticky(self):
        self.link.sticky_comment_id = 100
        sort = operators.desc("_confidence")
        builder = CommentBuilder(self.link, sort, num=1500)
        builder._get_comments()
        self.assertEqual(builder.comment_order, [100, 107, 108, 110, 109])

    def test_comment_order_invalid_sticky(self):
        self.link.sticky_comment_id = 101
        sort = operators.desc("_confidence")
        builder = CommentBuilder(self.link, sort, num=1500)
        builder._get_comments()
        self.assertEqual(builder.comment_order,
            [100, 101, 102, 104, 105, 106, 103, 107, 108, 110, 109])

    def test_comment_order_permalink(self):
        sort = operators.desc("_confidence")
        comment = MagicMock()
        comment._id = 100
        builder = CommentBuilder(self.link, sort, comment=comment, num=1500)
        builder._get_comments()
        self.assertEqual(builder.comment_order,
            [100, 101, 102, 104, 105, 106, 103])

    def test_comment_order_permalink_context(self):
        sort = operators.desc("_confidence")
        comment = MagicMock()
        comment._id = 104
        builder = CommentBuilder(
            self.link, sort, comment=comment, context=3, num=1500)
        builder._get_comments()
        self.assertEqual(builder.comment_order, [100, 102, 104])

    def test_comment_order_invalid_permalink_defocus(self):
        sort = operators.desc("_confidence")
        comment = MagicMock()
        comment._id = 999999
        builder = CommentBuilder(self.link, sort, comment=comment, num=1500)
        builder._get_comments()
        self.assertEqual(builder.comment_order,
            [100, 101, 102, 104, 105, 106, 103, 107, 108, 110, 109])

    def test_comment_order_children(self):
        sort = operators.desc("_confidence")
        builder = CommentBuilder(
            self.link, sort, children=[101, 102, 103], num=1500)
        builder._get_comments()
        self.assertEqual(builder.comment_order, [101, 102, 104, 105, 106, 103])

    def test_comment_order_children_limit(self):
        sort = operators.desc("_confidence")
        builder = CommentBuilder(
            self.link, sort, children=[107, 108, 109], num=3)
        builder._get_comments()
        self.assertEqual(builder.comment_order, [107, 108, 110])
