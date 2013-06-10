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

from r2.lib.utils import tup


__all__ = ["MessageQueue", "declare_queues"]


class Queues(dict):
    """A container for queue declarations."""
    def __init__(self, queues):
        dict.__init__(self)
        self.__dict__ = self
        self.bindings = set()
        self.declare(queues)

    def __iter__(self):
        for name, queue in self.iteritems():
            if name != "bindings":
                yield queue

    def declare(self, queues):
        for name, queue in queues.iteritems():
            queue.name = name
            queue.bindings = self.bindings
            if queue.bind_to_self:
                queue._bind(name)
        self.update(queues)


class MessageQueue(object):
    """A representation of an AMQP message queue.

    This class is solely intended for use with the Queues class above.

    """
    def __init__(self, durable=True, exclusive=False,
                 auto_delete=False, bind_to_self=False):
        self.durable = durable
        self.exclusive = exclusive
        self.auto_delete = auto_delete
        self.bind_to_self = bind_to_self

    def _bind(self, routing_key):
        self.bindings.add((self.name, routing_key))

    def __lshift__(self, routing_keys):
        """Register bindings from routing keys to this queue."""
        routing_keys = tup(routing_keys)
        for routing_key in routing_keys:
            self._bind(routing_key)


def declare_queues(g):
    queues = Queues({
        "scraper_q": MessageQueue(),
        "newcomments_q": MessageQueue(),
        "commentstree_q": MessageQueue(bind_to_self=True),
        "commentstree_fastlane_q": MessageQueue(bind_to_self=True),
        "vote_link_q": MessageQueue(bind_to_self=True),
        "vote_comment_q": MessageQueue(bind_to_self=True),
        "vote_fastlane_q": MessageQueue(bind_to_self=True),
        "log_q": MessageQueue(bind_to_self=True),
        "cloudsearch_changes": MessageQueue(bind_to_self=True),
        "update_promos_q": MessageQueue(bind_to_self=True),
        "butler_q": MessageQueue(),
    })

    if g.shard_link_vote_queues:
        sharded_vote_queues = {"vote_link_%d_q" % i :
                               MessageQueue(bind_to_self=True)
                               for i in xrange(10)}
        queues.declare(sharded_vote_queues)

    if g.shard_commentstree_queues:
        sharded_commentstree_queues = {"commentstree_%d_q" % i :
                                       MessageQueue(bind_to_self=True)
                                       for i in xrange(10)}
        queues.declare(sharded_commentstree_queues)

    queues.cloudsearch_changes << "search_changes"
    queues.scraper_q << "new_link"
    queues.newcomments_q << "new_comment"
    queues.butler_q << ("new_comment",
                        "usertext_edited")
    return queues
