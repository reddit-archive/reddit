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
from __future__ import with_statement

from r2.models import *
from r2.lib import authorize
from r2.lib import emailer, filters
from r2.lib.memoize import memoize
from r2.lib.template_helpers import get_domain
from r2.lib.utils import Enum
from pylons import g, c
from datetime import datetime, timedelta
import random

promoted_memo_lifetime = 30
promoted_memo_key = 'cached_promoted_links2'
promoted_lock_key = 'cached_promoted_links_lock2'

STATUS = Enum("unpaid", "unseen", "accepted", "rejected",
              "pending", "promoted", "finished")

PromoteSR = 'promos'
try:
    PromoteSR = Subreddit._new(name = PromoteSR,
                               title = "promoted links",
                               author_id = -1,
                               type = "public", 
                               ip = '0.0.0.0')
except SubredditExists:
    PromoteSR = Subreddit._by_name(PromoteSR)

def promo_traffic_url(l):
    domain = get_domain(cname = False, subreddit = False)
    return "http://%s/traffic/%s/" % (domain, l._id36)

def promo_edit_url(l):
    domain = get_domain(cname = False, subreddit = False)
    return "http://%s/promoted/edit_promo/%s" % (domain, l._id36)

# These could be done with relationships, but that seeks overkill as
# we never query based on user and only check per-thing
def is_traffic_viewer(thing, user):
    return (c.user_is_sponsor or user._id == thing.author_id or
            user._id in getattr(thing, "promo_traffic_viewers", set()))

def add_traffic_viewer(thing, user):
    viewers = getattr(thing, "promo_traffic_viewers", set()).copy()
    if user._id not in viewers:
        viewers.add(user._id)
        thing.promo_traffic_viewers = viewers
        thing._commit()
        return True
    return False

def rm_traffic_viewer(thing, user):
    viewers = getattr(thing, "promo_traffic_viewers", set()).copy()
    if user._id in viewers:
        viewers.remove(user._id)
        thing.promo_traffic_viewers = viewers
        thing._commit()
        return True
    return False

def traffic_viewers(thing):
    return sorted(getattr(thing, "promo_traffic_viewers", set()))

# logging routine for keeping track of diffs
def promotion_log(thing, text, commit = False):
    """
    For logging all sorts of things
    """
    name = c.user.name if c.user_is_loggedin else "<MAGIC>"
    log = list(getattr(thing, "promotion_log", []))
    now = datetime.now(g.tz).strftime("%Y-%m-%d %H:%M:%S")
    text = "[%s: %s] %s" % (name, now, text)
    log.append(text)
    # copy (and fix encoding) to make _dirty
    thing.promotion_log = map(filters._force_utf8, log)
    if commit:
        thing._commit()
    return text
    
def new_promotion(title, url, user, ip, promote_start, promote_until, bid,
                  disable_comments = False,
                  max_clicks = None, max_views = None):
    """
    Creates a new promotion with the provided title, etc, and sets it
    status to be 'unpaid'.
    """
    l = Link._submit(title, url, user, PromoteSR, ip)
    l.promoted = True
    l.promote_until = None
    l.promote_status = STATUS.unpaid
    l.promote_trans_id = 0
    l.promote_bid    = bid
    l.maximum_clicks = max_clicks
    l.maximum_views  = max_views
    l.disable_comments = disable_comments
    update_promo_dates(l, promote_start, promote_until)
    promotion_log(l, "promotion created")
    l._commit()
    # the user has posted a promotion, so enable the promote menu unless
    # they have already opted out
    if user.pref_show_promote is not False:
        user.pref_show_promote = True
        user._commit()
    emailer.new_promo(l)
    return l

def update_promo_dates(thing, start_date, end_date, commit = True):
    if thing and thing.promote_status < STATUS.pending or c.user_is_admin:
        if (thing._date != start_date or
            thing.promote_until != end_date):
            promotion_log(thing, "duration updated (was %s -> %s)" %
                          (thing._date, thing.promote_until))
            thing._date         = start_date
            thing.promote_until = end_date
            PromoteDates.update(thing, start_date, end_date)
            if commit:
                thing._commit()
        return True
    return False

def update_promo_data(thing, title, url, commit = True):
    if thing and (thing.url != url or thing.title != title):
        if thing.title != title:
            promotion_log(thing, "title updated (was '%s')" %
                          thing.title)
        if thing.url != url:
            promotion_log(thing, "url updated (was '%s')" %
                          thing.url)
        old_url = thing.url
        thing.url = url
        thing.title = title
        if not c.user_is_sponsor:
            unapproved_promo(thing)
        thing.update_url_cache(old_url)
        if commit:
            thing._commit()
        return True
    return False

def refund_promo(thing, user, refund):
    cur_refund = getattr(thing, "promo_refund", 0)
    refund = min(refund, thing.promote_bid - cur_refund)
    if refund > 0:
        thing.promo_refund = cur_refund + refund
        if authorize.refund_transaction(refund, user, thing.promote_trans_id):
            promotion_log(thing, "payment update: refunded '%.2f'" % refund)
        else:
            promotion_log(thing, "payment update: refund failed")
        if thing.promote_status in (STATUS.promoted, STATUS.finished):
            PromoteDates.update_bid(thing)
        thing._commit()

def auth_paid_promo(thing, user, pay_id, bid):
    """
    promotes a promotion from 'unpaid' to 'unseen'.  
    
    In the case that bid already exists on the current promotion, the
    previous transaction is voided and repalced with the new bid.
    """
    if thing.promote_status == STATUS.finished:
        return
    elif (thing.promote_status > STATUS.unpaid and
          thing.promote_trans_id):
        # void the existing transaction
        authorize.void_transaction(user, thing.promote_trans_id)

    # create a new transaction and update the bid
    trans_id = authorize.auth_transaction(bid, user, pay_id, thing)
    thing.promote_bid = bid
    
    if trans_id is not None and int(trans_id) != 0:
        # we won't reset to unseen if already approved and the payment went ok
        promotion_log(thing, "updated payment and/or bid: SUCCESS (id: %s)"
                      % trans_id)
        if trans_id < 0:
            promotion_log(thing, "FREEBIE")
        thing.promote_status = max(thing.promote_status, STATUS.unseen)
        thing.promote_trans_id = trans_id
    else:
        # something bad happend.  
        promotion_log(thing, "updated payment and/or bid: FAILED")    
        thing.promore_status = STATUS.unpaid
        thing.promote_trans_id = 0
    thing._commit()

    emailer.promo_bid(thing)
    PromoteDates.update_bid(thing)
    return bool(trans_id)

    
def unapproved_promo(thing):
    """
    revert status of a promoted link to unseen.

    NOTE: if the promotion is live, this has the side effect of
    bumping it from the live queue pending an admin's intervention to
    put it back in place.
    """
    # only reinforce pending if it hasn't been seen yet.
    if STATUS.unseen < thing.promote_status < STATUS.finished:
        promotion_log(thing, "status update: unapproved")    
        unpromote(thing, status = STATUS.unseen)

def accept_promo(thing):
    """
    Accept promotion and set its status as accepted if not already
    charged, else pending.
    """
    if thing.promote_status < STATUS.pending:
        bid = Bid.one(thing.promote_trans_id)
        if bid.status == Bid.STATUS.CHARGE:
            thing.promote_status = STATUS.pending
            # repromote if already promoted before
            if hasattr(thing, "promoted_on"):
                promote(thing)
            else:
                emailer.queue_promo(thing)
        else:
            thing.promote_status = STATUS.accepted
            promotion_log(thing, "status update: accepted")    
            emailer.accept_promo(thing)
        thing._commit()

def reject_promo(thing, reason = ""):
    """
    Reject promotion and set its status as rejected

    Here, we use unpromote so that we can also remove a promotion from
    the queue if it has become promoted.
    """
    unpromote(thing, status = STATUS.rejected)
    promotion_log(thing, "status update: rejected. Reason: '%s'" % reason)
    emailer.reject_promo(thing, reason)

def delete_promo(thing):
    """
    deleted promotions have to be specially dealt with.  Reject the
    promo and void any associated transactions.
    """
    thing.promoted = False
    thing._deleted = True
    reject_promo(thing, reason = "The promotion was deleted by the user")
    if thing.promote_trans_id > 0:
        user = Account._byID(thing.author_id)
        authorize.void_transaction(user, thing.promote_trans_id)



def pending_promo(thing):
    """
    For an accepted promotion within the proper time interval, charge
    the account of the user and set the new status as pending. 
    """
    if thing.promote_status == STATUS.accepted and thing.promote_trans_id:
        user = Account._byID(thing.author_id)
        # TODO: check for charge failures/recharges, etc
        if authorize.charge_transaction(user, thing.promote_trans_id):
            promotion_log(thing, "status update: pending")
            thing.promote_status = STATUS.pending
            thing.promote_paid = thing.promote_bid
            thing._commit()
            emailer.queue_promo(thing)
        else:
            promotion_log(thing, "status update: charge failure")
            thing._commit()
            #TODO: email rejection?



def promote(thing, batch = False):
    """
    Given a promotion with pending status, set the status to promoted
    and move it into the promoted queue.
    """
    if thing.promote_status == STATUS.pending:
        promotion_log(thing, "status update: live")
        PromoteDates.log_start(thing)
        thing.promoted_on = datetime.now(g.tz)
        thing.promote_status = STATUS.promoted
        thing._commit()
        emailer.live_promo(thing)
        if not batch:
            with g.make_lock(promoted_lock_key):
                promoted = get_promoted_direct()
                if thing._fullname not in promoted:
                    promoted[thing._fullname] = auction_weight(thing)
                    set_promoted(promoted)

def unpromote(thing, batch = False, status = STATUS.finished):
    """
    unpromote a link with provided status, removing it from the
    current promotional queue.
    """
    if status == STATUS.finished:
        PromoteDates.log_end(thing)
        emailer.finished_promo(thing)
        thing.unpromoted_on = datetime.now(g.tz)
        promotion_log(thing, "status update: finished")
    thing.promote_status = status
    thing._commit()
    if not batch:
        with g.make_lock(promoted_lock_key):
            promoted = get_promoted_direct()
            if thing._fullname in promoted:
                del promoted[thing._fullname]
                set_promoted(promoted)

# batch methods for moving promotions into the pending queue, and
# setting status as pending.

# dates are referenced to UTC, while we want promos to change at (roughly)
# midnight eastern-US.
# TODO: make this a config parameter
timezone_offset = -5 # hours
timezone_offset = timedelta(0, timezone_offset * 3600)

def promo_datetime_now():
    return datetime.now(g.tz) + timezone_offset

def generate_pending(date = None, test = False):
    """
    Look-up links that are to be promoted on the provided date (the
    default is now plus one day) and set their status as pending if
    they have been accepted.  This results in credit cards being charged.
    """
    date = date or (promo_datetime_now() + timedelta(1))
    links = Link._by_fullname([p.thing_name for p in 
                               PromoteDates.for_date(date)],
                              data = True,
                              return_dict = False)
    for l in links:
        if l._deleted and l.promote_status != STATUS.rejected:
            print "DELETING PROMO", l
            # deleted promos should never be made pending
            delete_promo(l)
        elif l.promote_status == STATUS.accepted:
            if test:
                print "Would have made pending: (%s, %s)" % \
                      (l, l.make_permalink(None))
            else:
                pending_promo(l)


def promote_promoted(test = False):
    """
    make promotions that are no longer supposed to be active
    'finished' and find all pending promotions that are supposed to be
    promoted and promote them.
    """
    from r2.lib.traffic import load_traffic
    with g.make_lock(promoted_lock_key):
        now = promo_datetime_now()

        promoted =  Link._by_fullname(get_promoted_direct().keys(),
                                      data = True, return_dict = False)
        promos = {}
        for l in promoted:
            keep = True
            if l.promote_until < now:
                keep = False
            maximum_clicks = getattr(l, "maximum_clicks", None)
            maximum_views = getattr(l, "maximum_views", None)
            if maximum_clicks or maximum_views:
                # grab the traffic
                traffic = load_traffic("day", "thing", l._fullname)
                if traffic:
                    # (unique impressions, number impressions, 
                    #  unique clicks, number of clicks)
                    traffic = [y for x, y in traffic]
                    traffic = map(sum, zip(*traffic))
                    uimp, nimp, ucli, ncli = traffic
                    if maximum_clicks and maximum_clicks < ncli:
                        keep = False
                    if maximum_views and maximum_views < nimp:
                        keep = False

            if not keep:
                if test:
                    print "Would have unpromoted: (%s, %s)" % \
                          (l, l.make_permalink(None))
                else:
                    unpromote(l, batch = True)

        new_promos = Link._query(Link.c.promote_status == (STATUS.pending,
                                                           STATUS.promoted),
                                 Link.c.promoted == True,
                                 data = True)
        for l in new_promos:
            if l.promote_until > now and l._date <= now:
                if test:
                    print "Would have promoted: %s" % l
                else:
                    promote(l, batch = True)
                promos[l._fullname] = auction_weight(l)
            elif l.promote_until <= now:
                if test:
                    print "Would have unpromoted: (%s, %s)" % \
                          (l, l.make_permalink(None))
                else:
                    unpromote(l, batch = True)

        # remove unpaid promos that are scheduled to run on today or before
        unpaid_promos = Link._query(Link.c.promoted == True,
                                    Link.c.promote_status == STATUS.unpaid,
                                    Link.c._date < now,
                                    Link.c._deleted == False, 
                                    data = True)
        for l in unpaid_promos:
            if test:
                print "Would have rejected: %s" % promo_edit_url(l)
            else:
                reject_promo(l, reason = "We're sorry, but this sponsored link was not set up for payment before the appointed date.  Please add payment info and move the date into the future if you would like to resubmit.  Also please feel free to email us at selfservicesupport@reddit.com if you believe this email is in error.")


        if test:
            print promos
        else:
            set_promoted(promos)
        return promos

def auction_weight(link):
    duration = (link.promote_until - link._date).days
    return duration and link.promote_bid / duration

def set_promoted(link_names):
    # caller is assumed to execute me inside a lock if necessary
    g.permacache.set(promoted_memo_key, link_names)

    #update cache
    get_promoted(_update = True)

@memoize(promoted_memo_key, time = promoted_memo_lifetime)
def get_promoted():
    # does not lock the list to return it, so (slightly) stale data
    # will be returned if called during an update rather than blocking
    return get_promoted_direct()

def get_promoted_direct():
    return g.permacache.get(promoted_memo_key, {})


def get_promoted_slow():
    # to be used only by a human at a terminal
    with g.make_lock(promoted_lock_key):
        links = Link._query(Link.c.promote_status == STATUS.promoted,
                            Link.c.promoted == True,
                            data = True)
        link_names = dict((x._fullname, auction_weight(x)) for x in links)

        set_promoted(link_names)

    return link_names


def random_promoted():
    """
    return a list of the currently promoted items, randomly choosing
    the order of the list based on the bid-weighing.
    """
    bids = get_promoted()
    market = sum(bids.values())
    if market: 
       # get a list of current promotions, sorted by their bid amount
        promo_list = bids.keys()
        # sort by bids and use the thing_id as the tie breaker (for
        # consistent sorting)
        promo_list.sort(key = lambda x: (bids[x], x), reverse = True)
        if len(bids) > 1:
            # pick a number, any number
            n = random.uniform(0, 1)
            for i, p in enumerate(promo_list):
                n -= bids[p] / market
                if n < 0:
                    return promo_list[i:] + promo_list[:i]
        return promo_list


def test_random_promoted(n = 1000):
    promos = get_promoted()
    market = sum(promos.values())
    if market:
        res = {}
        for i in xrange(n):
            key = random_promoted()[0]
            res[key] = res.get(key, 0) + 1

        print "%10s expected actual   E/A" % "thing"
        print "------------------------------------"
        for k, v in promos.iteritems():
            expected = float(v) / market * 100
            actual   = float(res.get(k, 0)) / n * 100

            print "%10s %6.2f%% %6.2f%% %6.2f" % \
                  (k, expected, actual, expected / actual if actual else 0) 

