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
from r2.lib.utils import tup
from r2.lib.filters import websafe
from r2.lib.log import log_text
from r2.models import Report, Account

from pylons import g

from datetime import datetime
from copy import copy

class AdminTools(object):

    def spam(self, things, auto=True, moderator_banned=False,
             banner=None, date = None, **kw):
        from r2.lib.db import queries

        things = [x for x in tup(things) if not x._spam]
        Report.accept(things, True)
        for t in things:
            t._spam = True
            ban_info = copy(getattr(t, 'ban_info', {}))
            ban_info.update(auto = auto,
                            moderator_banned = moderator_banned,
                            banned_at = date or datetime.now(g.tz),
                            **kw)

            if isinstance(banner, dict):
                ban_info['banner'] = banner[t._fullname]
            else:
                ban_info['banner'] = banner

            t.ban_info = ban_info
            t._commit()

        if not auto:
            self.author_spammer(things, True)
            self.set_last_sr_ban(things)

        queries.ban(things)

    def unspam(self, things, unbanner = None):
        from r2.lib.db import queries

        things = [x for x in tup(things) if x._spam]
        Report.accept(things, False)
        for t in things:
            ban_info = copy(getattr(t, 'ban_info', {}))
            ban_info['unbanned_at'] = datetime.now(g.tz)
            if unbanner:
                ban_info['unbanner'] = unbanner
            t.ban_info = ban_info
            t._spam = False
            t._commit()

        # auto is always False for unbans
        self.author_spammer(things, False)
        self.set_last_sr_ban(things)

        queries.unban(things)

    def author_spammer(self, things, spam):
        """incr/decr the 'spammer' field for the author of every
           passed thing"""
        by_aid = {}
        for thing in things:
            if (hasattr(thing, 'author_id')
                and not getattr(thing, 'ban_info', {}).get('auto',True)):
                # only decrement 'spammer' for items that were not
                # autobanned
                by_aid.setdefault(thing.author_id, []).append(thing)

        if by_aid:
            authors = Account._byID(by_aid.keys(), data=True, return_dict=True)

            for aid, author_things in by_aid.iteritems():
                author = authors[aid]
                author._incr('spammer', len(author_things) if spam else -len(author_things))

    def set_last_sr_ban(self, things):
        by_srid = {}
        for thing in things:
            if getattr(thing, 'sr_id', None) is not None:
                by_srid.setdefault(thing.sr_id, []).append(thing)

        if by_srid:
            srs = Subreddit._byID(by_srid.keys(), data=True, return_dict=True)
            for sr_id, sr_things in by_srid.iteritems():
                sr = srs[sr_id]

                sr.last_mod_action = datetime.now(g.tz)
                sr._commit()
                sr._incr('mod_actions', len(sr_things))


admintools = AdminTools()

def is_banned_IP(ip):
    return False

def is_banned_domain(dom):
    return None

def valid_thing(v, karma):
    return not v._thing1._spam

def valid_user(v, sr, karma):
    return True

# Returns whether this person is being suspicious
def login_throttle(username, wrong_password):
    return False

def apply_updates(user):
    pass

def update_score(obj, up_change, down_change, new_valid_thing, old_valid_thing):
     obj._incr('_ups',   up_change)
     obj._incr('_downs', down_change)

def compute_votes(wrapper, item):
    wrapper.upvotes   = item._ups
    wrapper.downvotes = item._downs

def ip_span(ip):
    ip = websafe(ip)
    return '<!-- %s -->' % ip

try:
    from r2admin.models.admintools import *
except ImportError:
    pass
