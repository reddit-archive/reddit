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
from datetime import datetime, timedelta

from babel.numbers import format_number
import json
import urllib

from pylons import c, g, request
from pylons.i18n import _, N_

from r2.controllers.api import ApiController
from r2.controllers.listingcontroller import ListingController
from r2.controllers.reddit_base import RedditController

from r2.lib import cssfilter, inventory, promote
from r2.lib.authorize import get_account_info, edit_profile, PROFILE_LIMIT
from r2.lib.db import queries
from r2.lib.errors import errors
from r2.lib.media import force_thumbnail, thumbnail_url
from r2.lib.memoize import memoize
from r2.lib.menus import NamedButton, NavButton, NavMenu
from r2.lib.pages import (
    LinkInfoPage,
    PaymentForm,
    PromoteInventory,
    PromotePage,
    PromoteLinkForm,
    PromoteLinkNew,
    PromoteReport,
    Reddit,
    RefundPage,
    RenderableCampaign,
    Roadblocks,
    UploadedImage,
)
from r2.lib.pages.things import wrap_links
from r2.lib.system_messages import user_added_messages
from r2.lib.utils import make_offset_date, to_date, to36
from r2.lib.validator import (
    json_validate,
    nop,
    noresponse,
    VAccountByName,
    ValidAddress,
    validate,
    validatedForm,
    ValidCard,
    ValidIP,
    VBid,
    VBoolean,
    VByName,
    VDate,
    VDateRange,
    VExistingUname,
    VFloat,
    VImageType,
    VInt,
    VLength,
    VLink,
    VLocation,
    VModhash,
    VOneOf,
    VPriority,
    VPromoCampaign,
    VRatelimit,
    VSelfText,
    VShamedDomain,
    VSponsor,
    VSponsorAdmin,
    VSponsorAdminOrAdminSecret,
    VSubmitSR,
    VTitle,
    VUploadLength,
    VUrl,
)
from r2.models import (
    Account,
    calc_impressions,
    Frontpage,
    get_promote_srid,
    Link,
    Message,
    NotFound,
    PromoCampaign,
    PromotionLog,
    PromotionWeights,
    PromotedLinkRoadblock,
    Subreddit,
)


def campaign_has_oversold_error(form, campaign):
    if campaign.priority.inventory_override:
        return

    target = Subreddit._by_name(campaign.sr_name) if campaign.sr_name else None
    return has_oversold_error(form, campaign, campaign.start_date,
                              campaign.end_date, campaign.bid, campaign.cpm,
                              target, campaign.location)


def has_oversold_error(form, campaign, start, end, bid, cpm, target, location):
    ndays = (to_date(end) - to_date(start)).days
    total_request = calc_impressions(bid, cpm)
    daily_request = int(total_request / ndays)
    oversold = inventory.get_oversold(target or Frontpage, start, end,
                                      daily_request, ignore=campaign,
                                      location=location)

    if oversold:
        min_daily = min(oversold.values())
        available = min_daily * ndays
        msg_params = {
            'available': format_number(available, locale=c.locale),
            'target': target.name if target else 'the frontpage',
            'start': start.strftime('%m/%d/%Y'),
            'end': end.strftime('%m/%d/%Y'),
        }
        c.errors.add(errors.OVERSOLD_DETAIL, field='bid',
                     msg_params=msg_params)
        form.has_errors('bid', errors.OVERSOLD_DETAIL)
        return True


class PromoteController(RedditController):
    @validate(VSponsor())
    def GET_new_promo(self):
        return PromotePage(title=_("create sponsored link"),
                           content=PromoteLinkNew()).render()

    @validate(VSponsor('link'),
              link=VLink('link'))
    def GET_edit_promo(self, link):
        if not link or link.promoted is None:
            return self.abort404()
        rendered = wrap_links(link, skip=False)
        form = PromoteLinkForm(link, rendered)
        page = Reddit(title=_("edit sponsored link"), content=form,
                      show_sidebar=False, extension_handling=False)
        return page.render()

    # admin only because the route might change
    @validate(VSponsorAdmin('campaign'),
              campaign=VPromoCampaign('campaign'))
    def GET_edit_promo_campaign(self, campaign):
        if not campaign:
            return self.abort404()
        link = Link._byID(campaign.link_id)
        return self.redirect(promote.promo_edit_url(link))

    @validate(VSponsorAdmin(),
              link=VLink("link"),
              campaign=VPromoCampaign("campaign"))
    def GET_refund(self, link, campaign):
        if campaign.link_id != link._id:
            return self.abort404()

        content = RefundPage(link, campaign)
        return Reddit("refund", content=content, show_sidebar=False).render()

    @validate(VSponsorAdmin())
    def GET_roadblock(self):
        return PromotePage(title=_("manage roadblocks"),
                           content=Roadblocks()).render()

    @validate(VSponsor("link"),
              link=VLink("link"),
              campaign=VPromoCampaign("campaign"))
    def GET_pay(self, link, campaign):
        # no need for admins to play in the credit card area
        if c.user_is_loggedin and c.user._id != link.author_id:
            return self.abort404()

        if not campaign.link_id == link._id:
            return self.abort404()
        if g.authorizenetapi:
            data = get_account_info(c.user)
            content = PaymentForm(link, campaign,
                                  customer_id=data.customerProfileId,
                                  profiles=data.paymentProfiles,
                                  max_profiles=PROFILE_LIMIT)
        else:
            content = None
        res = LinkInfoPage(link=link,
                            content=content,
                            show_sidebar=False)
        return res.render()

    @validate(VSponsorAdminOrAdminSecret('secret'),
              start=VDate('startdate'),
              end=VDate('enddate'),
              link_text=nop('link_text'),
              owner=VAccountByName('owner'))
    def GET_report(self, start, end, link_text=None, owner=None):
        now = datetime.now(g.tz).replace(hour=0, minute=0, second=0,
                                         microsecond=0)
        end = end or now - timedelta(days=1)
        start = start or end - timedelta(days=7)

        links = []
        bad_links = []
        owner_name = owner.name if owner else ''

        if owner:
            promo_weights = PromotionWeights.get_campaigns(start, end,
                                                           author_id=owner._id)
            campaign_ids = [pw.promo_idx for pw in promo_weights]
            campaigns = PromoCampaign._byID(campaign_ids, data=True)
            link_ids = {camp.link_id for camp in campaigns.itervalues()}
            links.extend(Link._byID(link_ids, data=True, return_dict=False))

        if link_text is not None:
            id36s = link_text.replace(',', ' ').split()
            try:
                links_from_text = Link._byID36(id36s, data=True)
            except NotFound:
                links_from_text = {}

            bad_links = [id36 for id36 in id36s if id36 not in links_from_text]
            links.extend(links_from_text.values())

        content = PromoteReport(links, link_text, owner_name, bad_links, start,
                                end)
        if c.render_style == 'csv':
            return content.as_csv()
        else:
            return PromotePage(title=_("sponsored link report"),
                               content=content).render()

    @validate(
        VSponsorAdmin(),
        start=VDate('startdate', reference_date=promote.promo_datetime_now),
        end=VDate('enddate', reference_date=promote.promo_datetime_now),
        sr_name=nop('sr_name'),
    )
    def GET_promote_inventory(self, start, end, sr_name):
        if not start or not end:
            start = promote.promo_datetime_now(offset=1).date()
            end = promote.promo_datetime_now(offset=8).date()
            c.errors.remove((errors.BAD_DATE, 'startdate'))
            c.errors.remove((errors.BAD_DATE, 'enddate'))

        sr = Frontpage
        if sr_name:
            try:
                sr = Subreddit._by_name(sr_name)
            except NotFound:
                c.errors.add(errors.SUBREDDIT_NOEXIST, field='sr_name')

        content = PromoteInventory(start, end, sr)
        return PromotePage(title=_("sponsored link inventory"),
                           content=content).render()


class PromoteListingController(ListingController):
    where = 'promoted'
    render_cls = PromotePage
    titles = {
        'future_promos': N_('unapproved promoted links'),
        'pending_promos': N_('accepted promoted links'),
        'unpaid_promos': N_('unpaid promoted links'),
        'rejected_promos': N_('rejected promoted links'),
        'live_promos': N_('live promoted links'),
        'underdelivered': N_('underdelivered promoted links'),
        'reported': N_('reported promoted links'),
        'house': N_('house promoted links'),
        'all': N_('all promoted links'),
    }

    def title(self):
        return _(self.titles[self.sort])

    @property
    def title_text(self):
        return _('promoted by you')

    @classmethod
    @memoize('live_by_subreddit', time=300)
    def _live_by_subreddit(cls, sr_names):
        promotuples = promote.get_live_promotions(sr_names)
        return [pt.link for pt in promotuples]

    def live_by_subreddit(cls, sr):
        sr_names = [''] if sr == Frontpage else [sr.name]
        return cls._live_by_subreddit(sr_names)

    @classmethod
    @memoize('house_link_names', time=60)
    def get_house_link_names(cls):
        now = promote.promo_datetime_now()
        pws = PromotionWeights.get_campaigns(now)
        campaign_ids = {pw.promo_idx for pw in pws}
        q = PromoCampaign._query(PromoCampaign.c._id.in_(campaign_ids),
                                 PromoCampaign.c.priority_name == 'house',
                                 data=True)
        return [Link._fullname_from_id36(to36(camp.link_id)) for camp in q]

    @property
    def menus(self):
        filters = [
            NamedButton('all_promos', dest=''),
            NamedButton('future_promos'),
            NamedButton('unpaid_promos'),
            NamedButton('rejected_promos'),
            NamedButton('pending_promos'),
            NamedButton('live_promos'),
        ]
        menus = [NavMenu(filters, base_path='/promoted', title='show',
                        type='lightdrop')]

        if self.sort == 'live_promos' and c.user_is_sponsor:
            srnames = promote.all_live_promo_srnames()
            buttons = [NavButton('all', '')]
            try:
                srnames.remove('')
                frontbutton = NavButton('FRONTPAGE', Frontpage.name,
                                        aliases=['/promoted/live_promos/%s' %
                                                 urllib.quote(Frontpage.name)])
                buttons.append(frontbutton)
            except KeyError:
                pass

            srnames = sorted(srnames, key=lambda name: name.lower())
            buttons.extend([NavButton(name, name) for name in srnames])
            menus.append(NavMenu(buttons, base_path='/promoted/live_promos',
                                 title='subreddit', type='lightdrop'))

        return menus

    def keep_fn(self):
        def keep(item):
            if self.sort == "future_promos":
                # this sort is used to review links that need to be approved
                # skip links that don't have any paid campaigns
                campaigns = list(PromoCampaign._by_link(item._id))
                if not any(promote.authed_or_not_needed(camp)
                           for camp in campaigns):
                    return False

            if item.promoted and not item._deleted:
                return True
            else:
                return False
        return keep

    def query(self):
        if c.user_is_sponsor:
            if self.sort == "future_promos":
                return queries.get_all_unapproved_links()
            elif self.sort == "pending_promos":
                return queries.get_all_accepted_links()
            elif self.sort == "unpaid_promos":
                return queries.get_all_unpaid_links()
            elif self.sort == "rejected_promos":
                return queries.get_all_rejected_links()
            elif self.sort == "live_promos" and self.sr:
                return self.live_by_subreddit(self.sr)
            elif self.sort == 'live_promos':
                return queries.get_all_live_links()
            elif self.sort == 'underdelivered':
                q = queries.get_underdelivered_campaigns()
                campaigns = PromoCampaign._by_fullname(list(q), data=True,
                                                       return_dict=False)
                link_ids = [camp.link_id for camp in campaigns]
                return [Link._fullname_from_id36(to36(id)) for id in link_ids]
            elif self.sort == 'reported':
                return queries.get_reported_links(get_promote_srid())
            elif self.sort == 'house':
                return self.get_house_link_names()
            elif self.sort == 'all':
                return queries.get_all_promoted_links()
        else:
            if self.sort == "future_promos":
                return queries.get_unapproved_links(c.user._id)
            elif self.sort == "pending_promos":
                return queries.get_accepted_links(c.user._id)
            elif self.sort == "unpaid_promos":
                return queries.get_unpaid_links(c.user._id)
            elif self.sort == "rejected_promos":
                return queries.get_rejected_links(c.user._id)
            elif self.sort == "live_promos":
                return queries.get_live_links(c.user._id)
            elif self.sort == "all":
                return queries.get_promoted_links(c.user._id)

    @validate(VSponsor(),
              sr=nop('sr'))
    def GET_listing(self, sr=None, sort="all", **env):
        if not c.user_is_loggedin or not c.user.email_verified:
            # never reached--see MinimalController.on_validation_error
            return self.redirect("/ad_inq")
        self.sort = sort
        self.sr = None
        if sr and sr == Frontpage.name:
            self.sr = Frontpage
        elif sr:
            try:
                self.sr = Subreddit._by_name(sr)
            except NotFound:
                pass
        return ListingController.GET_listing(self, **env)


class PromoteApiController(ApiController):
    @json_validate(sr=VSubmitSR('sr', promotion=True),
                   location=VLocation(),
                   start=VDate('startdate'),
                   end=VDate('enddate'))
    def GET_check_inventory(self, responder, sr, location, start, end):
        sr = sr or Frontpage
        if not location or not location.country:
            available = inventory.get_available_pageviews(sr, start, end,
                                                          datestr=True)
        else:
            available = inventory.get_available_pageviews_geotargeted(sr,
                            location, start, end, datestr=True)
        return {'inventory': available}

    @validatedForm(VSponsorAdmin(),
                   VModhash(),
                   link=VLink("link_id36"),
                   campaign=VPromoCampaign("campaign_id36"))
    def POST_freebie(self, form, jquery, link, campaign):
        if campaign_has_oversold_error(form, campaign):
            form.set_html(".freebie", "target oversold, can't freebie")
            return

        if promote.is_promo(link) and campaign:
            promote.free_campaign(link, campaign, c.user)
            form.redirect(promote.promo_edit_url(link))

    @validatedForm(VSponsorAdmin(),
                   VModhash(),
                   link=VByName("link"),
                   note=nop("note"))
    def POST_promote_note(self, form, jquery, link, note):
        if promote.is_promo(link):
            text = PromotionLog.add(link, note)
            form.find(".notes").children(":last").after(
                "<p>" + text + "</p>")


    @noresponse(VSponsorAdmin(),
                VModhash(),
                thing=VByName('id'))
    def POST_promote(self, thing):
        if promote.is_promo(thing):
            promote.accept_promotion(thing)

    @noresponse(VSponsorAdmin(),
                VModhash(),
                thing=VByName('id'),
                reason=nop("reason"))
    def POST_unpromote(self, thing, reason):
        if promote.is_promo(thing):
            promote.reject_promotion(thing, reason=reason)

    @validatedForm(VSponsorAdmin(),
                   VModhash(),
                   link=VLink('link'),
                   campaign=VPromoCampaign('campaign'))
    def POST_refund_campaign(self, form, jquery, link, campaign):
        billable_impressions = promote.get_billable_impressions(campaign)
        billable_amount = promote.get_billable_amount(campaign,
                                                      billable_impressions)
        refund_amount = promote.get_refund_amount(campaign, billable_amount)
        if refund_amount > 0:
            promote.refund_campaign(link, campaign, billable_amount,
                                    billable_impressions)
            form.set_html('.status', _('refund succeeded'))
        else:
            form.set_html('.status', _('refund not needed'))

    @validatedForm(VSponsor('link_id36'),
                   VModhash(),
                   VRatelimit(rate_user=True,
                              rate_ip=True,
                              prefix='create_promo_'),
                   VShamedDomain('url'),
                   username=VLength('username', 100, empty_error=None),
                   l=VLink('link_id36'),
                   title=VTitle('title'),
                   url=VUrl('url', allow_self=False),
                   selftext=VSelfText('text'),
                   kind=VOneOf('kind', ['link', 'self']),
                   ip=ValidIP(),
                   disable_comments=VBoolean("disable_comments"),
                   sendreplies=VBoolean("sendreplies"),
                   media_width=VInt("media-width", min=0),
                   media_height=VInt("media-height", min=0),
                   media_embed=VLength("media-embed", 1000),
                   media_override=VBoolean("media-override"),
                   domain_override=VLength("domain", 100)
                   )
    def POST_edit_promo(self, form, jquery, ip, username, l, title, url,
                        selftext, kind, disable_comments, sendreplies, media_height,
                        media_width, media_embed, media_override, domain_override):

        should_ratelimit = False
        if not c.user_is_sponsor:
            should_ratelimit = True

        if not should_ratelimit:
            c.errors.remove((errors.RATELIMIT, 'ratelimit'))

        # check for user override
        if not l and c.user_is_sponsor and username:
            try:
                user = Account._by_name(username)
            except NotFound:
                c.errors.add(errors.USER_DOESNT_EXIST, field="username")
                form.set_error(errors.USER_DOESNT_EXIST, "username")
                return

            if not user.email:
                c.errors.add(errors.NO_EMAIL_FOR_USER, field="username")
                form.set_error(errors.NO_EMAIL_FOR_USER, "username")
                return

            if not user.email_verified:
                c.errors.add(errors.NO_VERIFIED_EMAIL, field="username")
                form.set_error(errors.NO_VERIFIED_EMAIL, "username")
                return
        else:
            user = c.user

        # check for shame banned domains
        if form.has_errors("url", errors.DOMAIN_BANNED):
            g.stats.simple_event('spam.shame.link')
            return

        # demangle URL in canonical way
        if url:
            if isinstance(url, (unicode, str)):
                form.set_inputs(url=url)
            elif isinstance(url, tuple) or isinstance(url[0], Link):
                # there's already one or more links with this URL, but
                # we're allowing mutliple submissions, so we really just
                # want the URL
                url = url[0].url

        if kind == 'link':
            if form.has_errors('url', errors.NO_URL, errors.BAD_URL):
                return

        # users can change the disable_comments on promoted links
        if ((not l or not promote.is_promoted(l)) and
            (form.has_errors('title', errors.NO_TEXT, errors.TOO_LONG) or
             jquery.has_errors('ratelimit', errors.RATELIMIT))):
            return

        if not l:
            l = promote.new_promotion(title, url if kind == 'link' else 'self',
                                      selftext if kind == 'self' else '',
                                      user, ip)

        elif promote.is_promo(l):
            # changing link type is not allowed
            if ((l.is_self and kind == 'link') or
                (not l.is_self and kind == 'self')):
                c.errors.add(errors.NO_CHANGE_KIND, field="kind")
                form.set_error(errors.NO_CHANGE_KIND, "kind")
                return

            changed = False
            # live items can only be changed by a sponsor, and also
            # pay the cost of de-approving the link
            trusted = c.user_is_sponsor or c.user.trusted_sponsor
            if not promote.is_promoted(l) or trusted:
                if title and title != l.title:
                    l.title = title
                    changed = not trusted

                if kind == 'link' and url and url != l.url:
                    l.url = url
                    changed = not trusted

            # only trips if the title and url are changed by a non-sponsor
            if changed:
                promote.unapprove_promotion(l)

            # selftext can be changed at any time
            if kind == 'self':
                l.selftext = selftext

            # comment disabling and sendreplies is free to be changed any time.
            l.disable_comments = disable_comments
            l.sendreplies = sendreplies
            if c.user_is_sponsor or c.user.trusted_sponsor:
                if media_embed and media_width and media_height:
                    l.media_object = dict(height=media_height,
                                          width=media_width,
                                          content=media_embed,
                                          type='custom')
                else:
                    l.media_object = None

                l.media_override = media_override
                if getattr(l, "domain_override", False) or domain_override:
                    l.domain_override = domain_override
            l._commit()

        form.redirect(promote.promo_edit_url(l))

    @validatedForm(VSponsorAdmin(),
                   VModhash(),
                   dates=VDateRange(['startdate', 'enddate'],
                                    reference_date=promote.promo_datetime_now),
                   sr=VSubmitSR('sr', promotion=True))
    def POST_add_roadblock(self, form, jquery, dates, sr):
        if (form.has_errors('startdate', errors.BAD_DATE) or
            form.has_errors('enddate', errors.BAD_DATE, errors.BAD_DATE_RANGE)):
            return
        if form.has_errors('sr', errors.SUBREDDIT_NOEXIST,
                           errors.SUBREDDIT_NOTALLOWED,
                           errors.SUBREDDIT_REQUIRED):
            return
        if dates and sr:
            sd, ed = dates
            PromotedLinkRoadblock.add(sr, sd, ed)
            jquery.refresh()

    @validatedForm(VSponsorAdmin(),
                   VModhash(),
                   dates=VDateRange(['startdate', 'enddate'],
                                    reference_date=promote.promo_datetime_now),
                   sr=VSubmitSR('sr', promotion=True))
    def POST_rm_roadblock(self, form, jquery, dates, sr):
        if dates and sr:
            sd, ed = dates
            PromotedLinkRoadblock.remove(sr, sd, ed)
            jquery.refresh()

    @validatedForm(VSponsor('link_id36'),
                   VModhash(),
                   dates=VDateRange(['startdate', 'enddate'],
                       earliest=timedelta(days=g.min_promote_future),
                       latest=timedelta(days=g.max_promote_future),
                       reference_date=promote.promo_datetime_now,
                       business_days=True,
                       sponsor_override=True),
                   link=VLink('link_id36'),
                   bid=VBid('bid', min=0, max=g.max_promote_bid,
                            coerce=False, error=errors.BAD_BID),
                   sr=VSubmitSR('sr', promotion=True),
                   campaign_id36=nop("campaign_id36"),
                   targeting=VLength("targeting", 10),
                   priority=VPriority("priority"),
                   location=VLocation())
    def POST_edit_campaign(self, form, jquery, link, campaign_id36,
                          dates, bid, sr, targeting, priority, location):
        if not link:
            return

        start, end = dates or (None, None)

        author = Account._byID(link.author_id, data=True)
        cpm = author.cpm_selfserve_pennies
        if location:
            cpm += g.cpm_selfserve_geotarget.pennies

        if (form.has_errors('startdate', errors.BAD_DATE,
                            errors.DATE_TOO_EARLY, errors.DATE_TOO_LATE) or
            form.has_errors('enddate', errors.BAD_DATE, errors.DATE_TOO_EARLY,
                            errors.DATE_TOO_LATE, errors.BAD_DATE_RANGE)):
            return

        # Limit the number of PromoCampaigns a Link can have
        # Note that the front end should prevent the user from getting
        # this far
        existing_campaigns = list(PromoCampaign._by_link(link._id))
        if len(existing_campaigns) > g.MAX_CAMPAIGNS_PER_LINK:
            c.errors.add(errors.TOO_MANY_CAMPAIGNS,
                         msg_params={'count': g.MAX_CAMPAIGNS_PER_LINK},
                         field='title')
            form.has_errors('title', errors.TOO_MANY_CAMPAIGNS)
            return

        campaign = None
        if campaign_id36:
            try:
                campaign = PromoCampaign._byID36(campaign_id36)
            except NotFound:
                pass

        if priority.cpm:
            if form.has_errors('bid', errors.BAD_BID):
                return

            # you cannot edit the bid of a live ad unless it's a freebie
            if (campaign and bid != campaign.bid and
                promote.is_live_promo(link, campaign) and
                not campaign.is_freebie()):
                c.errors.add(errors.BID_LIVE, field='bid')
                form.has_errors('bid', errors.BID_LIVE)
                return

            min_bid = 0 if c.user_is_sponsor else g.min_promote_bid
            if bid is None or bid < min_bid:
                c.errors.add(errors.BAD_BID, field='bid',
                             msg_params={'min': min_bid,
                                         'max': g.max_promote_bid})
                form.has_errors('bid', errors.BAD_BID)
                return
        else:
            bid = 0.   # Set bid to 0 as dummy value

        if targeting == 'one':
            if form.has_errors('sr', errors.SUBREDDIT_NOEXIST,
                               errors.SUBREDDIT_NOTALLOWED,
                               errors.SUBREDDIT_REQUIRED):
                # checking to get the error set in the form, but we can't
                # check for rate-limiting if there's no subreddit
                return

            roadblock = PromotedLinkRoadblock.is_roadblocked(sr, start, end)
            if roadblock and not c.user_is_sponsor:
                msg_params = {"start": roadblock[0].strftime('%m/%d/%Y'),
                              "end": roadblock[1].strftime('%m/%d/%Y')}
                c.errors.add(errors.OVERSOLD, field='sr',
                             msg_params=msg_params)
                form.has_errors('sr', errors.OVERSOLD)
                return

        elif targeting == 'none':
            sr = None

        # Check inventory
        campaign = campaign if campaign_id36 else None
        if not priority.inventory_override:
            oversold = has_oversold_error(form, campaign, start, end, bid, cpm,
                                          sr, location)
            if oversold:
                return

        if campaign:
            promote.edit_campaign(link, campaign, dates, bid, cpm, sr, priority,
                                  location)
        else:
            campaign = promote.new_campaign(link, dates, bid, cpm, sr, priority,
                                            location)
        rc = RenderableCampaign.from_campaigns(link, campaign)
        jquery.update_campaign(campaign._fullname, rc.render_html())

    @validatedForm(VSponsor('link_id36'),
                   VModhash(),
                   l=VLink('link_id36'),
                   campaign=VPromoCampaign("campaign_id36"))
    def POST_delete_campaign(self, form, jquery, l, campaign):
        if l and campaign:
            promote.delete_campaign(l, campaign)

    @validatedForm(VSponsorAdmin(),
                   VModhash(),
                   link=VLink('link_id36'),
                   campaign=VPromoCampaign("campaign_id36"))
    def POST_terminate_campaign(self, form, jquery, link, campaign):
        if link and campaign:
            promote.terminate_campaign(link, campaign)
            rc = RenderableCampaign.from_campaigns(link, campaign)
            jquery.update_campaign(campaign._fullname, rc.render_html())

    @validatedForm(VSponsor('link'),
                   VModhash(),
                   link=VByName("link"),
                   campaign=VPromoCampaign("campaign"),
                   customer_id=VInt("customer_id", min=0),
                   pay_id=VInt("account", min=0),
                   edit=VBoolean("edit"),
                   address=ValidAddress(
                    ["firstName", "lastName", "company", "address",
                     "city", "state", "zip", "country", "phoneNumber"]),
                   creditcard=ValidCard(["cardNumber", "expirationDate",
                                           "cardCode"]))
    def POST_update_pay(self, form, jquery, link, campaign, customer_id, pay_id,
                        edit, address, creditcard):
        # Check inventory
        if campaign_has_oversold_error(form, campaign):
            return

        address_modified = not pay_id or edit
        form_has_errors = False
        if address_modified:
            if (form.has_errors(["firstName", "lastName", "company", "address",
                                 "city", "state", "zip",
                                 "country", "phoneNumber"],
                                errors.BAD_ADDRESS) or
                form.has_errors(["cardNumber", "expirationDate", "cardCode"],
                                errors.BAD_CARD)):
                form_has_errors = True
            elif g.authorizenetapi:
                pay_id = edit_profile(c.user, address, creditcard, pay_id)
            else:
                pay_id = 1
        # if link is in use or finished, don't make a change
        if pay_id and not form_has_errors:
            # valid bid and created or existing bid id.
            # check if already a transaction
            if g.authorizenetapi:
                success, reason = promote.auth_campaign(link, campaign, c.user,
                                                        pay_id)
            else:
                success = True
            if success:
                form.redirect(promote.promo_edit_url(link))
            else:
                form.set_html(".status",
                              reason or
                              _("failed to authenticate card.  sorry."))

    @validate(VSponsor("link_name"),
              VModhash(),
              link=VByName('link_name'),
              file=VUploadLength('file', 500*1024),
              img_type=VImageType('img_type'))
    def POST_link_thumb(self, link=None, file=None, img_type='jpg'):
        if link and (not promote.is_promoted(link) or
                     c.user_is_sponsor or c.user.trusted_sponsor):
            errors = dict(BAD_CSS_NAME="", IMAGE_ERROR="")
            try:
                # thumnails for promoted links can change and therefore expire
                force_thumbnail(link, file, file_type=".%s" % img_type)
            except cssfilter.BadImage:
                # if the image doesn't clean up nicely, abort
                errors["IMAGE_ERROR"] = _("bad image")
            if any(errors.values()):
                return UploadedImage("", "", "upload", errors=errors,
                                     form_id="image-upload").render()
            else:
                link._commit()
                return UploadedImage(_('saved'), thumbnail_url(link), "",
                                     errors=errors,
                                     form_id="image-upload").render()
