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
class QueueMap(object):
    """Represents a set of queues and bindings in a single exchange"""
    def __init__(self, exchange, chan, exchange_type='direct',
                 durable=True, auto_delete=False):
        self.exchange = exchange
        self.chan = chan

        self._exchange(exchange,exchange_type=exchange_type,
                       durable=durable, auto_delete=auto_delete)

    def _exchange(self, name, exchange_type, durable, auto_delete):
        self.chan.exchange_declare(exchange=name,
                                   type=exchange_type,
                                   durable=durable,
                                   auto_delete=auto_delete)

    def _q(self, name, durable=True, exclusive=False,
           auto_delete=False, self_refer=False):
        self.chan.queue_declare(queue=name,
                                durable=durable,
                                exclusive=exclusive,
                                auto_delete=auto_delete)
        if self_refer:
            # make a routing key with the same name as the queue to
            # allow things to be placed directly in it
            self._bind(name, name)

    def _bind(self, rk, q):
        self.chan.queue_bind(routing_key=rk,
                             queue=q,
                             exchange=self.exchange)

    def init(self):
        self.queues()
        self.bindings()

    def queues(self):
        raise NotImplementedError

    def bindings(self):
        raise NotImplementedError


class RedditQueueMap(QueueMap):
    def queues(self):
        self._q('scraper_q')
        self._q('newcomments_q')
        self._q('commentstree_q')
        # this isn't in use until the spam_q plumbing is
        #self._q('newpage_q')
        self._q('register_vote_q', self_refer=True)
        self._q('vote_link_q', self_refer=True)
        self._q('vote_comment_q', self_refer=True)
        self._q('log_q', self_refer=True)
        self._q('usage_q', self_refer=True, durable=False)

        self._q('cloudsearch_changes', self_refer=True)
        self._bind('search_changes', 'cloudsearch_changes')

    def bindings(self):
        self.newlink_bindings()
        self.newcomment_bindings()
        self.newsubreddit_bindings()

    def newlink_bindings(self):
        self._bind('new_link', 'scraper_q')

        # this isn't in use until the spam_q plumbing is
        #self._bind('new_link', 'newpage_q')

    def newcomment_bindings(self):
        self._bind('new_comment', 'newcomments_q')
        self._bind('new_comment', 'commentstree_q')

    def newsubreddit_bindings(self):
        pass

try:
    from r2admin.lib.adminqueues import *
except ImportError:
    pass
