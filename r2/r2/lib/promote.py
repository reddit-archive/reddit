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
# All portions of the code written by reddit are Copyright (c) 2006-2012 reddit
# Inc. All Rights Reserved.
###############################################################################

from __future__ import with_statement

from r2.models import *
from r2.lib.wrapped import Wrapped
from r2.lib import authorize
from r2.lib import emailer, filters
from r2.lib.memoize import memoize
from r2.lib.template_helpers import get_domain
from r2.lib.utils import Enum, UniqueIterator
from organic import keep_fresh_links
from pylons import g, c
from datetime import datetime, timedelta
from r2.lib.db.queries import make_results, db_sort, add_queries, merge_results
import itertools

import random

promoted_memo_lifetime = 30
promoted_memo_key = 'cached_promoted_links2'
promoted_lock_key = 'cached_promoted_links_lock2'

STATUS = Enum("unpaid", "unseen", "accepted", "rejected",
              "pending", "promoted", "finished")

CAMPAIGN = Enum("start", "end", "bid", "sr", "trans_id")

@memoize("get_promote_srid")
def get_promote_srid(name = 'promos'):
    try:
        sr = Subreddit._by_name(name, stale=True)
    except NotFound:
        sr = Subreddit._new(name = name,
                            title = "promoted links",
                            # negative author_ids make this unlisable
                            author_id = -1,
                            type = "public", 
                            ip = '0.0.0.0')
    return sr._id

# attrs

def promo_traffic_url(l):
    domain = get_domain(cname = False, subreddit = False)
    return "http://%s/traffic/%s/" % (domain, l._id36)

def promo_edit_url(l):
    domain = get_domain(cname = False, subreddit = False)
    return "http://%s/promoted/edit_promo/%s" % (domain, l._id36)

def pay_url(l, indx):
    return "%spromoted/pay/%s/%d" % (g.payment_domain, l._id36, indx)

def view_live_url(l, srname):
    url = get_domain(cname=False, subreddit=False)
    if srname:
        url += '/r/%s' % srname
    return 'http://%s/?ad=%s' % (url, l._fullname)

# booleans

def is_promo(link):
    return (link and not link._deleted and link.promoted is not None
            and hasattr(link, "promote_status"))

def is_accepted(link):
    return is_promo(link) and (link.promote_status != STATUS.rejected and
                               link.promote_status >= STATUS.accepted)

def is_unpaid(link):
    return is_promo(link) and link.promote_status == STATUS.unpaid

def is_unapproved(link):
    return is_promo(link) and link.promote_status <= STATUS.unseen

def is_rejected(link):
    return is_promo(link) and link.promote_status == STATUS.rejected

def is_promoted(link):
    return is_promo(link) and link.promote_status == STATUS.promoted

def is_valid_campaign(link, campaign_id):
    # check for campaign in link data (old way)
    if link and campaign_id in getattr(link, "campaigns", {}):
        return True
    # check for campaign in Thing data (new way)
    try:
        PromoCampaign._byID(campaign_id)
        return True
    except NotFound:
        return False

def is_live_on_sr(link, srname):
    if not is_promoted(link):
        return False
    live = scheduled_campaigns_by_link(link)
    srname = srname.lower()
    srname = srname if srname != DefaultSR.name.lower() else ''

    campaigns = PromoCampaign._byID(live, return_dict=True)
    for campaign_id in live:
        campaign = campaigns.get(campaign_id)
        if campaign and campaign.sr_name.lower() == srname:
            return True
    return False


def campaign_is_live(link, campaign_index):
    if not is_promoted(link):
        return False
    live = scheduled_campaigns_by_link(link)
    return campaign_index in live


# no references to promote_status below this function, pls
def set_status(l, status, onchange = None):
    # keep this out here.  Useful for updating the queue if there is a bug
    # and for initial migration
    add_queries([_sponsored_link_query(None, l.author_id),
                 _sponsored_link_query(None),
                 _sponsored_link_query(status, l.author_id),
                 _sponsored_link_query(status)], insert_items = [l])

    # no need to delete or commit of the status is unchanged
    if status != getattr(l, "promote_status", None):
        # new links won't even have a promote_status yet
        if hasattr(l, "promote_status"):
            add_queries([_sponsored_link_query(l.promote_status, l.author_id),
                         _sponsored_link_query(l.promote_status)],
                        delete_items = [l])
        l.promote_status = status
        l._commit()
        if onchange: 
            onchange()

# query queue updates below

def _sponsored_link_query(status, author_id = None):
    q = Link._query(Link.c.sr_id == get_promote_srid(),
                    Link.c._spam == (True, False),
                    Link.c._deleted == (True,False),
                    sort = db_sort('new'))
    if status is not None:
        q._filter(Link.c.promote_status == status)
    if author_id is not None:
        q._filter(Link.c.author_id == author_id)
    return make_results(q)

def get_unpaid_links(author_id = None):
    return _sponsored_link_query(STATUS.unpaid, author_id = author_id)

def get_unapproved_links(author_id = None):
    return _sponsored_link_query(STATUS.unseen, author_id = author_id)

def get_rejected_links(author_id = None):
    return _sponsored_link_query(STATUS.rejected, author_id = author_id)

def get_live_links(author_id = None):
    return _sponsored_link_query(STATUS.promoted, author_id = author_id)

def get_accepted_links(author_id = None):
    return merge_results(_sponsored_link_query(STATUS.accepted,
                                 author_id = author_id),
                         _sponsored_link_query(STATUS.pending,
                                 author_id = author_id),
                         _sponsored_link_query(STATUS.finished,
                                 author_id = author_id))

def get_all_links(author_id = None):
    return _sponsored_link_query(None, author_id = author_id)


# subreddit roadblocking functions

roadblock_prefix = "promotion_roadblock"
def roadblock_key(sr_name, d):
    return "%s-%s_%s" % (roadblock_prefix,
                         sr_name, d.strftime("%Y_%m_%d"))

def roadblock_reddit(sr_name, start_date, end_date):
    d = start_date
    now = promo_datetime_now().date()
    # set the expire to be 1 week after the roadblock end date
    expire = ((end_date - now).days + 7) * 86400
    while d < end_date:
        g.hardcache.add(roadblock_key(sr_name, d),
                        "%s-%s" % (start_date.strftime("%Y_%m_%d"),
                                   end_date.strftime("%Y_%m_%d")),
                        time = expire)
        d += timedelta(1)

def unroadblock_reddit(sr_name, start_date, end_date):
    d = start_date
    while d < end_date:
        g.hardcache.delete(roadblock_key(sr_name, d))
        d += timedelta(1)

def is_roadblocked(sr_name, start_date, end_date):
    d = start_date
    while d < end_date:
        res = g.hardcache.get(roadblock_key(sr_name, d))
        if res:
            start_date, end_date = res.split('-')
            start_date = datetime.strptime(start_date, "%Y_%m_%d").date()
            end_date = datetime.strptime(end_date, "%Y_%m_%d").date()
            return (start_date, end_date)
        d += timedelta(1)

def get_roadblocks():
    rbs = g.hardcache.backend.ids_by_category(roadblock_prefix)
    by_sr = {}
    for rb in rbs:
        rb = rb.rsplit('_', 3)  # subreddit_name_YYYY_MM_DD
        date = datetime.strptime('_'.join(rb[1:]), "%Y_%m_%d").date()
        by_sr.setdefault(rb[0], []).append((date, date + timedelta(1)))

    blobs = []
    for k, v in by_sr.iteritems():
        for sd, ed in sorted(v):
            if blobs and  blobs[-1][0] == k and blobs[-1][-1] == sd:
                blobs[-1] = (k, blobs[-1][1], ed)
            else:
                blobs.append((k, sd, ed))
    blobs.sort(key = lambda x: x[1])
    return blobs

# control functions

class RenderableCampaign():
    __slots__ = ["indx", "start_date", "end_date", "duration",
                 "bid", "sr", "status"]
    
    def __init__(self, link, campaign, transaction):
        self.indx = campaign._id
        self.start_date = campaign.start_date.strftime("%m/%d/%Y")
        self.end_date = campaign.end_date.strftime("%m/%d/%Y")
        ndays = (campaign.end_date - campaign.start_date).days
        self.duration = strings.time_label % dict(num = ndays,
                          time = ungettext("day", "days", ndays))
        self.bid = "%.2f" % campaign.bid
        self.sr = campaign.sr_name
        live = campaign_is_live(link, campaign._id)
        
        self.status = dict(paid = bool(transaction),
                           complete = False,
                           free = campaign.is_freebie(),
                           pay_url = pay_url(link, campaign._id),
                           view_live_url = view_live_url(link, campaign.sr_name),
                           sponsor = c.user_is_sponsor,
                           live = live)

        if transaction:
            if transaction.is_void():
                self.status['paid'] = False
                self.status['free'] = False
            elif transaction.is_charged():
                self.status['complete'] = True

    def get(self, key, default):
        return getattr(self, key, default)

    def __iter__(self):
        for s in self.__slots__:
            yield getattr(self, s)

def editable_add_props(l):
    if not isinstance(l, Wrapped):
        l = Wrapped(l)

    l.bids = get_transactions(l)

    campaigns = {}
    for campaign in PromoCampaign._by_link(l._id):
        campaigns[campaign._id] = RenderableCampaign(l, campaign, l.bids.get(campaign._id))
    l.campaigns = campaigns

    return l

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

def traffic_totals():
    from r2.models import traffic
    impressions = traffic.AdImpressionsByCodename.historical_totals("day")
    clicks = traffic.ClickthroughsByCodename.historical_totals("day")
    traffic_data = traffic.zip_timeseries(impressions, clicks)
    return [(d.date(), v) for d, v in traffic_data]

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

def new_promotion(title, url, user, ip):
    """
    Creates a new promotion with the provided title, etc, and sets it
    status to be 'unpaid'.
    """
    sr = Subreddit._byID(get_promote_srid())
    l = Link._submit(title, url, user, sr, ip)
    l.promoted = True
    l.disable_comments = False
    l.campaigns = {}
    promotion_log(l, "promotion created")
    l._commit()

    # set the status of the link, populating the query queue
    if c.user_is_sponsor or user.trusted_sponsor:
        set_status(l, STATUS.accepted)
    else:
        set_status(l, STATUS.unpaid)

    # the user has posted a promotion, so enable the promote menu unless
    # they have already opted out
    if user.pref_show_promote is not False:
        user.pref_show_promote = True
        user._commit()

    # notify of new promo
    emailer.new_promo(l)
    return l

def sponsor_wrapper(link):
    w = Wrapped(link)
    w.render_class = PromotedLink
    w.rowstyle = "promoted link"
    return w

def campaign_lock(link):
    return "edit_promo_campaign_lock_" + str(link._id)

def get_transactions(link):
    '''
    Gets records from the bids table for all campaigns on link that have a
      non-zero transaction id. Note this set includes auth, charged, and void
      transactions, any of which could be freebies and/or finished running.
    Returns a dict mapping campaign ids to Bid objects.
    '''
    campaigns = PromoCampaign._query(PromoCampaign.c.link_id == link._id,
                                     PromoCampaign.c.trans_id != 0,
                                     data=True)
    trans_tuples = [(camp.trans_id, camp._id) for camp in campaigns]
    bids = authorize.get_transactions(*trans_tuples)
    bids_by_campaign = {}
    for trans_id, campaign_id in trans_tuples:
        bids_by_campaign[campaign_id] = bids.get((trans_id, campaign_id))
    return bids_by_campaign


def new_campaign(link, dates, bid, sr):
    # empty string for sr_name means target to all
    sr_name = sr.name if sr else ""
    # dual-write campaigns as data Things
    campaign = PromoCampaign._new(link, sr_name, bid, dates[0], dates[1])
    # note indx in link.campaigns is the Thing id now 
    indx = campaign._id
    with g.make_lock("promo_campaign", campaign_lock(link)):
        # get a copy of the attr so that it'll be
        # marked as dirty on the next write.
        campaigns = getattr(link, "campaigns", {}).copy()
        # add the campaign
        campaigns[indx] = list(dates) + [bid, sr_name, 0]
        PromotionWeights.add(link, indx, sr_name, dates[0], dates[1], bid)
        link.campaigns = {}
        link.campaigns = campaigns
        promotion_log(link, "campaign %s created" % campaign._id)
        link._commit()


    author = Account._byID(link.author_id, True)
    if getattr(author, "complimentary_promos", False):
        free_campaign(link, indx, c.user)

    return indx

def free_campaign(link, campaign_id, user):
    auth_campaign(link, campaign_id, user, -1)

def edit_campaign(link, campaign_id, dates, bid, sr):
    sr_name = sr.name if sr else '' # empty string means target to all
    try: 
        campaign = PromoCampaign._byID(campaign_id)

        # if the bid amount changed, cancel any pending transactions
        if campaign.bid != bid:
            void_campaign(link, campaign_id)

        # update the schedule
        PromotionWeights.reschedule(link, campaign_id, sr_name,
                                    dates[0], dates[1], bid)

        # update values in the db
        campaign.update(dates[0], dates[1], bid, sr_name, campaign.trans_id, commit=True)

        # dual-write to link attribute in case we need to roll back
        with g.make_lock("promo_campaign", campaign_lock(link)):
            campaigns = getattr(link, 'campaigns', {}).copy()
            campaigns[campaign_id] = (dates[0], dates[1], bid, sr_name, campaign.trans_id)
            link.campaigns = campaigns
            link._commit()

        # record the transaction
        promotion_log(link, "updated campaign %s. (bid: %0.2f)" % (campaign_id, bid), commit=True)
       
        # make it a freebie, if applicable
        author = Account._byID(link.author_id, True)
        if getattr(author, "complimentary_promos", False):
            free_campaign(link, campaign._id, c.user)

    except Exception, e: # record error and rethrow 
        g.log.error("Failed to update PromoCampaign %s on link %d. Error was: %r" % 
                    (campaign_id, link._id, e))
        try: # wrapped in try/except so orig error won't be lost if commit fails
            promotion_log(link, "update FAILED. (campaign: %s, bid: %.2f)" % 
              (campaign_id, bid), commit=True)
        except:
            pass
        raise e


def complimentary(username, value = True):
    a = Account._by_name(username, True)
    a.complimentary_promos = value
    a._commit()

def delete_campaign(link, index):
    with g.make_lock("promo_campaign", campaign_lock(link)):
        campaigns = getattr(link, "campaigns", {}).copy()
        if index in campaigns:
            PromotionWeights.delete_unfinished(link, index)
            del campaigns[index]
            link.campaigns = {}
            link.campaigns = campaigns
            promotion_log(link, "deleted campaign %s" % index)
            link._commit()
            #TODO cancel any existing charges
            void_campaign(link, index)
    # dual-write update to campaign Thing if it exists
    try:
        campaign = PromoCampaign._byID(index)
        campaign.delete()
    except NotFound:
        g.log.debug("Skipping deletion of non-existent PromoCampaign [link:%d, index:%d]" %
                    (link._id, index))

def void_campaign(link, campaign_id):
    transactions = get_transactions(link)
    bid_record = transactions.get(campaign_id)
    if bid_record:
        a = Account._byID(link.author_id)
        authorize.void_transaction(a, bid_record.transaction, campaign_id)

def auth_campaign(link, campaign_id, user, pay_id):
    """
    Authorizes (but doesn't charge) a bid with authorize.net.
    Args:
    - link: promoted link
    - campaign_id: long id of the campaign on link to be authorized
    - user: Account obj of the user doing the auth (usually the currently
        logged in user)
    - pay_id: customer payment profile id to use for this transaction. (One
        user can have more than one payment profile if, for instance, they have
        more than one credit card on file.) Set pay_id to -1 for freebies.

    Returns: (True, "") if successful or (False, error_msg) if not. 
    """
    try:
        campaign = PromoCampaign._byID(campaign_id, data=True)
    except NotFound:
        g.log.error("Ignoring attempt to auth non-existent campaign: %d" % 
                    campaign_id)
        return False, "Campaign not found."

    void_campaign(link, campaign_id)
    test = 1 if g.debug else None
    trans_id, reason = authorize.auth_transaction(campaign.bid, user, pay_id,
                                                  link, campaign_id, test=test)

    if trans_id and not reason:
        promotion_log(link, "updated payment and/or bid for campaign %s: "
                      "SUCCESS (trans_id: %d, amt: %0.2f)"
                      % (campaign_id, trans_id, campaign.bid))
        if trans_id < 0:
            promotion_log(link, "FREEBIE (campaign: %s)" % campaign_id)

        set_status(link,
                   max(STATUS.unseen if trans_id else STATUS.unpaid,
                       link.promote_status))
        # notify of campaign creation
        # update the query queue
        if user and (user._id == link.author_id) and trans_id > 0:
            emailer.promo_bid(link, campaign.bid, campaign.start_date)
    
    else:
        # something bad happend.
        promotion_log(link, "updated payment and/or bid for campaign %s: FAILED ('%s')" 
                      % (campaign_id, reason))
        trans_id = 0

    campaign.trans_id = trans_id
    campaign._commit()

    # dual-write update to link attribute in case we need to roll back
    with g.make_lock("promo_campaign", campaign_lock(link)):
        campaigns = getattr(link, "campaigns", {}).copy()
        if campaign_id in campaigns:
            campaigns[campaign_id] = (campaign.start_date, campaign.end_date,
                                      campaign.bid, campaign.sr_name, campaign.trans_id)
            link.campaigns = {}
            link.campaigns = campaigns
            link._commit()

    return bool(trans_id), reason



# dates are referenced to UTC, while we want promos to change at (roughly)
# midnight eastern-US.
# TODO: make this a config parameter
timezone_offset = -5 # hours
timezone_offset = timedelta(0, timezone_offset * 3600)
def promo_datetime_now(offset = None):
    now = datetime.now(g.tz) + timezone_offset
    if offset is not None:
        now += timedelta(offset)
    return now

def accept_promotion(link):
    """
    Accepting is campaign agnostic.  Accepting the ad just means that
    it is allowed to run if payment has been processed.

    If a campagn is able to run, this also requeues it.
    """
    promotion_log(link, "status update: accepted")
    # update the query queue

    set_status(link, STATUS.accepted)
    now = promo_datetime_now(0)
    if link._fullname in set(l.thing_name for l in
                             PromotionWeights.get_campaigns(now)):
        promotion_log(link, "requeued")
        charge_pending(0) # campaign must be charged before it will go live
        make_daily_promotions()
    if link._spam:
        link._spam = False
        link._commit()
    emailer.accept_promo(link)

def reject_promotion(link, reason = None):
    promotion_log(link, "status update: rejected")
    # update the query queue
    set_status(link, STATUS.rejected)
    # check to see if this link is a member of the current live list
    links, weighted = get_live_promotions()
    if link._fullname in links:
        links.remove(link._fullname)
        for k in list(weighted.keys()):
            weighted[k] = [(lid, w, cid) for lid, w, cid in weighted[k]
                           if lid != link._fullname]
            if not weighted[k]:
                del weighted[k]
        set_live_promotions((links, weighted))
        promotion_log(link, "dequeued")
    # don't send a rejection email when the rejection was user initiated.
    if not c.user or c.user._id != link.author_id:
        emailer.reject_promo(link, reason = reason)


def unapprove_promotion(link):
    promotion_log(link, "status update: unapproved")
    # update the query queue
    set_status(link, STATUS.unseen)
    links, weghts = get_live_promotions()

def accepted_campaigns(offset=0):
    now = promo_datetime_now(offset=offset)
    promo_weights = PromotionWeights.get_campaigns(now)
    all_links = Link._by_fullname(set(x.thing_name for x in promo_weights),
                                  data=True, return_dict=True)
    accepted_links = {}
    for link_fullname, link in all_links.iteritems():
        if is_accepted(link):
            accepted_links[link._id] = link

    accepted_link_ids = accepted_links.keys()
    campaign_query = PromoCampaign._query(PromoCampaign.c.link_id==accepted_link_ids,
                                          data=True)
    campaigns = dict((camp._id, camp) for camp in campaign_query)
    for pw in promo_weights:
        campaign = campaigns.get(pw.promo_idx)
        if not campaign or not campaign.trans_id:
            continue
        link = accepted_links.get(campaign.link_id)
        if not link:
            continue

        yield (link, campaign, pw.weight)
    
def get_scheduled(offset=0):
    '''  
    Arguments:
      offset - number of days after today you want the schedule for
    Returns:
      {'by_sr': dict, 'links':set(), 'error_campaigns':[]}
      -by_sr maps sr names to lists of (Link, bid, campaign_fullname) tuples
      -links is the set of promoted Link objects used in the schedule
      -error_campaigns is a list of (campaign_id, error_msg) tuples if any 
        exceptions were raised or an empty list if there were none
      Note: campaigns in error_campaigns will not be included in by_sr
      '''
    by_sr = {} 
    error_campaigns = [] 
    links = set()
    for l, campaign, weight in accepted_campaigns(offset=offset):
        try:
            if authorize.is_charged_transaction(campaign.trans_id, campaign._id):
                by_sr.setdefault(campaign.sr_name, []).append((l, weight, campaign._fullname))
                links.add(l)
        except Exception, e: # could happen if campaign things have corrupt data
            error_campaigns.append((campaign._id, e))
    return {'by_sr': by_sr, 'links': links, 'error_campaigns': error_campaigns}


def charge_pending(offset=1):
    for l, camp, weight in accepted_campaigns(offset=offset):
        user = Account._byID(l.author_id)
        try:
            if (authorize.is_charged_transaction(camp.trans_id, camp._id) or not 
                authorize.charge_transaction(user, camp.trans_id, camp._id)):
                continue

            if is_promoted(l):
                emailer.queue_promo(l, camp.bid, camp.trans_id)
            else:
                set_status(l, STATUS.pending,
                    onchange=lambda: emailer.queue_promo(l, camp.bid, camp.trans_id))
            promotion_log(l, "auth charge for campaign %s, trans_id: %d" % 
                             (camp._id, camp.trans_id), commit=True)
        except:
            print "Error on %s, campaign %s" % (l, camp._id)


def scheduled_campaigns_by_link(l, date=None):
    # A promotion/campaign is scheduled/live if it's in
    # PromotionWeights.get_campaigns(now) and
    # authorize.is_charged_transaction()

    date = date or promo_datetime_now()

    if not is_accepted(l):
        return []

    scheduled = PromotionWeights.get_campaigns(date)
    campaigns = [c.promo_idx for c in scheduled if c.thing_name == l._fullname]

    # Check authorize
    accepted = []
    for campaign_id in campaigns:
        try:
            campaign = PromoCampaign._byID(campaign_id, data=True)
            if authorize.is_charged_transaction(campaign.trans_id, campaign_id):
                accepted.append(campaign_id)
        except NotFound:
            g.log.error("PromoCampaign %d scheduled to run on %s not found." %
                          (campaign_id, date.strftime("%Y-%m-%d")))

    return accepted

def get_traffic_weights(srnames):
    from r2.models.traffic import PageviewsBySubreddit

    # the weight is just the last 7 days of impressions (averaged)
    def weigh(t, npoints = 7):
        if t and len(t) > 1:
            t = [y[1] for x, y in t[-npoints-1:-1]]
            return max(float(sum(t)) / len(t), 1)
        return 1

    default_traffic = [weigh(PageviewsBySubreddit.history("day", sr.name))
                             for sr in Subreddit.top_lang_srs('all', 10)]
    default_traffic = (float(max(sum(default_traffic),1)) /
                       max(len(default_traffic), 1))

    res = {}
    for srname in srnames:
        if srname:
            res[srname] = (default_traffic /
                          weigh(PageviewsBySubreddit.history("day", sr.name)) )
        else:
            res[srname] = 1
    return res

def weight_schedule(by_sr):
    '''
    Arguments:
      by_sr - a dict mapping subreddit names to lists of (Link, bid) tuples. 
        Usually this data struct would come from the output of get_scheduled
    Returns:
      a dict just like by_sr but with bids replaced by weights 
    '''
    weight_dict = get_traffic_weights(by_sr.keys())
    weighted = {}
    for sr_name, t_tuples in by_sr.iteritems():
        weighted[sr_name] = []
        for l, weight, cid in t_tuples:
            weighted[sr_name].append((l._fullname,
                                      weight * weight_dict[sr_name],
                                      cid))
    return weighted


def promotion_key():
    return "current_promotions:1"

def get_live_promotions():
    return g.permacache.get(promotion_key()) or (set(), {})

def set_live_promotions(x):
    return g.permacache.set(promotion_key(), x)

# Gotcha: even if links are scheduled and authorized, they won't be added to 
# current promotions until they're actually charged, so make sure to call
# charge_pending() before make_daily_promotions()
def make_daily_promotions(offset = 0, test = False):
    '''
    Arguments:
      offset - number of days after today to get the schedule for
      test - if True, new schedule will be generated but not launched
    Raises Exception with list of campaigns that had errors if there were any
    '''
    old_links = set([])

    schedule = get_scheduled(offset)
    all_links = set([l._fullname for l in schedule['links']])
    error_campaigns = schedule['error_campaigns']
    weighted = weight_schedule(schedule['by_sr'])

    # over18 check
    for sr, links in weighted.iteritems():
        if sr:
            sr = Subreddit._by_name(sr)
            if sr.over_18:
                for l in Link._by_fullname([l[0] for l in links], return_dict = False):
                    l.over_18 = True
                    if not test:
                        l._commit()

    x = get_live_promotions()
    if x:
        old_links, old_weights = x
        # links that need to be promoted
        new_links = all_links - old_links
        # links that have already been promoted
        old_links = old_links - all_links
    else:
        new_links = links

    links = Link._by_fullname(new_links.union(old_links), data = True,
                              return_dict = True)
    for l in old_links:
        if is_promoted(links[l]):
            if test:
                print "unpromote", l
            else:
                # update the query queue
                set_status(links[l], STATUS.finished, 
                           onchange = lambda: emailer.finished_promo(links[l]))

    for l in new_links:
        if is_accepted(links[l]):
            if test:
                print "promote2", l
            else:
                # update the query queue
                set_status(links[l], STATUS.promoted,
                           onchange = lambda: emailer.live_promo(links[l]))

    # convert the weighted dict to use sr_ids which are more useful
    srs = {"":""}
    for srname in weighted.keys():
        if srname:
            srs[srname] = Subreddit._by_name(srname)._id
    weighted = dict((srs[k], v) for k, v in weighted.iteritems())

    if not test:
        set_live_promotions((all_links, weighted))
    else:
        print (all_links, weighted)

    # after launching as many campaigns as possible, raise an exception to 
    #   report any error campaigns. (useful for triggering alerts in irc)
    if error_campaigns:
        raise Exception("Some scheduled campaigns could not be added to daily "
                        "promotions: %r" % error_campaigns)


def get_promotion_list(user, site):
    # site is specified, pick an ad from that site
    if not isinstance(site, FakeSubreddit):
        srids = set([site._id])
    elif isinstance(site, MultiReddit):
        srids = set(site.sr_ids)
    # site is Fake, user is not.  Pick based on their subscriptions.
    elif user and not isinstance(user, FakeAccount):
        srids = set(Subreddit.reverse_subscriber_ids(user) + [""])
    # both site and user are "fake" -- get the default subscription list
    else:
        srids = set(Subreddit.user_subreddits(None, True) + [""])

    return get_promotions_cached(srids)


#@memoize('get_promotions_cached', time = 10 * 60)
def get_promotions_cached(sites):
    p = get_live_promotions()
    if p:
        links, promo_dict = p
        available = {}
        campaigns = {}
        for k, links in promo_dict.iteritems():
            if k in sites:
                for l, w, cid in links:
                    available[l] = available.get(l, 0) + w
                    campaigns[l] = cid
        # sort the available list by weight
        links = available.keys()
        links.sort(key = lambda x: -available[x])
        norm = sum(available.values())
        # return a sorted list of (link, norm_weight)
        return [(l, available[l] / norm, campaigns[l]) for l in links]

    return []

def randomized_promotion_list(user, site):
    promos = get_promotion_list(user, site)
    # no promos, no problem
    if not promos:
        return []
    # more than two: randomize
    elif len(promos) > 1:
        n = random.uniform(0, 1)
        for i, (l, w, cid) in enumerate(promos):
            n -= w
            if n < 0:
                promos = promos[i:] + promos[:i]
                break
    # fall thru for the length 1 case here as well
    return [(l, cid) for l, w, cid in promos]


def insert_promoted(link_names, pos, promoted_every_n = 5):
    """
    Inserts promoted links into an existing organic list. Destructive
    on `link_names'
    """
    promo_tuples = randomized_promotion_list(c.user, c.site)
    promoted_link_names, campaign_ids = zip(*promo_tuples) if promo_tuples else ([],[])

    if not promoted_link_names:
        return link_names, pos, {}

    campaigns_by_link = dict(promo_tuples)

    # no point in running the builder over more promoted links than
    # we'll even use
    max_promoted = max(1,len(link_names)/promoted_every_n)
    builder = IDBuilder(promoted_link_names, keep_fn = keep_fresh_links,
                        skip = True)
    promoted_items = builder.get_items()[0]

    focus = None
    if promoted_items:
        focus = promoted_items[0]._fullname
        # insert one promoted item for every N items
        for i, item in enumerate(promoted_items):
            p = i * (promoted_every_n + 1)
            if p > len(link_names):
                break
            p += pos
            if p > len(link_names):
                p = p % len(link_names)

            link_names.insert(p, item._fullname)

    link_names = filter(None, link_names)
    if focus:
        try:
            pos = link_names.index(focus)
        except ValueError:
            pass
    # don't insert one at the head of the list 50% of the time for
    # logged in users, and 50% of the time for logged-off users when
    # the pool of promoted links is less than 3 (to avoid showing the
    # same promoted link to the same person too often)
    if ((c.user_is_loggedin or len(promoted_items) < 3) and
        random.choice((True,False))):
        pos = (pos + 1) % len(link_names)  

    return list(UniqueIterator(link_names)), pos, campaigns_by_link

def benchmark_promoted(user, site, pos = 0, link_sample = 50, attempts = 100):
    c.user = user
    c.site = site
    link_names = ["blah%s" % i for i in xrange(link_sample)]
    res = {}
    for i in xrange(attempts):
        names, p, campaigns_by_link =  insert_promoted(link_names[::], pos)
        name = names[p]
        res[name] = res.get(name, 0) + 1
    res = list(res.iteritems())
    res.sort(key = lambda x : x[1], reverse = True)
    expected = dict(get_promotion_list(user, site))
    for l, v in res:
        print "%s: %5.3f %3.5f" % (l,float(v)/attempts, expected.get(l, 0))


def get_total_run(link):
    """Return the total time span this promotion has run for.

    Starts at the start date of the earliest campaign and goes to the end date
    of the latest campaign.

    """

    campaigns = PromoCampaign._by_link(link._id)
    
    earliest = None
    latest = None
    for campaign in campaigns:
        if not campaign.trans_id:
            continue

        if not earliest or campaign.start_date < earliest:
            earliest = campaign.start_date

        if not latest or campaign.end_date > latest:
            latest = campaign.end_date

    # a manually launched promo (e.g., sr discovery) might not have campaigns.
    if not earliest or not latest: 
        latest = datetime.utcnow()
        earliest = latest - timedelta(days=30)  # last month

    # ugh this stuff is a mess. they're stored as "UTC" but actually mean UTC-5.
    earliest = earliest.replace(tzinfo=None) - timezone_offset
    latest = latest.replace(tzinfo=None) - timezone_offset

    return earliest, latest


def Run(offset = 0):
    charge_pending(offset = offset + 1)
    charge_pending(offset = offset)
    make_daily_promotions(offset = offset)


