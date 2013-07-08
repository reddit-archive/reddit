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

from r2.lib.errors import MessageError
from r2.lib.utils import tup, fetch_things2
from r2.lib.filters import websafe
from r2.lib.log import log_text
from r2.models import Account, Message, Report, Subreddit
from r2.models.award import Award
from r2.models.token import AwardClaimToken

from _pylibmc import MemcachedError
from pylons import g

from datetime import datetime, timedelta
from copy import copy

class AdminTools(object):

    def spam(self, things, auto=True, moderator_banned=False,
             banner=None, date=None, train_spam=True, **kw):
        from r2.lib.db import queries

        all_things = tup(things)
        new_things = [x for x in all_things if not x._spam]

        Report.accept(all_things, True)

        for t in all_things:
            if getattr(t, "promoted", None) is not None:
                g.log.debug("Refusing to mark promotion %r as spam" % t)
                continue

            if not t._spam and train_spam:
                note = 'spam'
            elif not t._spam and not train_spam:
                note = 'remove not spam'
            elif t._spam and not train_spam:
                note = 'confirm spam'
            elif t._spam and train_spam:
                note = 'reinforce spam'

            t._spam = True

            if moderator_banned:
                t.verdict = 'mod-removed'
            elif not auto:
                t.verdict = 'admin-removed'

            ban_info = copy(getattr(t, 'ban_info', {}))
            if isinstance(banner, dict):
                ban_info['banner'] = banner[t._fullname]
            else:
                ban_info['banner'] = banner
            ban_info.update(auto=auto,
                            moderator_banned=moderator_banned,
                            banned_at=date or datetime.now(g.tz),
                            **kw)
            ban_info['note'] = note

            t.ban_info = ban_info
            t._commit()

        if not auto:
            self.author_spammer(new_things, True)
            self.set_last_sr_ban(new_things)

        queries.ban(all_things, filtered=auto)

    def unspam(self, things, moderator_unbanned=True, unbanner=None,
               train_spam=True, insert=True):
        from r2.lib.db import queries

        things = tup(things)

        # We want to make unban-all moderately efficient, so when
        # mass-unbanning, we're going to skip the code below on links that
        # are already not banned.  However, when someone manually clicks
        # "approve" on an unbanned link, and there's just one, we want do
        # want to run the code below. That way, the little green checkmark
        # will have the right mouseover details, the reports will be
        # cleared, etc.

        if len(things) > 1:
            things = [x for x in things if x._spam]

        Report.accept(things, False)
        for t in things:
            ban_info = copy(getattr(t, 'ban_info', {}))
            ban_info['unbanned_at'] = datetime.now(g.tz)
            if unbanner:
                ban_info['unbanner'] = unbanner
            if ban_info.get('reset_used', None) == None:
                ban_info['reset_used'] = False
            else:
                ban_info['reset_used'] = True
            t.ban_info = ban_info
            t._spam = False
            if moderator_unbanned:
                t.verdict = 'mod-approved'
            else:
                t.verdict = 'admin-approved'
            t._commit()

        self.author_spammer(things, False)
        self.set_last_sr_ban(things)
        queries.unban(things, insert)
    
    def report(self, thing):
        pass

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

    def engolden(self, account, days):
        account.gold = True

        now = datetime.now(g.display_tz)

        existing_expiration = getattr(account, "gold_expiration", None)
        if existing_expiration is None or existing_expiration < now:
            existing_expiration = now
        account.gold_expiration = existing_expiration + timedelta(days)

        description = "Since " + now.strftime("%B %Y")
        trophy = Award.give_if_needed("reddit_gold", account,
                                     description=description,
                                     url="/gold/about")
        if trophy and trophy.description.endswith("Member Emeritus"):
            trophy.description = description
            trophy._commit()
        account._commit()

        account.friend_rels_cache(_update=True)

    def degolden(self, account, severe=False):

        if severe:
            account.gold_charter = False
            Award.take_away("charter_subscriber", account)

        Award.take_away("reddit_gold", account)
        account.gold = False
        account._commit()

    def admin_list(self):
        return list(g.admins)

    def create_award_claim_code(self, unique_award_id, award_codename,
                                description, url):
        '''Create a one-time-use claim URL for a user to claim a trophy.

        `unique_award_id` - A string that uniquely identifies the kind of
                            Trophy the user would be claiming.
                            See: token.py:AwardClaimToken.uid
        `award_codename` - The codename of the Award the user will claim
        `description` - The description the Trophy will receive
        `url` - The URL the Trophy will receive

        '''
        award = Award._by_codename(award_codename)
        token = AwardClaimToken._new(unique_award_id, award, description, url)
        return token.confirm_url()

admintools = AdminTools()

def cancel_subscription(subscr_id):
    q = Account._query(Account.c.gold_subscr_id == subscr_id, data=True)
    l = list(q)
    if len(l) != 1:
        g.log.warning("Found %d matches for canceled subscription %s"
                      % (len(l), subscr_id))
    for account in l:
        account.gold_subscr_id = None
        account._commit()
        g.log.info("%s canceled their recurring subscription %s" %
                   (account.name, subscr_id))

def all_gold_users():
    q = Account._query(Account.c.gold == True, data=True,
                       sort="_id")
    return fetch_things2(q)

def accountid_from_paypalsubscription(subscr_id):
    if subscr_id is None:
        return None

    q = Account._query(Account.c.gold_subscr_id == subscr_id,
                       data=False)
    l = list(q)
    if l:
        return l[0]._id
    else:
        return None

def update_gold_users(verbose=False):
    now = datetime.now(g.display_tz)
    minimum = None
    count = 0
    expiration_dates = {}

    for account in all_gold_users():
        if not hasattr(account, "gold_expiration"):
            g.log.error("%s has no gold_expiration" % account.name)
            continue

        delta = account.gold_expiration - now
        days_left = delta.days

        hc_key = "gold_expiration_notice-" + account.name

        if days_left < 0:
            if verbose:
                print "%s just expired" % account.name
            admintools.degolden(account)
            send_system_message(account, "Your reddit gold subscription has expired. :(",
               "Your subscription to reddit gold has expired. [Click here for details on how to renew, or to set up an automatically-renewing subscription.](http://www.reddit.com/gold) Or, if you don't want to, please write to us at 912@reddit.com and tell us where we let you down, so we can work on fixing the problem.")
            continue

        count += 1

        if verbose:
            exp_date = account.gold_expiration.strftime('%Y-%m-%d')
            expiration_dates.setdefault(exp_date, 0)
            expiration_dates[exp_date] += 1

#           print "%s expires in %d days" % (account.name, days_left)
            if minimum is None or delta < minimum[0]:
                minimum = (delta, account)

        if days_left <= 3 and not g.hardcache.get(hc_key):
            if verbose:
                print "%s expires soon: %s days" % (account.name, days_left)
            if getattr(account, "gold_subscr_id", None):
                if verbose:
                    print "Not sending notice to %s (%s)" % (account.name,
                                                     account.gold_subscr_id)
            else:
                if verbose:
                    print "Sending notice to %s" % account.name
                g.hardcache.set(hc_key, True, 86400 * 10)
                send_system_message(account, "Your reddit gold subscription is about to expire!",
                                    "Your subscription to reddit gold will be expiring soon. [Click here for details on how to renew, or to set up an automatically-renewing subscription.](http://www.reddit.com/gold) Or, if you don't want to, please write to us at 912@reddit.com and tell us where we let you down, so we can work on fixing the problem.")

    if verbose:
        for exp_date in sorted(expiration_dates.keys()):
            num_expiring = expiration_dates[exp_date]
            print '%s %3d %s' % (exp_date, num_expiring, '*' * num_expiring)
        print "%s goldmembers" % count
        if minimum is None:
            print "Nobody found."
        else:
            delta, account = minimum
            print "Next expiration is %s, in %d days" % (account.name, delta.days)

def admin_ratelimit(user):
    return True

def is_banned_IP(ip):
    return False

def is_banned_domain(dom):
    return None

def is_shamed_domain(dom):
    return False, None, None

def valid_thing(v, karma, *a, **kw):
    return not v._thing1._spam

def valid_user(v, sr, karma, *a, **kw):
    return True

# Returns whether this person is being suspicious
def login_throttle(username, wrong_password):
    return False

def apply_updates(user):
    pass

def update_score(obj, up_change, down_change, vote, old_valid_thing):
     obj._incr('_ups',   up_change)
     obj._incr('_downs', down_change)

def compute_votes(wrapper, item):
    wrapper.upvotes   = item._ups
    wrapper.downvotes = item._downs

def ip_span(ip):
    ip = websafe(ip)
    return '<!-- %s -->' % ip

def filter_quotas(unfiltered):
    now = datetime.now(g.tz)

    baskets = {
        'hour':  [],
        'day':   [],
        'week':  [],
        'month': [],
        }

    new_quotas = []
    quotas_changed = False

    for item in unfiltered:
        delta = now - item._date

        age = delta.days * 86400 + delta.seconds

        # First, select a basket or abort if item is too old
        if age < 3600:
            basket = 'hour'
        elif age < 86400:
            basket = 'day'
        elif age < 7 * 86400:
            basket = 'week'
        elif age < 30 * 86400:
            basket = 'month'
        else:
            quotas_changed = True
            continue

        verdict = getattr(item, "verdict", None)
        approved = verdict and verdict in (
            'admin-approved', 'mod-approved')

        # Then, make sure it's worthy of quota-clogging
        if item._spam:
            pass
        elif item._deleted:
            pass
        elif item._score <= 0:
            pass
        elif age < 86400 and item._score <= g.QUOTA_THRESHOLD and not approved:
            pass
        else:
            quotas_changed = True
            continue

        baskets[basket].append(item)
        new_quotas.append(item._fullname)

    if quotas_changed:
        return baskets, new_quotas
    else:
        return baskets, None


def send_system_message(user, subject, body, system_user=None,
                        distinguished='admin', repliable=False):
    from r2.lib.db import queries

    if system_user is None:
        system_user = Account.system_user()
    if not system_user:
        g.log.warning("Can't send system message "
                      "- invalid system_user or g.system_user setting")
        return

    item, inbox_rel = Message._new(system_user, user, subject, body,
                                   ip='0.0.0.0')
    item.distinguished = distinguished
    item.repliable = repliable
    item._commit()

    try:
        queries.new_message(item, inbox_rel)
    except MemcachedError:
        raise MessageError('reddit_inbox')


try:
    from r2admin.models.admintools import *
except ImportError:
    pass
