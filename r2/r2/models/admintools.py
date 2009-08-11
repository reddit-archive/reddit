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
from r2.lib.utils import tup
from r2.models import Report, Account
from r2.models.thing_changes import changed
from r2.lib.db import queries

from pylons import g

from datetime import datetime
from copy import copy

class AdminTools(object):
    def spam(self, things, auto, moderator_banned, banner, date = None, **kw):
        Report.accept(things, True)
        things = [ x for x in tup(things) if not x._spam ]
        for t in things:
            t._spam = True
            ban_info = copy(getattr(t, 'ban_info', {}))
            ban_info.update(auto = auto,
                            moderator_banned = moderator_banned,
                            banner = banner,
                            banned_at = date or datetime.now(g.tz),
                            **kw)
            t.ban_info = ban_info
            t._commit()
            changed(t)
        self.author_spammer(things, True)
        queries.ban(things)

    def unspam(self, things, unbanner = None):
        Report.accept(things, False)
        things = [ x for x in tup(things) if x._spam ]
        for t in things:
            ban_info = copy(getattr(t, 'ban_info', {}))
            ban_info['unbanned_at'] = datetime.now(g.tz)
            if unbanner:
                ban_info['unbanner'] = unbanner
            t.ban_info = ban_info
            t._spam = False
            t._commit()
            changed(t)
        self.author_spammer(things, False)
        queries.unban(things)

    def author_spammer(self, things, spam):
        """incr/decr the 'spammer' field for the author of every
           passed thing"""
        by_aid = {}
        for thing in things:
            if hasattr(thing, 'author_id'):
                by_aid.setdefault(thing.author_id, []).append(thing)

        if by_aid:
            authors = Account._byID(by_aid.keys(), data=True, return_dict=True)

            for aid, author_things in by_aid.iteritems():
                author = authors[aid]
                author._incr('spammer', len(author_things) if spam else -len(author_things))

admintools = AdminTools()

def is_banned_IP(ip):
    return False

def is_banned_domain(dom):
    return False

def valid_thing(v, karma):
    return not v._thing1._spam

def valid_user(v, sr, karma):
    return True

def update_score(obj, up_change, down_change, new_valid_thing, old_valid_thing):
     obj._incr('_ups',   up_change)
     obj._incr('_downs', down_change)

def compute_votes(wrapper, item):
    wrapper.upvotes   = item._ups
    wrapper.downvotes = item._downs


try:
    from r2admin.models.admintools import *
except ImportError:
    pass
