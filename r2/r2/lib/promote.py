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
# All portions of the code written by CondeNet are Copyright (c) 2006-2008
# CondeNet, Inc. All Rights Reserved.
################################################################################
from __future__ import with_statement

from r2.models import *
from r2.lib.memoize import memoize, clear_memo

from datetime import datetime

promoted_memo_lifetime = 30
promoted_memo_key = 'cached_promoted_links'
promoted_lock_key = 'cached_promoted_links_lock'

def promote(thing, subscribers_only = False, promote_until = None,
            disable_comments = False):

    thing.promoted = True
    thing.promoted_on = datetime.now(g.tz)

    if c.user:
        thing.promoted_by = c.user._id

    if promote_until:
        thing.promote_until = promote_until

    if disable_comments:
        thing.disable_comments = True

    if subscribers_only:
        thing.promoted_subscribersonly = True

    thing._commit()

    with g.make_lock(promoted_lock_key):
        promoted = get_promoted_direct()
        promoted.append(thing._fullname)
        set_promoted(promoted)

def unpromote(thing):
    thing.promoted = False
    thing.unpromoted_on = datetime.now(g.tz)
    thing.promote_until = None
    thing._commit()

    with g.make_lock(promoted_lock_key):
        promoted = [ x for x in get_promoted_direct()
                     if x != thing._fullname ]

        set_promoted(promoted)

def set_promoted(link_names):
    # caller is assumed to execute me inside a lock if necessary
    g.permacache.set(promoted_memo_key, link_names)

    clear_memo(promoted_memo_key)

@memoize(promoted_memo_key, time = promoted_memo_lifetime)
def get_promoted():
    # does not lock the list to return it, so (slightly) stale data
    # will be returned if called during an update rather than blocking
    return get_promoted_direct()

def get_promoted_direct():
    return g.permacache.get(promoted_memo_key, [])

def expire_promoted():
    """
        To be called periodically (e.g. by `cron') to clean up
        promoted links past their expiration date
    """
    with g.make_lock(promoted_lock_key):
        link_names = set(get_promoted_direct())
        links = Link._by_fullname(link_names, data=True, return_dict = False)

        link_names = []
        expired_names = []

        for x in links:
            if (not x.promoted
                or x.promote_until and x.promote_until < datetime.now(g.tz)):
                g.log.info('Unpromoting %s' % x._fullname)
                unpromote(x)
                expired_names.append(x._fullname)
            else:
                link_names.append(x._fullname)

        set_promoted(link_names)

    return expired_names

def get_promoted_slow():
    # to be used only by a human at a terminal
    with g.make_lock(promoted_lock_key):
        links = Link._query(Link.c.promoted == True,
                            data = True)
        link_names = [ x._fullname for x in links ]

        set_promoted(link_names)

    return link_names

#deprecated
def promote_builder_wrapper(alternative_wrapper):
    def wrapper(thing):
        if isinstance(thing, Link) and thing.promoted:
            w = Wrapped(thing)
            w.render_class = PromotedLink
            w.rowstyle = 'promoted link'

            return w
        else:
            return alternative_wrapper(thing)
    return wrapper


