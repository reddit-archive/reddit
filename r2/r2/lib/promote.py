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
from r2.models import *

from r2.lib.utils import timefromnow
from r2.lib.memoize import clear_memo, memoize
from r2.lib.db.operators import desc

from datetime import datetime
import random

# time in seconds to retain cached list of promoted links; note that
# expired promotions are cleaned only this often
promoted_memo_lifetime = 60*60
promoted_memo_key = 'cached_promoted_links'

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
    clear_memo(promoted_memo_key)

def unpromote(thing):
    thing.promoted = False
    thing.unpromoted_on = datetime.now(g.tz)
    thing.promote_until = None
    thing._commit()
    clear_memo(promoted_memo_key)

@memoize(promoted_memo_key, time = promoted_memo_lifetime)
def get_promoted_cached():
    """
       Returns all links that are promoted, and cleans up any that are
       ready for automatic unpromotion
    """
    links = Link._query(Link.c.promoted == True,
                        sort = desc('_date'),
                        data = True)

    # figure out which links have expired
    expired_links = set(x for x in links
                        if x.promote_until
                        and x.promote_until < datetime.now(g.tz))
    
    for x in expired_links:
        g.log.debug('Unpromoting "%s"' % x.title)
        unpromote(x)

    return [ x._fullname for x in links if x not in expired_links ]

def get_promoted():
    return ()
    return get_promoted_cached()

def promote_builder_wrapper(alternative_wrapper):
    def wrapper(thing):
        if isinstance(thing, Link) and thing.promoted:
            thing.__class__ = PromotedLink
            w = Wrapped(thing)
            w.rowstyle = 'promoted link'

            return w
        else:
            return alternative_wrapper(thing)
    return wrapper


