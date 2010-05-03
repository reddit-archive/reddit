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
# The Original Code is Reddit.
# 
# The Original Developer is the Initial Developer.  The Initial Developer of the
# Original Code is CondeNet, Inc.
# 
# All portions of the code written by CondeNet are Copyright (c) 2006-2009
# CondeNet, Inc. All Rights Reserved.
################################################################################
from __future__ import with_statement

from pylons import g

from r2.models import *

def comments_key(link_id):
    return 'comments_' + str(link_id)

def lock_key(link_id):
    return 'comment_lock_' + str(link_id)

def add_comment(comment):
    with g.make_lock(lock_key(comment.link_id)):
        add_comment_nolock(comment)

def add_comment_nolock(comment):
    cm_id = comment._id
    p_id = comment.parent_id
    link_id = comment.link_id

    cids, comment_tree, depth, num_children = link_comments(link_id)

    #make sure we haven't already done this before (which would happen
    #if the tree isn't cached when you add a comment)
    if comment._id in cids:
        return

    #add to comment list
    cids.append(comment._id)

    #add to tree
    comment_tree.setdefault(p_id, []).append(cm_id)

    #add to depth
    depth[cm_id] = depth[p_id] + 1 if p_id else 0

    #update children
    num_children[cm_id] = 0

    #dfs to find the list of parents for the new comment
    def find_parents():
        stack = [cid for cid in comment_tree[None]]
        parents = []
        while stack:
            cur_cm = stack.pop()
            if cur_cm == cm_id:
                return parents
            elif comment_tree.has_key(cur_cm):
                #make cur_cm the end of the parents list
                parents = parents[:depth[cur_cm]] + [cur_cm]
                for child in comment_tree[cur_cm]:
                    stack.append(child)


    #if this comment had a parent, find the parent's parents
    if p_id:
        for p_id in find_parents():
            num_children[p_id] += 1

    g.permacache.set(comments_key(link_id),
                     (cids, comment_tree, depth, num_children))

def delete_comment(comment):
    #nothing really to do here, atm
    pass

def link_comments(link_id):
    key = comments_key(link_id)
    r = g.permacache.get(key)
    if r:
        return r
    else:
        with g.make_lock(lock_key(link_id)):
            r = load_link_comments(link_id)
            g.permacache.set(key, r)
        return r

def load_link_comments(link_id):
    q = Comment._query(Comment.c.link_id == link_id,
                       Comment.c._deleted == (True, False),
                       Comment.c._spam == (True, False),
                       data = True)
    comments = list(q)
    cids = [c._id for c in comments]

    #make a tree
    comment_tree = {}
    for cm in comments:
        p_id = cm.parent_id
        comment_tree.setdefault(p_id, []).append(cm._id)

    #calculate the depths
    depth = {}
    level = 0
    cur_level = comment_tree.get(None, ())
    while cur_level:
        next_level = []
        for cm_id in cur_level:
            depth[cm_id] = level
            next_level.extend(comment_tree.get(cm_id, ()))
        cur_level = next_level
        level += 1

    #calc the number of children
    num_children = {}
    for cm_id in cids:
        num = 0
        todo = [cm_id]
        while todo:
            more = comment_tree.get(todo.pop(0), ())
            num += len(more)
            todo.extend(more)
        num_children[cm_id] = num

    return cids, comment_tree, depth, num_children
