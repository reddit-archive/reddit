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

from threading import local
from datetime import datetime
import os
import sys
import time
import errno
import socket

from amqplib import client_0_8 as amqp

from r2.lib.cache import LocalCache
from pylons import g

amqp_host = g.amqp_host
amqp_user = g.amqp_user
amqp_pass = g.amqp_pass
log = g.log
amqp_virtual_host = g.amqp_virtual_host

connection = None
channel = local()
have_init = False

#there are two ways of interacting with this module: add_item and
#handle_items. add_item should only be called from the utils.worker
#thread since it might block for an arbitrary amount of time while
#trying to get a connection amqp.

def get_connection():
    global connection
    global have_init

    while not connection:
        try:
            connection = amqp.Connection(host = amqp_host,
                                         userid = amqp_user,
                                         password = amqp_pass,
                                         virtual_host = amqp_virtual_host,
                                         insist = False)
        except (socket.error, IOError):
            print 'error connecting to amqp'
            time.sleep(1)

    #don't run init_queue until someone actually needs it. this allows
    #the app server to start and serve most pages if amqp isn't
    #running
    if not have_init:
        init_queue()
        have_init = True

def get_channel(reconnect = False):
    global connection
    global channel
    global log

    # Periodic (and increasing with uptime) errors appearing when
    # connection object is still present, but appears to have been
    # closed.  This checks that the the connection is still open.
    if connection and connection.channels is None:
        log.error("Error: amqp.py, connection object with no available channels.  Reconnecting...")
        connection = None

    if not connection or reconnect:
        channel.chan = None
        connection = None
        get_connection()

    if not getattr(channel, 'chan', None):
        channel.chan = connection.channel()
    return channel.chan

def init_queue():
    from r2.models import admintools

    exchange = 'reddit_exchange'

    chan = get_channel()

    #we'll have one exchange for now
    chan.exchange_declare(exchange=exchange,
                          type='direct',
                          durable=True,
                          auto_delete=False)

    #prec_links queue
    chan.queue_declare(queue='prec_links',
                       durable=True,
                       exclusive=False,
                       auto_delete=False)
    chan.queue_bind(routing_key='prec_links',
                    queue='prec_links',
                    exchange=exchange)

    chan.queue_declare(queue='scraper_q',
                       durable=True,
                       exclusive=False,
                       auto_delete=False)

    chan.queue_declare(queue='searchchanges_q',
                       durable=True,
                       exclusive=False,
                       auto_delete=False)

    # new_link
    chan.queue_bind(routing_key='new_link',
                    queue='scraper_q',
                    exchange=exchange)
    chan.queue_bind(routing_key='new_link',
                    queue='searchchanges_q',
                    exchange=exchange)

    # new_subreddit
    chan.queue_bind(routing_key='new_subreddit',
                    queue='searchchanges_q',
                    exchange=exchange)

    # new_comment (nothing here for now)

    # while new items will be put here automatically, we also need a
    # way to specify that the item has changed by hand
    chan.queue_bind(routing_key='searchchanges_q',
                    queue='searchchanges_q',
                    exchange=exchange)

    admintools.admin_queues(chan, exchange)


def add_item(routing_key, body, message_id = None):
    """adds an item onto a queue. If the connection to amqp is lost it
    will try to reconnect and then call itself again."""
    if not amqp_host:
        print "Ignoring amqp message %r to %r" % (body, routing_key)
        return

    chan = get_channel()
    msg = amqp.Message(body,
                       timestamp = datetime.now(),
                       delivery_mode = 2)
    if message_id:
        msg.properties['message_id'] = message_id

    try:
        chan.basic_publish(msg,
                           exchange = 'reddit_exchange',
                           routing_key = routing_key)
    except Exception as e:
        if e.errno == errno.EPIPE:
            get_channel(True)
            add_item(routing_key, body, message_id)
        else:
            raise

def handle_items(queue, callback, ack = True, limit = 1, drain = False):
    """Call callback() on every item in a particular queue. If the
       connection to the queue is lost, it will die. Intended to be
       used as a long-running process."""

    # debuffer stdout so that logging comes through more real-time
    sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)

    chan = get_channel()
    while True:
        msg = chan.basic_get(queue)
        if not msg and drain:
            return
        elif not msg:
            time.sleep(1)
            continue

        items = []
        #reset the local cache
        g.cache.caches = (LocalCache(),) + g.cache.caches[1:]

        while msg:
            items.append(msg)
            if len(items) >= limit:
                break # the innermost loop only
            msg = chan.basic_get(queue)

        callback(items)

        if ack:
            for item in items:
                chan.basic_ack(item.delivery_tag)

def empty_queue(queue):
    """debug function to completely erase the contents of a queue"""
    chan = get_channel()
    chan.queue_purge(queue)
