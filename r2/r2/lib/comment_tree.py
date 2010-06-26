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
from cache import sgm

def comments_key(link_id):
    return 'comments_' + str(link_id)

def lock_key(link_id):
    return 'comment_lock_' + str(link_id)

def parent_comments_key(link_id):
    return 'comments_parents_' + str(link_id)

def sort_comments_key(link_id, sort):
    return 'comments_sort_%s_%s'  % (link_id, sort)

def _get_sort_value(comment, sort):
    if sort == "_date":
        return comment._date
    return getattr(comment, sort), comment._date


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

    # update our cache of children -> parents as well:
    key = parent_comments_key(link_id)
    r = g.permacache.get(key)

    if not r:
        r = _parent_dict_from_tree(comment_tree)
    r[cm_id] = p_id
    g.permacache.set(key, r)

    # update the list of sorts
    for sort in ("_controversy", "_date", "_hot", "_confidence", "_score"):
        key = sort_comments_key(link_id, sort)
        r = g.permacache.get(key)
        if r:
            r[cm_id] = _get_sort_value(comment, sort)
            g.permacache.set(key, r)

    # do this last b/c we don't want the cids updated before the sorts
    # and parents
    g.permacache.set(comments_key(link_id),
                     (cids, comment_tree, depth, num_children))



def update_comment_vote(comment):
    link_id = comment.link_id
    # update the list of sorts
    with g.make_lock(lock_key(link_id)):
        for sort in ("_controversy", "_hot", "_confidence", "_score"):
            key = sort_comments_key(link_id, sort)
            r = g.permacache.get(key)
            # don't bother recomputing a non-existant sort dict, as
            # we'll catch it next time we have to render something
            if r:
                r[comment._id] = _get_sort_value(comment, sort)
                g.permacache.set(key, r)


def delete_comment(comment):
    with g.make_lock(lock_key(comment.link_id)):
        cids, comment_tree, depth, num_children = link_comments(comment.link_id)

        # only completely remove comments with no children
        if comment._id not in comment_tree:
            if comment._id in cids:
                cids.remove(comment._id)
            if comment._id in depth:
                del depth[comment._id]
            if comment._id in num_children:
                del num_children[comment._id]
            g.permacache.set(comments_key(comment.link_id),
                             (cids, comment_tree, depth, num_children))


def _parent_dict_from_tree(comment_tree):
    parents = {}
    for parent, childs in comment_tree.iteritems():
        for child in childs:
            parents[child] = parent
    return parents

def _comment_sorter_from_cids(cids, sort):
    from r2.models import Comment
    comments = Comment._byID(cids, data = False, return_dict = False)
    return dict((x._id, _get_sort_value(x, sort)) for x in comments)

def link_comments_and_sort(link_id, sort):
    cids, cid_tree, depth, num_children = link_comments(link_id)

    # load the sorter
    key = sort_comments_key(link_id, sort)
    sorter = g.permacache.get(key)
    if sorter is None:
        g.log.error("comment_tree.py: sorter (%s) cache miss for Link %s"
                    % (sort, link_id))
        sorter = {}
    elif cids and not all(x in sorter for x in cids):
        g.log.error("Error in comment_tree: sorter (%s) inconsistent for Link %s"
                    % (sort, link_id))
        sorter = {}

    # load the parents
    key = parent_comments_key(link_id)
    parents = g.permacache.get(key)
    if parents is None:
        g.log.error("comment_tree.py: parents cache miss for Link %s"
                    % link_id)
        parents = {}
    elif cids and not all(x in parents for x in cids):
        g.log.error("Error in comment_tree: parents inconsistent for Link %s"
                    % link_id)
        parents = {}

    if not sorter or not parents:
        with g.make_lock(lock_key(link_id)):
            # reload from the cache so the sorter and parents are
            # maximally consistent
            r = g.permacache.get(comments_key(link_id))
            cids, cid_tree, depth, num_children = r

            key = sort_comments_key(link_id, sort)
            if not sorter:
                sorter = _comment_sorter_from_cids(cids, sort)
                g.permacache.set(key, sorter)

            key = parent_comments_key(link_id)
            if not parents:
                parents = _parent_dict_from_tree(cid_tree)
                g.permacache.set(key, parents)

    return cids, cid_tree, depth, num_children, parents, sorter


def link_comments(link_id, _update=False):
    key = comments_key(link_id)

    r = g.permacache.get(key)

    if r and not _update:
        return r
    else:
        # This operation can take longer than most (note the inner
        # locks) better to time out request temporarily than to deal
        # with an inconsistent tree
        with g.make_lock(lock_key(link_id), timeout=180):
            r = _load_link_comments(link_id)
            # rebuild parent dict
            cids, cid_tree, depth, num_children = r
            g.permacache.set(parent_comments_key(link_id),
                             _parent_dict_from_tree(cid_tree))

            # rebuild the sorts
            for sort in ("_controversy","_date","_hot","_confidence","_score"):
                g.permacache.set(sort_comments_key(link_id, sort),
                                 _comment_sorter_from_cids(cids, sort))

            g.permacache.set(key, r)
            return r


def _load_link_comments(link_id):
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
    if message.to_id:
        with g.make_lock(messages_lock_key(message.to_id)):
            add_message_nolock(message.to_id, message)
    if message.sr_id:
        with g.make_lock(sr_messages_lock_key(message.sr_id)):
            add_sr_message_nolock(message.sr_id, message)


def _add_message_nolock(key, message):
    from r2.models import Account, Message
    trees = g.permacache.get(key)
    if not trees:
        # in case an empty list got written at some point, delete it to
        # force a recompute
        if trees is not None:
            g.permacache.delete(key)
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


def add_message_nolock(user_id, message):
    return _add_message_nolock(messages_key(user_id), message)

def _conversation(trees, parent):
    from r2.models import Message
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

def conversation(user, parent):
    trees = dict(user_messages(user))
    return _conversation(trees, parent)


def user_messages(user, update = False):
    key = messages_key(user._id)
    trees = g.permacache.get(key)
    if not trees or update:
        trees = user_messages_nocache(user)
        g.permacache.set(key, trees)
    return trees

def _process_message_query(inbox):
    if hasattr(inbox, 'prewrap_fn'):
        return [inbox.prewrap_fn(i) for i in inbox]
    return list(inbox)


def _load_messages(mlist):
    from r2.models import Message
    m = {}
    ids = [x for x in mlist if not isinstance(x, Message)]
    if ids:
        m = Message._by_fullname(ids, return_dict = True, data = True)
    messages = [m.get(x, x) for x in mlist]
    return messages

def user_messages_nocache(user):
    """
    Just like user_messages, but avoiding the cache
    """
    from r2.lib.db import queries
    inbox = _process_message_query(queries.get_inbox_messages(user))
    sent = _process_message_query(queries.get_sent(user))
    messages = _load_messages(list(chain(inbox, sent)))
    return compute_message_trees(messages)

def sr_messages_key(sr_id):
    return 'sr_messages_conversation_' + str(sr_id)

def sr_messages_lock_key(sr_id):
    return 'sr_messages_conversation_lock_' + str(sr_id)


def subreddit_messages(sr, update = False):
    key = sr_messages_key(sr._id)
    trees = g.permacache.get(key)
    if not trees or update:
        trees = subreddit_messages_nocache(sr)
        g.permacache.set(key, trees)
    return trees

def moderator_messages(user):
    from r2.models import Subreddit
    sr_ids = Subreddit.reverse_moderator_ids(user)

    def multi_load_tree(sr_ids):
        srs = Subreddit._byID(sr_ids, return_dict = False)
        res = {}
        for sr in srs:
            trees = subreddit_messages_nocache(sr)
            if trees:
                res[sr._id] = trees
        return res

    res = sgm(g.permacache, sr_ids, miss_fn = multi_load_tree,
              prefix = sr_messages_key(""))

    return sorted(chain(*res.values()), key = tree_sort_fn, reverse = True)

def subreddit_messages_nocache(sr):
    """
    Just like user_messages, but avoiding the cache
    """
    from r2.lib.db import queries
    inbox = _process_message_query(queries.get_subreddit_messages(sr))
    messages = _load_messages(inbox)
    return compute_message_trees(messages)


def add_sr_message_nolock(sr_id, message):
    return _add_message_nolock(sr_messages_key(sr_id), message)

def sr_conversation(sr, parent):
    trees = dict(subreddit_messages(sr))
    return _conversation(trees, parent)


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
