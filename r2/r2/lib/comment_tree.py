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
# All portions of the code written by CondeNet are Copyright (c) 2006-2010
# CondeNet, Inc. All Rights Reserved.
################################################################################
from __future__ import with_statement

from pylons import g
from itertools import chain
from utils import tup

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
    from r2.models import Comment
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

# message conversation functions
def messages_key(user_id):
    return 'message_conversations_' + str(user_id)

def messages_lock_key(user_id):
    return 'message_conversations_lock_' + str(user_id)

def add_message(message):
    # add the message to the author's list and the recipient
    with g.make_lock(messages_lock_key(message.author_id)):
        add_message_nolock(message.author_id, message)
    with g.make_lock(messages_lock_key(message.to_id)):
        add_message_nolock(message.to_id, message)

def add_message_nolock(user_id, message):
    from r2.models import Account, Message
    key = messages_key(user_id)
    trees = g.permacache.get(key)
    if not trees:
        # no point computing it now.  We'll do it when they go to
        # their message page.
        return

    # if it is a new root message, easy enough
    if message.first_message is None:
        trees.insert(0, (message._id, []))
    else:
        tree_dict = dict(trees)

        # if the tree already has the first message, update the list
        if message.first_message in tree_dict:
            if message._id not in tree_dict[message.first_message]:
                tree_dict[message.first_message].append(message._id)
                tree_dict[message.first_message].sort()
        # we have to regenerate the conversation :/
        else:
            m = Message._query(Message.c.first_message == message.first_message,
                               data = True)
            new_tree = compute_message_trees(m)
            if new_tree:
                trees.append(new_tree[0])
        trees.sort(key = tree_sort_fn, reverse = True)

    # done!
    g.permacache.set(key, trees)


def conversation(user, parent):
    from r2.models import Message
    trees = dict(user_messages(user))

    if parent._id in trees:
        convo = trees[parent._id]
        if convo:
            m = Message._byID(convo[0], data = True)
        if not convo or m.first_message == m.parent_id:
            return [(parent._id, convo)]

    # if we get to this point, either we didn't find the conversation,
    # or the first child of the result was not the actual first child.
    # To the database!
    m = Message._query(Message.c.first_message == parent._id,
                       data = True)
    return compute_message_trees([parent] + list(m))

def user_messages(user):
    key = messages_key(user._id)
    trees = g.permacache.get(key)
    if trees is None:
        trees = user_messages_nocache(user)
        g.permacache.set(key, trees)
    return trees

def user_messages_nocache(user):
    """
    Just like user_messages, but avoiding the cache
    """
    from r2.lib.db import queries
    from r2.models import Message

    inbox = queries.get_inbox_messages(user)
    if hasattr(inbox, 'prewrap_fn'):
        inbox = [inbox.prewrap_fn(i) for i in inbox]
    else:
        inbox = list(inbox)

    sent = queries.get_sent(user)
    if hasattr(sent, 'prewrap_fn'):
        sent = [sent.prewrap_fn(i) for i in sent]
    else:
        sent = list(sent)
    
    m = {}
    ids = [x for x in chain(inbox, sent) if not isinstance(x, Message)]
    if ids:
        m = Message._by_fullname(ids, return_dict = True, data = True)

    messages = [m.get(x, x) for x in chain(inbox, sent)]

    return compute_message_trees(messages)

def compute_message_trees(messages):
    from r2.models import Message
    roots = set()
    threads = {}
    mdict = {}
    messages = sorted(messages, key = lambda m: m._date, reverse = True)

    for m in messages:
        if not m._loaded:
            m._load()
        mdict[m._id] = m
        if m.first_message:
            roots.add(m.first_message)
            threads.setdefault(m.first_message, set()).add(m._id)
        else:
            roots.add(m._id)

    # load any top-level messages which are not in the original list
    missing = [m for m in roots if m not in mdict]
    if missing:
        mdict.update(Message._byID(tup(missing),
                                   return_dict = True, data = True))

    # sort threads in chrono order
    for k in threads:
        threads[k] = list(sorted(threads[k]))

    tree = [(root, threads.get(root, [])) for root in roots]
    tree.sort(key = tree_sort_fn, reverse = True)

    return tree

def tree_sort_fn(tree):
    root, threads = tree
    return threads[-1] if threads else root
