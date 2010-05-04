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
        sr = Subreddit._by_name(name)
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
        rb = rb.split('_')
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
    
    def __init__(self, link, indx, raw_campaign, transaction):
        sd, ed, bid, sr, trans_id  = raw_campaign
        self.indx = indx
        self.start_date = sd.strftime("%m/%d/%Y")
        self.end_date = ed.strftime("%m/%d/%Y")
        ndays = (ed - sd).days
        self.duration = strings.time_label % dict(num = ndays,
                                  time = ungettext("day", "days", ndays))
        self.bid = "%.2f" % bid
        self.sr = sr

        self.status = dict(paid = bool(transaction),
                           complete = False,
                           free = (trans_id < 0),
                           pay_url = pay_url(link, indx),
                           sponsor = c.user_is_sponsor)
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
    l.campaigns = dict((indx, RenderableCampaign(l, indx,
                                                 campaign, l.bids.get(indx))) 
                       for indx, campaign in
                       getattr(l, "campaigns", {}).iteritems())

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
    if c.user_is_sponsor or getattr(user, "trusted_sponsor", False):
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
    # tuple of (transaction_id, key)
    trans_tuples = [(v[CAMPAIGN.trans_id], k)
                    for k, v in getattr(link, "campaigns", {}).iteritems()
                    if v[CAMPAIGN.trans_id] != 0]
    bids = authorize.get_transactions(*trans_tuples)
    return dict((indx, bids.get((t, indx))) for t, indx in trans_tuples)


def new_campaign(link, dates, bid, sr):
    with g.make_lock(campaign_lock(link)):
        # get a copy of the attr so that it'll be
        # marked as dirty on the next write.
        campaigns = getattr(link, "campaigns", {}).copy()
        # create a new index
        indx = max(campaigns.keys() or [-1]) + 1
        # add the campaign
        # store the name not the reddit
        sr = sr.name if sr else ""
        campaigns[indx] = list(dates) + [bid, sr, 0]
        PromotionWeights.add(link, indx, sr, dates[0], dates[1], bid)
        link.campaigns = {}
        link.campaigns = campaigns
        link._commit()
        return indx

def free_campaign(link, index, user):
    auth_campaign(link, index, user, -1)

def edit_campaign(link, index, dates, bid, sr):
    with g.make_lock(campaign_lock(link)):
        campaigns = getattr(link, "campaigns", {}).copy()
        if index in campaigns:
            trans_id = campaigns[index][CAMPAIGN.trans_id]
            prev_bid = campaigns[index][CAMPAIGN.bid]
            # store the name not the reddit
            sr = sr.name if sr else ""
            campaigns[index] = list(dates) + [bid, sr, trans_id]
            PromotionWeights.reschedule(link, index,
                                        sr, dates[0], dates[1], bid)
            link.campaigns = {}
            link.campaigns = campaigns
            link._commit()

            #TODO cancel any existing charges if the bid has changed
            if prev_bid != bid:
                void_campaign(link, index, c.user)


def delete_campaign(link, index):
    with g.make_lock(campaign_lock(link)):
        campaigns = getattr(link, "campaigns", {}).copy()
        if index in campaigns:
            PromotionWeights.delete_unfinished(link, index)
            del campaigns[index]
            link.campaigns = {}
            link.campaigns = campaigns
            link._commit()
            #TODO cancel any existing charges
            void_campaign(link, index, c.user)

def void_campaign(link, index, user):
    campaigns = getattr(link, "campaigns", {}).copy()
    if index in campaigns:
        sd, ed, bid, sr, trans_id = campaigns[index]
        transactions = get_transactions(link)
        if transactions.get(index):
            # void the existing transaction
            a = Account._byID(link.author_id)
            authorize.void_transaction(a, trans_id, index)

def auth_campaign(link, index, user, pay_id):
    """
    for setting up a campaign as a real bid with authorize.net
    """
    with g.make_lock(campaign_lock(link)):
        campaigns = getattr(link, "campaigns", {}).copy()
        if index in campaigns:
            # void any existing campaign
            void_campaign(link, index, user)

            sd, ed, bid, sr, trans_id = campaigns[index]
            # create a new transaction and update the bid
            test = 1 if g.debug else None
            trans_id, reason = authorize.auth_transaction(bid, user,
                                                          pay_id, link,
                                                          index,
                                                          test = test)
            if not reason and trans_id is not None and int(trans_id) != 0:
                promotion_log(link, "updated payment and/or bid: "
                              "SUCCESS (id: %s)"
                              % trans_id)
                if trans_id < 0:
                    promotion_log(link, "FREEBIE")

                set_status(link,
                           max(STATUS.unseen if trans_id else STATUS.unpaid,
                               link.promote_status))
                # notify of campaign creation
                # update the query queue
                if user._id == link.author_id and trans_id > 0:
                    emailer.promo_bid(link, bid, sd)

            else:
                # something bad happend.
                promotion_log(link, "updated payment and/or bid: FAILED ('%s')" 
                              % reason)
                trans_id = 0

            campaigns[index] = sd, ed, bid, sr, trans_id
            link.campaigns = {}
            link.campaigns = campaigns
            link._commit()

            return bool(trans_id), reason
        return False, ""

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



def get_scheduled_campaign(link, offset = None):
    """
    returns the indices of the campaigns that (datewise) could be active.
    """
    now = promo_datetime_now(offset = offset)
    active = []
    campaigns = getattr(link, "campaigns", {})
    for indx in campaigns:
        sd, ed, bid, sr, trans_id = campaigns[indx]
        if sd <= now and ed >= now:
            active.append(indx)
    return active


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
        #TODO: smarter would be nice, but this will have to do for now
        make_daily_promotions()
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
            weighted[k] = [(lid, w) for lid, w in weighted[k]
                           if lid != link._fullname]
            if not weighted[k]:
                del weighted[k]
        set_live_promotions((links, weighted))
        promotion_log(link, "dequeued")
    emailer.reject_promo(link, reason = reason)


def unapprove_promotion(link):
    promotion_log(link, "status update: unapproved")
    # update the query queue
    set_status(link, STATUS.unseen)
    links, weghts = get_live_promotions()

def accepted_iter(func, offset = 0):
    now = promo_datetime_now(offset = offset)
    campaigns = PromotionWeights.get_campaigns(now)
    # load the links that have campaigns coming up
    links = Link._by_fullname(set(x.thing_name for x in campaigns),
                              data = True,return_dict = True)
    for x in campaigns:
        l = links[x.thing_name]
        if is_accepted(l):
            # get the campaign of interest from the link
            camp = getattr(l, "campaigns", {}).get(x.promo_idx)
            # the transaction id is the last of the campaign tuple
            if camp and camp[CAMPAIGN.trans_id]:
                func(l, camp, x.promo_idx, x.weight)


def charge_pending(offset = 1):
    def _charge(l, camp, indx, weight):
        user = Account._byID(l.author_id)
        sd, ed, bid, sr, trans_id = camp
        try:
            if (not authorize.is_charged_transaction(trans_id, indx) and
                authorize.charge_transaction(user, trans_id, indx)):
                # TODO: probably not absolutely necessary
                promotion_log(l, "status update: pending")
                # update the query queue
                if is_promoted(l):
                    emailer.queue_promo(l, bid, trans_id)
                else:
                    set_status(l, STATUS.pending,
                               onchange = lambda: emailer.queue_promo(l, bid, trans_id) )
        except:
            print "Error on %s, campaign %s" % (l, indx)
    accepted_iter(_charge, offset = offset)


def get_scheduled(offset = 0):
    """
    gets a dictionary of sr -> list of (link, weight) for promotions
    that should be live as of the day which is offset days from today.
    """
    by_sr = {}
    def _promote(l, camp, indx, weight):
        sd, ed, bid, sr, trans_id = camp
        if authorize.is_charged_transaction(trans_id, indx):
            by_sr.setdefault(sr, []).append((l, weight))
    accepted_iter(_promote, offset = offset)
    return by_sr


def get_traffic_weights(srnames):
    from r2.lib import traffic

    # the weight is just the last 7 days of impressions (averaged)
    def weigh(t, npoints = 7):
        if t:
            t = [y[1] for x, y in t[-npoints-1:-1]]
            return max(float(sum(t)) / len(t), 1)
        return 1

    default_traffic = [weigh(traffic.load_traffic("day", "reddit", sr.name))
                             for sr in Subreddit.top_lang_srs('all', 10)]
    default_traffic = (float(max(sum(default_traffic),1)) /
                       max(len(default_traffic), 1))

    res = {}
    for srname in srnames:
        if srname:
            res[srname] = (default_traffic /
                          weigh(traffic.load_traffic("day", "reddit", srname)) )
        else:
            res[srname] = 1
    return res

def get_weighted_schedule(offset = 0):
    by_sr = get_scheduled(offset = offset)
    weight_dict = get_traffic_weights(by_sr.keys())
    weighted = {}
    links = set()
    for sr_name, t_tuples in by_sr.iteritems():
        weighted[sr_name] = []
        for l, weight in t_tuples:
            links.add(l._fullname)
            weighted[sr_name].append((l._fullname,
                                      weight * weight_dict[sr_name]))
    return links, weighted

def promotion_key():
    return "current_promotions"

def get_live_promotions():
    return g.permacache.get(promotion_key()) or (set(), {})

def set_live_promotions(x):
    return g.permacache.set(promotion_key(), x)

def make_daily_promotions(offset = 0, test = False):
    old_links = set([])
    all_links, weighted = get_weighted_schedule(offset)
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


def get_promotion_list(user, site):
    # site is specified, pick an ad from that site
    if not isinstance(site, FakeSubreddit):
        srids = set([site._id])
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
        for k, links in promo_dict.iteritems():
            if k in sites:
                for l, w in links:
                    available[l] = available.get(l, 0) + w
        # sort the available list by weight
        links = available.keys()
        links.sort(key = lambda x: -available[x])
        norm = sum(available.values())
        # return a sorted list of (link, norm_weight)
        return [(l, available[l] / norm) for l in links]

    return []

def randomized_promotion_list(user, site):
    promos = get_promotion_list(user, site)
    # no promos, no problem
    if not promos:
        return []
    # more than two: randomize
    elif len(promos) > 1:
        n = random.uniform(0, 1)
        for i, (l, w) in enumerate(promos):
            n -= w
            if n < 0:
                promos = promos[i:] + promos[:i]
                break
    # fall thru for the length 1 case here as well
    return [l for l, w in promos]


def insert_promoted(link_names, pos, promoted_every_n = 5):
    """
    Inserts promoted links into an existing organic list. Destructive
    on `link_names'
    """
    promoted_items = randomized_promotion_list(c.user, c.site)

    if not promoted_items:
        return link_names, pos

    # no point in running the builder over more promoted links than
    # we'll even use
    max_promoted = max(1,len(link_names)/promoted_every_n)

    builder = IDBuilder(promoted_items, keep_fn = keep_fresh_links,
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

    return list(UniqueIterator(link_names)), pos

def benchmark_promoted(user, site, pos = 0, link_sample = 50, attempts = 100):
    c.user = user
    c.site = site
    link_names = ["blah%s" % i for i in xrange(link_sample)]
    res = {}
    for i in xrange(attempts):
        names, p =  insert_promoted(link_names[::], pos)
        name = names[p]
        res[name] = res.get(name, 0) + 1
    res = list(res.iteritems())
    res.sort(key = lambda x : x[1], reverse = True)
    expected = dict(get_promotion_list(user, site))
    for l, v in res:
        print "%s: %5.3f %3.5f" % (l,float(v)/attempts, expected.get(l, 0))



def Run(offset = 0):
    charge_pending(offset = offset + 1)
    charge_pending(offset = offset)
    make_daily_promotions(offset = offset)


