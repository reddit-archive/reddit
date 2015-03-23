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

from pylons import g, c
from itertools import chain
from r2.lib.utils import SimpleSillyStub, tup, to36
from r2.lib.db.sorts import epoch_seconds
from r2.lib.cache import sgm
from r2.models.comment_tree import CommentTree
from r2.models.link import Comment, Link

MESSAGE_TREE_SIZE_LIMIT = 15000

def comments_key(link_id):
    return 'comments_' + str(link_id)

def lock_key(link_id):
    return 'comment_lock_' + str(link_id)

def parent_comments_key(link_id):
    return 'comments_parents_' + str(link_id)


def _get_sort_value(comment, sort, link=None, children=None):
    if sort == "_date":
        return epoch_seconds(comment._date)
    if sort == '_qa':
        # Responder is usually the OP, but there could be support for adding
        # other answerers in the future.
        responder_ids = link.responder_ids
        return comment._qa(children, responder_ids)
    return getattr(comment, sort)

def add_comments(comments):
    links = Link._byID([com.link_id for com in tup(comments)], data=True)
    comments = tup(comments)

    link_map = {}
    for com in comments:
        link_map.setdefault(com.link_id, []).append(com)

    for link_id, coms in link_map.iteritems():
        link = links[link_id]
        add_comments = [comment for comment in coms if not comment._deleted]
        delete_comments = (comment for comment in coms if comment._deleted)
        timer = g.stats.get_timer('comment_tree.add.%s'
                                  % link.comment_tree_version)
        timer.start()
        try:
            with CommentTree.mutation_context(link):
                timer.intermediate('lock')
                cache = get_comment_tree(link, timer=timer)
                timer.intermediate('get')
                if add_comments:
                    cache.add_comments(add_comments)
                for comment in delete_comments:
                    cache.delete_comment(comment, link)
                timer.intermediate('update')
        except:
            g.log.exception(
                'add_comments_nolock failed for link %s, recomputing tree',
                link_id)

            # calculate it from scratch
            get_comment_tree(link, _update=True, timer=timer)
        timer.stop()
        update_comment_votes(coms)

def update_comment_votes(comments):
    from r2.models import CommentScoresByLink

    comments = tup(comments)

    link_map = {}
    for com in comments:
        link_map.setdefault(com.link_id, []).append(com)
    all_links = Link._byID(link_map.keys(), data=True)

    comment_trees = {}
    for link in all_links.values():
        comment_trees[link._id] = get_comment_tree(link)

    for link_id, coms in link_map.iteritems():
        link = all_links[link_id]
        for sort in ("_controversy", "_hot", "_confidence", "_score", "_date",
                     "_qa"):
            cid_tree = comment_trees[link_id].tree
            scores_by_comment = _comment_sorter_from_cids(
                coms, sort, link, cid_tree, by_36=True)
            CommentScoresByLink.set_scores(link, sort, scores_by_comment)


def _comment_sorter_from_cids(comments, sort, link, cid_tree, by_36=False):
    """Retrieve sort values for comments.

    Arguments:

    * comments -- an iterable of Comments to retrieve sort values for.
    * sort -- a string representing the type of sort to use.
    * cid_tree -- a mapping from parent id to children ids, as created by
      CommentTree.
    * by_36 -- a boolean indicating if the resultant map keys off of base 36
      ids instead of integer ids.

    Returns a dictionary from cid to a numeric sort value.
    """
    # The Q&A sort requires extra information about surrounding comments.  It's
    # more efficient to gather it up here instead of in the guts of the comment
    # sort, but we don't want to do that for sort types that don't need it.
    if sort == '_qa':
        # An OP response will change the sort value for its parent, so we need
        # to process the parent, too.
        parent_cids = []
        responder_ids = link.responder_ids
        for c in comments:
            if c.author_id in responder_ids and c.parent_id:
                parent_cids.append(c.parent_id)
        parent_comments = Comment._byID(parent_cids, data=True,
                return_dict=False)
        comments.extend(parent_comments)

        # Fetch the comments in batch to avoid a bunch of separate calls down
        # the line.
        all_child_cids = []
        for c in comments:
            child_cids = cid_tree.get(c._id, None)
            if child_cids:
                all_child_cids.extend(child_cids)
        all_child_comments = Comment._byID(all_child_cids, data=True)

    comment_sorter = {}
    for comment in comments:
        if sort == '_qa':
            child_cids = cid_tree.get(comment._id, ())
            child_comments = (all_child_comments[cid] for cid in child_cids)
            sort_value = _get_sort_value(comment, sort, link, child_comments)
        else:
            sort_value = _get_sort_value(comment, sort)
        if by_36:
            id = comment._id36
        else:
            id = comment._id
        comment_sorter[id] = sort_value

    return comment_sorter

def _get_comment_sorter(link, sort):
    """Retrieve cached sort values for all comments on a post.

    Arguments:

    * link_id -- id of the Link containing the comments.
    * sort -- a string indicating the attribute on the comments to use for
      generating sort values.

    Returns a dictionary from cid to a numeric sort value.
    """
    from r2.models import CommentScoresByLink

    sorter = CommentScoresByLink.get_scores(link, sort)

    # we store these id36ed, but there are still bits of the code that
    # want to deal in integer IDs
    sorter = dict((int(c_id, 36), val)
                  for (c_id, val) in sorter.iteritems())
    return sorter

def link_comments_and_sort(link, sort):
    """Fetch and sort the comments on a post.

    Arguments:

    * link -- the Link whose comments we want to sort.
    * sort -- a string indicating the attribute on the comments to use for
      generating sort values.

    Returns a tuple in the form (cids, cid_tree, depth, parents, sorter), where
    the values are as follows:

    * cids -- a list of the ids of all comments in the thread.
    * cid_tree -- a dictionary from parent cid to children cids.
    * depth -- a dictionary from cid to the depth that comment resides in the
      tree. A top-level comment has depth 0.
    * parents -- a dictionary from child cid to parent cid.
    * sorter -- a dictionary from cid to a numeric value to be used for
      sorting.
    """

    # This has grown sort of organically over time. Right now the
    # cache of the comments tree consists in three keys:
    # 1. The comments_key: A tuple of
    #      (cids, comment_tree, depth)
    #    given:
    #      cids         =:= [comment_id]
    #      comment_tree =:= dict(comment_id -> [comment_id])
    #      depth        =:= dict(comment_id -> int depth)
    # 2. The parent_comments_key =:= dict(comment_id -> parent_id)
    # 3. The comments_sorts keys =:= dict(comment_id36 -> float).
    #    These are represented by a Cassandra model
    #    (CommentScoresByLink) rather than a permacache key. One of
    #    these exists for each sort (hot, new, etc)

    timer = g.stats.get_timer('comment_tree.get.%s' % link.comment_tree_version)
    timer.start()

    cache = get_comment_tree(link, timer=timer)
    cids = cache.cids
    tree = cache.tree
    depth = cache.depth
    parents = cache.parents

    # load the sorter
    sorter = _get_comment_sorter(link, sort)

    # find comments for which the sort values weren't in the cache
    sorter_needed = []
    if cids and not sorter:
        sorter_needed = cids
        g.log.debug("comment_tree.py: sorter %s cache miss for %s", sort, link)
        sorter = {}

    sorter_needed = [x for x in cids if x not in sorter]
    if cids and sorter_needed:
        g.log.debug(
            "Error in comment_tree: sorter %s/%s inconsistent (missing %d e.g. %r)"
            % (link, sort, len(sorter_needed), sorter_needed[:10]))
        if not g.disallow_db_writes:
            update_comment_votes(Comment._byID(sorter_needed, data=True, return_dict=False))

        # The Q&A sort needs access to attributes the others don't, so save the
        # extra lookups if we can.
        data_needed = (sort == '_qa')
        comments = Comment._byID(sorter_needed, data=data_needed, return_dict=False)
        sorter.update(_comment_sorter_from_cids(comments, sort, link, tree))
        timer.intermediate('sort')

    if parents is None:
        g.log.debug("comment_tree.py: parents cache miss for %s", link)
        parents = {}
    elif cids and not all(x in parents for x in cids):
        g.log.debug("Error in comment_tree: parents inconsistent for %s", link)
        parents = {}

    if not parents and len(cids) > 0:
        with CommentTree.mutation_context(link):
            # reload under lock so the sorter and parents are consistent
            timer.intermediate('lock')
            cache = get_comment_tree(link, timer=timer)
            cache.parents = cache.parent_dict_from_tree(cache.tree)

    timer.stop()

    return (cache.cids, cache.tree, cache.depth, cache.parents, sorter)

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
        link.update_search_index()
        timer.intermediate('update_search_index')
        return cache

# message conversation functions
def messages_key(user_id):
    return 'message_conversations_' + str(user_id)

def messages_lock_key(user_id):
    return 'message_conversations_lock_' + str(user_id)

def add_message(message, update_recipient=True, update_modmail=True,
                add_to_user=None):
    with g.make_lock("message_tree", messages_lock_key(message.author_id)):
        add_message_nolock(message.author_id, message)

    if (update_recipient and message.to_id and
            message.to_id != message.author_id):
        with g.make_lock("message_tree", messages_lock_key(message.to_id)):
            add_message_nolock(message.to_id, message)

    if update_modmail and message.sr_id:
        with g.make_lock("modmail_tree", sr_messages_lock_key(message.sr_id)):
            add_sr_message_nolock(message.sr_id, message)

    if add_to_user and add_to_user._id != message.to_id:
        with g.make_lock("message_tree", messages_lock_key(add_to_user._id)):
            add_message_nolock(add_to_user._id, message)

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

    # If we have too many messages in the tree, drop the oldest
    # conversation to avoid the permacache size limit
    tree_size = len(trees) + sum(len(convo[1]) for convo in trees)

    if tree_size > MESSAGE_TREE_SIZE_LIMIT:
        del trees[-1]

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
    from r2.models import desc
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
        update_comment_votes(chunk)
