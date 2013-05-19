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

from collections import namedtuple
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import itertools
import json
import time

from pylons import g, c
from pylons.i18n import ungettext

from r2.lib import (
    authorize,
    emailer,
    hooks,
)
from r2.lib.db.operators import not_
from r2.lib.db.queries import (
    set_promote_status,
    set_underdelivered_campaigns,
    unset_underdelivered_campaigns,
)
from r2.lib.cache import sgm
from r2.lib.memoize import memoize
from r2.lib.strings import strings
from r2.lib.template_helpers import get_domain
from r2.lib.utils import to_date, weighted_lottery
from r2.models import (
    Account,
    Bid,
    DefaultSR,
    FakeAccount,
    FakeSubreddit,
    get_promote_srid,
    Link,
    MultiReddit,
    NO_TRANSACTION,
    PromoCampaign,
    PROMOTE_STATUS,
    PromotedLink,
    PromotionLog,
    PromotionWeights,
    Subreddit,
    traffic,
)
from r2.models.keyvalue import NamedGlobals

PROMO_HEALTH_KEY = 'promotions_last_updated'

def _mark_promos_updated():
    NamedGlobals.set(PROMO_HEALTH_KEY, time.time())


def health_check():
    """Calculate the number of seconds since promotions were last updated"""
    return time.time() - int(NamedGlobals.get(PROMO_HEALTH_KEY, default=0))


def cost_per_mille(spend, impressions):
    """Return the cost-per-mille given ad spend and impressions."""
    if impressions:
        return 1000. * float(spend) / impressions
    else:
        return 0


def cost_per_click(spend, clicks):
    """Return the cost-per-click given ad spend and clicks."""
    if clicks:
        return float(spend) / clicks
    else:
        return 0


# attrs

def promo_traffic_url(l): # old traffic url
    domain = get_domain(cname=False, subreddit=False)
    return "http://%s/traffic/%s/" % (domain, l._id36)

def promotraffic_url(l): # new traffic url
    domain = get_domain(cname=False, subreddit=False)
    return "http://%s/promoted/traffic/headline/%s" % (domain, l._id36)

def promo_edit_url(l):
    domain = get_domain(cname=False, subreddit=False)
    return "http://%s/promoted/edit_promo/%s" % (domain, l._id36)

def pay_url(l, campaign):
    return "%spromoted/pay/%s/%s" % (g.payment_domain, l._id36, campaign._id36)

def view_live_url(l, srname):
    url = get_domain(cname=False, subreddit=False)
    if srname:
        url += '/r/%s' % srname
    return 'http://%s/?ad=%s' % (url, l._fullname)


def refund_url(link, campaign):
    return "%spromoted/refund/%s/%s" % (g.payment_domain, link._id36,
                                        campaign._id36)


# booleans

def is_promo(link):
    return (link and not link._deleted and link.promoted is not None
            and hasattr(link, "promote_status"))

def is_accepted(link):
    return (is_promo(link) and
            link.promote_status != PROMOTE_STATUS.rejected and
            link.promote_status >= PROMOTE_STATUS.accepted)

def is_unpaid(link):
    return is_promo(link) and link.promote_status == PROMOTE_STATUS.unpaid

def is_unapproved(link):
    return is_promo(link) and link.promote_status <= PROMOTE_STATUS.unseen

def is_rejected(link):
    return is_promo(link) and link.promote_status == PROMOTE_STATUS.rejected

def is_promoted(link):
    return is_promo(link) and link.promote_status == PROMOTE_STATUS.promoted

def is_finished(link):
    return is_promo(link) and link.promote_status == PROMOTE_STATUS.finished

def is_live_on_sr(link, sr):
    return bool(live_campaigns_by_link(link, sr=sr))


def update_promote_status(link, status):
    set_promote_status(link, status)
    hooks.get_hook('promote.edit_promotion').call(link=link)


def new_promotion(title, url, selftext, user, ip):
    """
    Creates a new promotion with the provided title, etc, and sets it
    status to be 'unpaid'.
    """
    sr = Subreddit._byID(get_promote_srid())
    l = Link._submit(title, url, user, sr, ip)
    l.promoted = True
    l.disable_comments = False
    l.sendreplies = True
    PromotionLog.add(l, 'promotion created')

    if url == 'self':
        l.url = l.make_permalink_slow()
        l.is_self = True
        l.selftext = selftext

    l._commit()

    update_promote_status(l, PROMOTE_STATUS.unpaid)

    # the user has posted a promotion, so enable the promote menu unless
    # they have already opted out
    if user.pref_show_promote is not False:
        user.pref_show_promote = True
        user._commit()

    # notify of new promo
    emailer.new_promo(l)
    return l


def get_transactions(link, campaigns):
    """Return Bids for specified campaigns on the link.

    A PromoCampaign can have several bids associated with it, but the most
    recent one is recorded on the trans_id attribute. This is the one that will
    be returned.

    """

    campaigns = [c for c in campaigns if (c.trans_id != 0
                                          and c.link_id == link._id)]
    if not campaigns:
        return {}

    bids = Bid.lookup(thing_id=link._id)
    bid_dict = {(b.campaign, b.transaction): b for b in bids}
    bids_by_campaign = {c._id: bid_dict[(c._id, c.trans_id)] for c in campaigns}
    return bids_by_campaign

def new_campaign(link, dates, bid, cpm, sr, priority, location):
    # empty string for sr_name means target to all
    sr_name = sr.name if sr else ""
    campaign = PromoCampaign._new(link, sr_name, bid, cpm, dates[0], dates[1],
                                  priority, location)
    PromotionWeights.add(link, campaign._id, sr_name, dates[0], dates[1], bid)
    PromotionLog.add(link, 'campaign %s created' % campaign._id)

    if campaign.priority.cpm:
        author = Account._byID(link.author_id, data=True)
        if getattr(author, "complimentary_promos", False):
            free_campaign(link, campaign, c.user)

    hooks.get_hook('promote.new_campaign').call(link=link, campaign=campaign)
    return campaign


def free_campaign(link, campaign, user):
    auth_campaign(link, campaign, user, -1)

def edit_campaign(link, campaign, dates, bid, cpm, sr, priority, location):
    sr_name = sr.name if sr else '' # empty string means target to all

    changed = {}
    if bid != campaign.bid:
        changed['bid'] = ("$%0.2f" % campaign.bid, "$%0.2f" % bid)
    if dates[0] != campaign.start_date or dates[1] != campaign.end_date:
        original = '%s to %s' % (campaign.start_date, campaign.end_date)
        edited = '%s to %s' % (dates[0], dates[1])
        changed['dates'] = (original, edited)
    if cpm != campaign.cpm:
        changed['cpm'] = (campaign.cpm, cpm)
    if sr_name != campaign.sr_name:
        format_sr_name = (lambda sr_name: '/r/%s' % sr_name if sr_name
                                                            else '<frontpage>')
        changed['sr_name'] = map(format_sr_name, (campaign.sr_name, sr_name))
    if priority != campaign.priority:
        changed['priority'] = (campaign.priority.name, priority.name)

    change_strs = map(lambda t: '%s: %s -> %s' % (t[0], t[1][0], t[1][1]),
                      changed.iteritems())
    change_text = ', '.join(change_strs)

    # if the bid amount changed, cancel any pending transactions
    if campaign.bid != bid:
        void_campaign(link, campaign)

    # update the schedule
    PromotionWeights.reschedule(link, campaign._id, sr_name,
                                dates[0], dates[1], bid)

    # update values in the db
    campaign.update(dates[0], dates[1], bid, cpm, sr_name,
                    campaign.trans_id, priority, location, commit=True)

    if campaign.priority.cpm:
        # make it a freebie, if applicable
        author = Account._byID(link.author_id, True)
        if getattr(author, "complimentary_promos", False):
            free_campaign(link, campaign, c.user)

    # record the changes
    if change_text:
        PromotionLog.add(link, 'edited %s: %s' % (campaign, change_text))

    hooks.get_hook('promote.edit_campaign').call(link=link, campaign=campaign)


def terminate_campaign(link, campaign):
    if not is_live_promo(link, campaign):
        return

    now = promo_datetime_now()
    original_end = campaign.end_date
    dates = [campaign.start_date, now]
    sr = Subreddit._by_name(campaign.sr_name) if campaign.sr_name else None

    # NOTE: this will delete PromotionWeights after and including now.date()
    edit_campaign(link, campaign, dates, campaign.bid, campaign.cpm, sr,
                  campaign.priority, campaign.location)

    update_promote_status(link, PROMOTE_STATUS.finished)
    all_live_promo_srnames(_update=True)

    msg = 'terminated campaign %s (original end %s)' % (campaign._id,
                                                        original_end.date())
    PromotionLog.add(link, msg)


def delete_campaign(link, campaign):
    PromotionWeights.delete_unfinished(link, campaign._id)
    void_campaign(link, campaign)
    campaign.delete()
    PromotionLog.add(link, 'deleted campaign %s' % campaign._id)
    hooks.get_hook('promote.delete_campaign').call(link=link, campaign=campaign)

def void_campaign(link, campaign):
    transactions = get_transactions(link, [campaign])
    bid_record = transactions.get(campaign._id)
    if bid_record:
        a = Account._byID(link.author_id)
        authorize.void_transaction(a, bid_record.transaction, campaign._id)
        campaign.trans_id = NO_TRANSACTION
        campaign._commit()
        text = ('voided transaction for %s: (trans_id: %d)'
                % (campaign, bid_record.transaction))
        PromotionLog.add(link, text)


def auth_campaign(link, campaign, user, pay_id):
    """
    Authorizes (but doesn't charge) a bid with authorize.net.
    Args:
    - link: promoted link
    - campaign: campaign to be authorized
    - user: Account obj of the user doing the auth (usually the currently
        logged in user)
    - pay_id: customer payment profile id to use for this transaction. (One
        user can have more than one payment profile if, for instance, they have
        more than one credit card on file.) Set pay_id to -1 for freebies.

    Returns: (True, "") if successful or (False, error_msg) if not. 
    """
    void_campaign(link, campaign)
    test = 1 if g.debug else None
    trans_id, reason = authorize.auth_transaction(campaign.bid, user, pay_id,
                                                  link, campaign._id, test=test)

    if trans_id and not reason:
        text = ('updated payment and/or bid for campaign %s: '
                'SUCCESS (trans_id: %d, amt: %0.2f)' % (campaign._id, trans_id,
                                                        campaign.bid))
        PromotionLog.add(link, text)
        if trans_id < 0:
            PromotionLog.add(link, 'FREEBIE (campaign: %s)' % campaign._id)

        if trans_id:
            if is_finished(link):
                # When a finished promo gets a new paid campaign it doesn't
                # need to go through approval again and is marked accepted
                new_status = PROMOTE_STATUS.accepted
            else:
                new_status = max(PROMOTE_STATUS.unseen, link.promote_status)
        else:
            new_status = max(PROMOTE_STATUS.unpaid, link.promote_status)
        update_promote_status(link, new_status)

        if user and (user._id == link.author_id) and trans_id > 0:
            emailer.promo_bid(link, campaign.bid, campaign.start_date)

    else:
        # something bad happend.
        text = ("updated payment and/or bid for campaign %s: FAILED ('%s')"
                % (campaign._id, reason))
        PromotionLog.add(link, text)
        trans_id = 0

    campaign.trans_id = trans_id
    campaign._commit()

    return bool(trans_id), reason



# dates are referenced to UTC, while we want promos to change at (roughly)
# midnight eastern-US.
# TODO: make this a config parameter
timezone_offset = -5 # hours
timezone_offset = timedelta(0, timezone_offset * 3600)
def promo_datetime_now(offset=None):
    now = datetime.now(g.tz) + timezone_offset
    if offset is not None:
        now += timedelta(offset)
    return now


def accept_promotion(link):
    update_promote_status(link, PROMOTE_STATUS.accepted)

    if link._spam:
        link._spam = False
        link._commit()

    emailer.accept_promo(link)

    # if the link has campaigns running now charge them and promote the link
    now = promo_datetime_now()
    campaigns = list(PromoCampaign._by_link(link._id))
    is_live = False
    for camp in campaigns:
        if is_accepted_promo(now, link, camp):
            charge_campaign(link, camp)
            if charged_or_not_needed(camp):
                promote_link(link, camp)
                is_live = True

    if is_live:
        all_live_promo_srnames(_update=True)


def reject_promotion(link, reason=None):
    was_live = is_promoted(link)
    update_promote_status(link, PROMOTE_STATUS.rejected)

    # Send a rejection email (unless the advertiser requested the reject)
    if not c.user or c.user._id != link.author_id:
        emailer.reject_promo(link, reason=reason)

    if was_live:
        all_live_promo_srnames(_update=True)


def unapprove_promotion(link):
    if is_unpaid(link):
        return
    elif is_finished(link):
        # when a finished promo is edited it is bumped down to unpaid so if it
        # eventually gets a paid campaign it can get upgraded to unseen and
        # reviewed
        update_promote_status(link, PROMOTE_STATUS.unpaid)
    else:
        update_promote_status(link, PROMOTE_STATUS.unseen)


def authed_or_not_needed(campaign):
    authed = campaign.trans_id != NO_TRANSACTION
    needs_auth = campaign.priority.cpm
    return authed or not needs_auth


def charged_or_not_needed(campaign):
    # True if a campaign has a charged transaction or doesn't need one
    charged = authorize.is_charged_transaction(campaign.trans_id, campaign._id)
    needs_charge = campaign.priority.cpm
    return charged or not needs_charge


def is_accepted_promo(date, link, campaign):
    return (campaign.start_date <= date < campaign.end_date and
            is_accepted(link) and
            authed_or_not_needed(campaign))


def is_scheduled_promo(date, link, campaign):
    return (is_accepted_promo(date, link, campaign) and 
            charged_or_not_needed(campaign))


def is_live_promo(link, campaign):
    now = promo_datetime_now()
    return is_promoted(link) and is_scheduled_promo(now, link, campaign)


def get_promos(date, sr_names=None, link=None):
    pws = PromotionWeights.get_campaigns(date, sr_names=sr_names, link=link)
    campaign_ids = {pw.promo_idx for pw in pws}
    campaigns = PromoCampaign._byID(campaign_ids, data=True, return_dict=False)
    link_ids = {camp.link_id for camp in campaigns}
    links = Link._byID(link_ids, data=True)
    for camp in campaigns:
        yield camp, links[camp.link_id]


def get_accepted_promos(offset=0):
    date = promo_datetime_now(offset=offset)
    for camp, link in get_promos(date):
        if is_accepted_promo(date, link, camp):
            yield camp, link


def get_scheduled_promos(offset=0):
    date = promo_datetime_now(offset=offset)
    for camp, link in get_promos(date):
        if is_scheduled_promo(date, link, camp):
            yield camp, link


def charge_campaign(link, campaign):
    if charged_or_not_needed(campaign):
        return

    user = Account._byID(link.author_id)
    charge_succeeded = authorize.charge_transaction(user, campaign.trans_id,
                                                    campaign._id)

    if not charge_succeeded:
        return

    hooks.get_hook('promote.edit_campaign').call(link=link, campaign=campaign)

    if not is_promoted(link):
        update_promote_status(link, PROMOTE_STATUS.pending)

    emailer.queue_promo(link, campaign.bid, campaign.trans_id)
    text = ('auth charge for campaign %s, trans_id: %d' %
            (campaign._id, campaign.trans_id))
    PromotionLog.add(link, text)


def charge_pending(offset=1):
    for camp, link in get_accepted_promos(offset=offset):
        charge_campaign(link, camp)


def live_campaigns_by_link(link, sr=None):
    if not is_promoted(link):
        return []

    if sr:
        sr_names = [''] if isinstance(sr, DefaultSR) else [sr.name]
    else:
        sr_names = None

    now = promo_datetime_now()
    return [camp for camp, link in get_promos(now, sr_names=sr_names,
                                              link=link)
            if is_live_promo(link, camp)]


def promote_link(link, campaign):
    if (not link.over_18 and
        not link.over_18_override and
        campaign.sr_name and Subreddit._by_name(campaign.sr_name).over_18):
        link.over_18 = True
        link._commit()

    if not is_promoted(link):
        update_promote_status(link, PROMOTE_STATUS.promoted)
        emailer.live_promo(link)


def make_daily_promotions():
    # charge campaigns so they can go live
    charge_pending(offset=0)
    charge_pending(offset=1)

    # promote links and record ids of promoted links
    link_ids = set()
    for campaign, link in get_scheduled_promos(offset=0):
        link_ids.add(link._id)
        promote_link(link, campaign)

    # expire finished links
    q = Link._query(Link.c.promote_status == PROMOTE_STATUS.promoted, data=True)
    q = q._filter(not_(Link.c._id.in_(link_ids)))
    for link in q:
        update_promote_status(link, PROMOTE_STATUS.finished)
        emailer.finished_promo(link)

    # update subreddits with promos
    all_live_promo_srnames(_update=True)

    _mark_promos_updated()
    finalize_completed_campaigns(daysago=1)
    hooks.get_hook('promote.make_daily_promotions').call(offset=0)


def finalize_completed_campaigns(daysago=1):
    # PromoCampaign.end_date is utc datetime with year, month, day only
    now = datetime.now(g.tz)
    date = now - timedelta(days=daysago)
    date = date.replace(hour=0, minute=0, second=0, microsecond=0)

    q = PromoCampaign._query(PromoCampaign.c.end_date == date,
                             # exclude no transaction and freebies
                             PromoCampaign.c.trans_id > 0,
                             data=True)
    campaigns = list(q)

    if not campaigns:
        return

    # check that traffic is up to date
    earliest_campaign = min(campaigns, key=lambda camp: camp.start_date)
    start, end = get_total_run(earliest_campaign)
    missing_traffic = traffic.get_missing_traffic(start.replace(tzinfo=None),
                                                  date.replace(tzinfo=None))
    if missing_traffic:
        raise ValueError("Can't finalize campaigns finished on %s."
                         "Missing traffic from %s" % (date, missing_traffic))

    links = Link._byID([camp.link_id for camp in campaigns], data=True)
    underdelivered_campaigns = []

    for camp in campaigns:
        if hasattr(camp, 'refund_amount'):
            continue

        link = links[camp.link_id]
        billable_impressions = get_billable_impressions(camp)
        billable_amount = get_billable_amount(camp, billable_impressions)

        if billable_amount >= camp.bid:
            if hasattr(camp, 'cpm'):
                text = '%s completed with $%s billable (%s impressions @ $%s).'
                text %= (camp, billable_amount, billable_impressions, camp.cpm)
            else:
                text = '%s completed with $%s billable (pre-CPM).'
                text %= (camp, billable_amount) 
            PromotionLog.add(link, text)
            camp.refund_amount = 0.
            camp._commit()
        else:
            underdelivered_campaigns.append(camp)

        if underdelivered_campaigns:
            set_underdelivered_campaigns(underdelivered_campaigns)


def get_refund_amount(camp, billable):
    existing_refund = getattr(camp, 'refund_amount', 0.)
    charge = camp.bid - existing_refund
    refund_amount = charge - billable
    refund_amount = Decimal(str(refund_amount)).quantize(Decimal('.01'),
                                                    rounding=ROUND_UP)
    return max(float(refund_amount), 0.)


def refund_campaign(link, camp, billable_amount, billable_impressions):
    refund_amount = get_refund_amount(camp, billable_amount)
    if refund_amount <= 0:
        return

    owner = Account._byID(camp.owner_id, data=True)
    try:
        success = authorize.refund_transaction(owner, camp.trans_id,
                                               camp._id, refund_amount)
    except authorize.AuthorizeNetException as e:
        text = ('%s $%s refund failed' % (camp, refund_amount))
        PromotionLog.add(link, text)
        g.log.debug(text + ' (response: %s)' % e)
        return

    text = ('%s completed with $%s billable (%s impressions @ $%s).'
            ' %s refunded.' % (camp, billable_amount,
                               billable_impressions, camp.cpm,
                               refund_amount))
    PromotionLog.add(link, text)
    camp.refund_amount = refund_amount
    camp._commit()
    unset_underdelivered_campaigns(camp)
    emailer.refunded_promo(link)


PromoTuple = namedtuple('PromoTuple', ['link', 'weight', 'campaign'])


@memoize('all_live_promo_srnames')
def all_live_promo_srnames():
    now = promo_datetime_now()
    return {camp.sr_name for camp, link in get_promos(now)
            if is_live_promo(link, camp)}


def srnames_from_site(user, site):
    if not isinstance(site, FakeSubreddit):
        srnames = {site.name}
    elif isinstance(site, MultiReddit):
        srnames = {sr.name for sr in site.srs}
    elif user and not isinstance(user, FakeAccount):
        srnames = {sr.name for sr in Subreddit.user_subreddits(user, ids=False)}
        srnames.add('')
    else:
        srnames = {sr.name for sr in Subreddit.user_subreddits(None, ids=False)}
        srnames.add('')
    return srnames


def srnames_with_live_promos(user, site):
    site_srnames = srnames_from_site(user, site)
    promo_srnames = all_live_promo_srnames()
    return promo_srnames.intersection(site_srnames)


def _get_live_promotions(sr_names):
    now = promo_datetime_now()
    ret = {sr_name: [] for sr_name in sr_names}
    for camp, link in get_promos(now, sr_names=sr_names):
        if is_live_promo(link, camp):
            weight = (camp.bid / camp.ndays)
            pt = PromoTuple(link=link._fullname, weight=weight,
                            campaign=camp._fullname)
            ret[camp.sr_name].append(pt)
    return ret


def get_live_promotions(sr_names):
    promos_by_srname = sgm(g.cache, sr_names, miss_fn=_get_live_promotions,
                           prefix='live_promotions', time=60)
    return itertools.chain.from_iterable(promos_by_srname.itervalues())


def lottery_promoted_links(sr_names, n=10):
    """Run weighted_lottery to order and choose a subset of promoted links."""
    promo_tuples = get_live_promotions(sr_names)

    # house priority campaigns have weight of 0, use some small value
    # so they'll show if there are no other campaigns
    weights = {p: p.weight or 0.001 for p in promo_tuples}
    selected = []
    while weights and len(selected) < n:
        s = weighted_lottery(weights)
        del weights[s]
        selected.append(s)
    return selected


def get_total_run(thing):
    """Return the total time span this link or campaign will run.

    Starts at the start date of the earliest campaign and goes to the end date
    of the latest campaign.

    """

    if isinstance(thing, Link):
        campaigns = PromoCampaign._by_link(thing._id)
    elif isinstance(thing, PromoCampaign):
        campaigns = [thing]

    earliest = None
    latest = None
    for campaign in campaigns:
        if not charged_or_not_needed(campaign):
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
    earliest = earliest.replace(tzinfo=g.tz) - timezone_offset
    latest = latest.replace(tzinfo=g.tz) - timezone_offset

    return earliest, latest


def get_traffic_dates(thing):
    """Retrieve the start and end of a Promoted Link or PromoCampaign."""
    now = datetime.now(g.tz).replace(minute=0, second=0, microsecond=0)
    start, end = get_total_run(thing)
    end = min(now, end)
    return start, end


def get_billable_impressions(campaign):
    start, end = get_traffic_dates(campaign)
    if start > datetime.now(g.tz):
        return 0

    traffic_lookup = traffic.TargetedImpressionsByCodename.promotion_history
    imps = traffic_lookup(campaign._fullname, start.replace(tzinfo=None),
                          end.replace(tzinfo=None))
    billable_impressions = sum(imp for date, (imp,) in imps)
    return billable_impressions


def get_billable_amount(camp, impressions):
    if hasattr(camp, 'cpm'):
        value_delivered = impressions / 1000. * camp.cpm / 100.
        billable_amount = min(camp.bid, value_delivered)
    else:
        # pre-CPM campaigns are charged in full regardless of impressions
        billable_amount = camp.bid

    billable_amount = Decimal(str(billable_amount)).quantize(Decimal('.01'),
                                                        rounding=ROUND_DOWN)
    return float(billable_amount)


def get_spent_amount(campaign):
    if hasattr(campaign, 'refund_amount'):
        # no need to calculate spend if we've already refunded
        spent = campaign.bid - campaign.refund_amount
    elif not hasattr(campaign, 'cpm'):
        # pre-CPM campaign
        return campaign.bid
    else:
        billable_impressions = get_billable_impressions(campaign)
        spent = get_billable_amount(campaign, billable_impressions)
    return spent


def Run(verbose=True):
    """reddit-job-update_promos: Intended to be run hourly to pull in
    scheduled changes to ads

    """

    if verbose:
        print "promote.py:Run() - make_daily_promotions()"

    make_daily_promotions()

    if verbose:
        print "promote.py:Run() - finished"
