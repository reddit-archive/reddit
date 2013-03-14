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

from pylons import g, c
from itertools import chain
from r2.lib.utils import SimpleSillyStub, tup, to36
from r2.lib.db.sorts import epoch_seconds
from r2.lib.cache import sgm
from r2.models.comment_tree import CommentTree
from r2.models.link import Comment, Link

MAX_ITERATIONS = 50000

def comments_key(link_id):
    return 'comments_' + str(link_id)

def lock_key(link_id):
    return 'comment_lock_' + str(link_id)

def parent_comments_key(link_id):
    return 'comments_parents_' + str(link_id)

def sort_comments_key(link_id, sort):
    assert sort.startswith('_')
    return '%s%s' % (to36(link_id), sort)

def _get_sort_value(comment, sort):
    if sort == "_date":
        return epoch_seconds(comment._date)
    return getattr(comment, sort)

def add_comments(comments):
    links = Link._byID([com.link_id for com in tup(comments)], data=True)
    comments = tup(comments)

    link_map = {}
    for com in comments:
        link_map.setdefault(com.link_id, []).append(com)

    for link_id, coms in link_map.iteritems():
        link = links[link_id]
        timer = g.stats.get_timer('comment_tree.add.%s'
                                  % link.comment_tree_version)
        timer.start()
        try:
            with CommentTree.mutation_context(link):
                timer.intermediate('lock')
                cache = get_comment_tree(link, timer=timer)
                timer.intermediate('get')
                cache.add_comments(coms)
                timer.intermediate('update')
        except:
            g.log.exception(
                'add_comments_nolock failed for link %s, recomputing tree',
                link_id)

            # calculate it from scratch
            get_comment_tree(link, _update=True, timer=timer)
        timer.stop()
        update_comment_votes(coms)

def update_comment_votes(comments, write_consistency_level = None):
    from r2.models import CommentSortsCache

    comments = tup(comments)

    link_map = {}
    for com in comments:
        link_map.setdefault(com.link_id, []).append(com)

    for link_id, coms in link_map.iteritems():
        for sort in ("_controversy", "_hot", "_confidence", "_score", "_date"):
            # Cassandra always uses the id36 instead of the integer
            # ID, so we'll map that first before sending it
            c_key = sort_comments_key(link_id, sort)
            c_r = dict((cm._id36, _get_sort_value(cm, sort))
                       for cm in coms)
            CommentSortsCache._set_values(c_key, c_r,
                                          write_consistency_level = write_consistency_level)

def delete_comment(comment):
    link = Link._byID(comment.link_id, data=True)
    timer = g.stats.get_timer('comment_tree.delete.%s'
                              % link.comment_tree_version)
    timer.start()
    with CommentTree.mutation_context(link):
        timer.intermediate('lock')
        cache = get_comment_tree(link)
        timer.intermediate('get')
        cache.delete_comment(comment, link)
        timer.intermediate('update')
        from r2.lib.db.queries import changed
        changed([link])
        timer.intermediate('changed')
    timer.stop()

def _comment_sorter_from_cids(cids, sort):
    comments = Comment._byID(cids, data = False, return_dict = False)
    return dict((x._id, _get_sort_value(x, sort)) for x in comments)

def _get_comment_sorter(link_id, sort):
    from r2.models import CommentSortsCache
    from r2.lib.db.tdb_cassandra import NotFound

    key = sort_comments_key(link_id, sort)
    try:
        sorter = CommentSortsCache._byID(key)._values()
    except NotFound:
        return {}

    # we store these id36ed, but there are still bits of the code that
    # want to deal in integer IDs
    sorter = dict((int(c_id, 36), val)
                  for (c_id, val) in sorter.iteritems())
    return sorter

def link_comments_and_sort(link, sort):
    from r2.models import CommentSortsCache

    # This has grown sort of organically over time. Right now the
    # cache of the comments tree consists in three keys:
    # 1. The comments_key: A tuple of
    #      (cids, comment_tree, depth, num_children)
    #    given:
    #      cids         =:= [comment_id]
    #      comment_tree =:= dict(comment_id -> [comment_id])
    #      depth        =:= dict(comment_id -> int depth)
    #      num_children =:= dict(comment_id -> int num_children)
    # 2. The parent_comments_key =:= dict(comment_id -> parent_id)
    # 3. The comments_sorts keys =:= dict(comment_id36 -> float).
    #    These are represented by a Cassandra model
    #    (CommentSortsCache) rather than a permacache key. One of
    #    these exists for each sort (hot, new, etc)

    timer = g.stats.get_timer('comment_tree.get.%s' % link.comment_tree_version)
    timer.start()

    link_id = link._id
    cache = get_comment_tree(link, timer=timer)
    cids = cache.cids
    tree = cache.tree
    depth = cache.depth
    num_children = cache.num_children
    parents = cache.parents

    # load the sorter
    sorter = _get_comment_sorter(link_id, sort)

    sorter_needed = []
    if cids and not sorter:
        sorter_needed = cids
        g.log.debug("comment_tree.py: sorter (%s) cache miss for Link %s"
                    % (sort, link_id))
        sorter = {}

    sorter_needed = [x for x in cids if x not in sorter]
    if cids and sorter_needed:
        g.log.debug(
            "Error in comment_tree: sorter %r inconsistent (missing %d e.g. %r)"
            % (sort_comments_key(link_id, sort), len(sorter_needed), sorter_needed[:10]))
        if not g.disallow_db_writes:
            update_comment_votes(Comment._byID(sorter_needed, data=True, return_dict=False))

        sorter.update(_comment_sorter_from_cids(sorter_needed, sort))
        timer.intermediate('sort')

    if parents is None:
        g.log.debug("comment_tree.py: parents cache miss for Link %s"
                    % link_id)
        parents = {}
    elif cids and not all(x in parents for x in cids):
        g.log.debug("Error in comment_tree: parents inconsistent for Link %s"
                    % link_id)
        parents = {}

    if not parents and len(cids) > 0:
        with CommentTree.mutation_context(link):
            # reload under lock so the sorter and parents are consistent
            timer.intermediate('lock')
            cache = get_comment_tree(link, timer=timer)
            cache.parents = cache.parent_dict_from_tree(cache.tree)

    timer.stop()

    return (cache.cids, cache.tree, cache.depth, cache.num_children,
            cache.parents, sorter)

def get_comment_tree(link, _update=False, timer=None):
    if timer is None:
        timer = SimpleSillyStub()
    cache = CommentTree.by_link(link)
    timer.intermediate('load')
    if cache and not _update:
        return cache
    with CommentTree.mutation_context(link, timeout=180):
        timer.intermediate('lock')
        cache = CommentTree.rebuild(link)
        timer.intermediate('rebuild')
        # the tree rebuild updated the link's comment count, so schedule it for
        # search reindexing
        from r2.lib.db.queries import changed
        changed([link])
        timer.intermediate('changed')
        return cache

# message conversation functions
def messages_key(user_id):
    return 'message_conversations_' + str(user_id)

def messages_lock_key(user_id):
    return 'message_conversations_lock_' + str(user_id)

def add_message(message):
    # add the message to the author's list and the recipient
    with g.make_lock("message_tree", messages_lock_key(message.author_id)):
        add_message_nolock(message.author_id, message)
    if message.to_id:
        with g.make_lock("message_tree", messages_lock_key(message.to_id)):
            add_message_nolock(message.to_id, message)
    # Messages to a subreddit should end in its inbox. Messages
    # FROM a subreddit (currently, just ban messages) should NOT
    if message.sr_id and not message.from_sr:
        with g.make_lock("modmail_tree", sr_messages_lock_key(message.sr_id)):
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
    rules = [Message.c.first_message == parent._id]
    if c.user_is_admin:
        rules.append(Message.c._spam == (True, False))
        rules.append(Message.c._deleted == (True, False))
    m = Message._query(*rules, data=True)
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

def moderator_messages(sr_ids):
    from r2.models import Subreddit

    srs = Subreddit._byID(sr_ids)
    sr_ids = [sr_id for sr_id, sr in srs.iteritems()
              if sr.is_moderator_with_perms(c.user, 'mail')]

    def multi_load_tree(sr_ids):
        res = {}
        for sr_id in sr_ids:
            trees = subreddit_messages_nocache(srs[sr_id])
            if trees:
                res[sr_id] = trees
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

def _populate(after_id = None, estimate=54301242):
    from r2.models import CommentSortsCache, desc
    from r2.lib.db import tdb_cassandra
    from r2.lib import utils

    # larger has a chance to decrease the number of Cassandra writes,
    # but the probability is low
    chunk_size = 5000

    q = Comment._query(Comment.c._spam==(True,False),
                       Comment.c._deleted==(True,False),
                       sort=desc('_date'))

    if after_id is not None:
        q._after(Comment._byID(after_id))

    q = utils.fetch_things2(q, chunk_size=chunk_size)
    q = utils.progress(q, verbosity=chunk_size, estimate = estimate)

    for chunk in utils.in_chunks(q, chunk_size):
        chunk = filter(lambda x: hasattr(x, 'link_id'), chunk)
        update_comment_votes(chunk, write_consistency_level = tdb_cassandra.CL.ONE)
