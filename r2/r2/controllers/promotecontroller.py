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
# All portions of the code written by reddit are Copyright (c) 2006-2014 reddit
# Inc. All Rights Reserved.
###############################################################################
from datetime import datetime, timedelta

from babel.dates import format_date
from babel.numbers import format_number
import json
import urllib

from pylons import c, g, request
from pylons.i18n import _, N_

from r2.controllers.api import ApiController
from r2.controllers.listingcontroller import ListingController
from r2.controllers.reddit_base import RedditController

from r2.lib import inventory, promote
from r2.lib.authorize import get_account_info, edit_profile, PROFILE_LIMIT
from r2.lib.base import abort
from r2.lib.db import queries
from r2.lib.errors import errors
from r2.lib.filters import websafe
from r2.lib.media import force_thumbnail, thumbnail_url, _scrape_media
from r2.lib.memoize import memoize
from r2.lib.menus import NamedButton, NavButton, NavMenu, QueryButton
from r2.lib.pages import (
    LinkInfoPage,
    PaymentForm,
    PromoteInventory,
    PromotePage,
    PromoteLinkEdit,
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
    VBoolean,
    VByName,
    VCollection,
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
    VPromoTarget,
    VRatelimit,
    VMarkdownLength,
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
    Collection,
    Frontpage,
    Link,
    Message,
    NotFound,
    PromoCampaign,
    PromotionLog,
    PromotionPrices,
    PromotionWeights,
    PromotedLinkRoadblock,
    Subreddit,
    Target,
)


def campaign_has_oversold_error(form, campaign):
    if campaign.priority.inventory_override:
        return

    return has_oversold_error(
        form, campaign, campaign.start_date, campaign.end_date, campaign.bid,
        campaign.cpm, campaign.target, campaign.location,
    )


def has_oversold_error(form, campaign, start, end, bid, cpm, target, location):
    ndays = (to_date(end) - to_date(start)).days
    total_request = calc_impressions(bid, cpm)
    daily_request = int(total_request / ndays)
    oversold = inventory.get_oversold(
        target, start, end, daily_request, ignore=campaign, location=location)

    if oversold:
        min_daily = min(oversold.values())
        available = min_daily * ndays
        msg_params = {
            'available': format_number(available, locale=c.locale),
            'target': target.pretty_name,
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
        form = PromoteLinkEdit(link, rendered)
        page = PromotePage(title=_("edit sponsored link"), content=form,
                      show_sidebar=False, extension_handling=False)
        return page.render()

    @validate(VSponsorAdmin(),
              link=VLink("link"),
              campaign=VPromoCampaign("campaign"))
    def GET_refund(self, link, campaign):
        if link._id != campaign.link_id:
            return self.abort404()

        content = RefundPage(link, campaign)
        return Reddit("refund", content=content, show_sidebar=False).render()

    @validate(VSponsor("link"),
              link=VLink("link"),
              campaign=VPromoCampaign("campaign"))
    def GET_pay(self, link, campaign):
        if link._id != campaign.link_id:
            return self.abort404()

        # no need for admins to play in the credit card area
        if c.user_is_loggedin and c.user._id != link.author_id:
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


class SponsorController(PromoteController):
    @validate(VSponsorAdmin())
    def GET_roadblock(self):
        return PromotePage(title=_("manage roadblocks"),
                           content=Roadblocks()).render()

    @validate(VSponsorAdminOrAdminSecret('secret'),
              start=VDate('startdate'),
              end=VDate('enddate'),
              link_text=nop('link_text'),
              owner=VAccountByName('owner'))
    def GET_report(self, start, end, link_text=None, owner=None):
        now = datetime.now(g.tz).replace(hour=0, minute=0, second=0,
                                         microsecond=0)
        if not start or not end:
            start = promote.promo_datetime_now(offset=1).date()
            end = promote.promo_datetime_now(offset=8).date()
            c.errors.remove((errors.BAD_DATE, 'startdate'))
            c.errors.remove((errors.BAD_DATE, 'enddate'))
        end = end or now - timedelta(days=1)
        start = start or end - timedelta(days=7)

        links = []
        bad_links = []
        owner_name = owner.name if owner else ''

        if owner:
            campaign_ids = PromotionWeights.get_campaign_ids(
                start, end, author_id=owner._id)
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
        collection_name=nop('collection_name'),
    )
    def GET_promote_inventory(self, start, end, sr_name, collection_name):
        if not start or not end:
            start = promote.promo_datetime_now(offset=1).date()
            end = promote.promo_datetime_now(offset=8).date()
            c.errors.remove((errors.BAD_DATE, 'startdate'))
            c.errors.remove((errors.BAD_DATE, 'enddate'))

        target = Target(Frontpage.name)
        if sr_name:
            try:
                sr = Subreddit._by_name(sr_name)
                target = Target(sr.name)
            except NotFound:
                c.errors.add(errors.SUBREDDIT_NOEXIST, field='sr_name')
        elif collection_name:
            collection = Collection.by_name(collection_name)
            if not collection:
                c.errors.add(errors.COLLECTION_NOEXIST, field='collection_name')
            else:
                target = Target(collection)

        content = PromoteInventory(start, end, target)
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
        'all': N_('all promoted links'),
    }
    base_path = '/promoted'

    def title(self):
        return _(self.titles[self.sort])

    @property
    def title_text(self):
        return _('promoted by you')

    @property
    def menus(self):
        filters = [
            NamedButton('all_promos', dest='', use_params=True,
                        aliases=['/sponsor']),
            NamedButton('future_promos', use_params=True),
            NamedButton('unpaid_promos', use_params=True),
            NamedButton('rejected_promos', use_params=True),
            NamedButton('pending_promos', use_params=True),
            NamedButton('live_promos', use_params=True),
        ]
        menus = [NavMenu(filters, base_path=self.base_path, title='show',
                         type='lightdrop')]
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

    @validate(VSponsor())
    def GET_listing(self, sort="all", **env):
        self.sort = sort
        return ListingController.GET_listing(self, **env)


class SponsorListingController(PromoteListingController):
    titles = dict(PromoteListingController.titles.items() + {
        'underdelivered': N_('underdelivered promoted links'),
        'reported': N_('reported promoted links'),
        'house': N_('house promoted links'),
    }.items())
    base_path = '/sponsor/promoted'

    @property
    def title_text(self):
        return _('promos on reddit')

    @property
    def menus(self):
        if self.sort in {'underdelivered', 'reported', 'house'}:
            menus = []
        else:
            menus = super(SponsorListingController, self).menus
            menus.append(NavMenu([
                QueryButton("exclude managed", dest=None,
                            query_param='include_managed'),
                QueryButton("include managed", dest="yes",
                            query_param='include_managed'),
            ], base_path=request.path, type='lightdrop'))

        if self.sort == 'live_promos':
            srnames = promote.all_live_promo_srnames()
            buttons = [NavButton('all', '', use_params=True)]
            try:
                srnames.remove(Frontpage.name)
                frontbutton = NavButton('FRONTPAGE', Frontpage.name,
                                        use_params=True,
                                        aliases=['/promoted/live_promos/%s' %
                                                 urllib.quote(Frontpage.name)])
                buttons.append(frontbutton)
            except KeyError:
                pass

            srnames = sorted(srnames, key=lambda name: name.lower())
            buttons.extend(
                NavButton(name, name, use_params=True) for name in srnames)
            base_path = self.base_path + '/live_promos'
            menus.append(NavMenu(buttons, base_path=base_path,
                                 title='subreddit', type='lightdrop'))
        return menus

    @classmethod
    @memoize('live_by_subreddit', time=300)
    def _live_by_subreddit(cls, sr_names):
        promotuples = promote.get_live_promotions(sr_names)
        return [pt.link for pt in promotuples]

    def live_by_subreddit(cls, sr):
        return cls._live_by_subreddit([sr.name])

    @classmethod
    @memoize('house_link_names', time=60)
    def get_house_link_names(cls):
        now = promote.promo_datetime_now()
        campaign_ids = PromotionWeights.get_campaign_ids(now)
        q = PromoCampaign._query(PromoCampaign.c._id.in_(campaign_ids),
                                 PromoCampaign.c.priority_name == 'house',
                                 data=True)
        link_names = {Link._fullname_from_id36(to36(camp.link_id))
                      for camp in q}
        return sorted(link_names, reverse=True)

    def keep_fn(self):
        base_keep_fn = PromoteListingController.keep_fn(self)

        def keep(item):
            if not self.include_managed and item.managed_promo:
                return False
            return base_keep_fn(item)
        return keep

    def query(self):
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
            return queries.get_reported_links(Subreddit.get_promote_srid())
        elif self.sort == 'house':
            return self.get_house_link_names()
        elif self.sort == 'all':
            return queries.get_all_promoted_links()

    @validate(
        VSponsorAdmin(),
        srname=nop('sr'),
        include_managed=VBoolean("include_managed"),
    )
    def GET_listing(self, srname=None, include_managed=False, sort="all", **kw):
        self.sort = sort
        self.sr = None
        self.include_managed = include_managed

        if srname:
            try:
                self.sr = Subreddit._by_name(srname)
            except NotFound:
                pass
        return ListingController.GET_listing(self, **kw)


def allowed_location_and_target(location, target):
    if c.user_is_sponsor:
        return True

    # regular users can only use locations when targeting frontpage
    is_location = location and location.country
    is_frontpage = (not target.is_collection and
                    target.subreddit_name == Frontpage.name)
    return not is_location or is_frontpage


class PromoteApiController(ApiController):
    @json_validate(sr=VSubmitSR('sr', promotion=True),
                   collection=VCollection('collection'),
                   location=VLocation(),
                   start=VDate('startdate'),
                   end=VDate('enddate'))
    def GET_check_inventory(self, responder, sr, collection, location, start,
                            end):
        if collection:
            target = Target(collection)
            sr = None
        else:
            sr = sr or Frontpage
            target = Target(sr.name)

        if not allowed_location_and_target(location, target):
            return abort(403, 'forbidden')

        available = inventory.get_available_pageviews(
                        target, start, end, location=location, datestr=True)

        return {'inventory': available}

    @validatedForm(VSponsorAdmin(),
                   VModhash(),
                   link=VLink("link_id36"),
                   campaign=VPromoCampaign("campaign_id36"))
    def POST_freebie(self, form, jquery, link, campaign):
        if not link or not campaign or link._id != campaign.link_id:
            return abort(404, 'not found')

        if campaign_has_oversold_error(form, campaign):
            form.set_text(".freebie", _("target oversold, can't freebie"))
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
                "<p>" + websafe(text) + "</p>")


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
        if not link or not campaign or link._id != campaign.link_id:
            return abort(404, 'not found')

        billable_impressions = promote.get_billable_impressions(campaign)
        billable_amount = promote.get_billable_amount(campaign,
                                                      billable_impressions)
        refund_amount = promote.get_refund_amount(campaign, billable_amount)
        if refund_amount > 0:
            promote.refund_campaign(link, campaign, billable_amount,
                                    billable_impressions)
            form.set_text('.status', _('refund succeeded'))
        else:
            form.set_text('.status', _('refund not needed'))

    @validatedForm(
        VSponsor('link_id36'),
        VModhash(),
        VRatelimit(rate_user=True,
                   rate_ip=True,
                   prefix='create_promo_'),
        VShamedDomain('url'),
        username=VLength('username', 100, empty_error=None),
        l=VLink('link_id36'),
        title=VTitle('title'),
        url=VUrl('url', allow_self=False),
        selftext=VMarkdownLength('text', max_length=40000),
        kind=VOneOf('kind', ['link', 'self']),
        disable_comments=VBoolean("disable_comments"),
        sendreplies=VBoolean("sendreplies"),
        media_url=VUrl("media_url", allow_self=False,
                       valid_schemes=('http', 'https')),
        media_autoplay=VBoolean("media_autoplay"),
        media_override=VBoolean("media-override"),
        domain_override=VLength("domain", 100),
        is_managed=VBoolean("is_managed"),
    )
    def POST_edit_promo(self, form, jquery, username, l, title, url,
                        selftext, kind, disable_comments, sendreplies,
                        media_url, media_autoplay, media_override,
                        domain_override, is_managed):

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

        if kind == 'self' and form.has_errors('text', errors.TOO_LONG):
            return

        if not l:
            l = promote.new_promotion(title, url if kind == 'link' else 'self',
                                      selftext if kind == 'self' else '',
                                      user, request.ip)
            l.domain_override = domain_override or None
            if c.user_is_sponsor:
                l.managed_promo = is_managed
            l._commit()

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
            if not promote.is_promoted(l) or c.user_is_sponsor:
                if title and title != l.title:
                    l.title = title
                    changed = not c.user_is_sponsor

                if kind == 'link' and url and url != l.url:
                    l.url = url
                    changed = not c.user_is_sponsor

            # only trips if the title and url are changed by a non-sponsor
            if changed:
                promote.unapprove_promotion(l)

            # selftext can be changed at any time
            if kind == 'self':
                l.selftext = selftext

            # comment disabling and sendreplies is free to be changed any time.
            l.disable_comments = disable_comments
            l.sendreplies = sendreplies

            if c.user_is_sponsor:
                if (not media_url and
                        form.has_errors("media_url", errors.BAD_URL)):
                    return

                media_url = media_url or None
                media_changed = (media_url != l.media_url or
                                 media_autoplay != l.media_autoplay)

                if media_changed:
                    if media_url:
                        media = _scrape_media(
                            media_url, autoplay=media_autoplay,
                            save_thumbnail=False, use_cache=True)

                        if media:
                            l.set_media_object(media.media_object)
                            l.set_secure_media_object(media.secure_media_object)
                            l.media_url = media_url
                            l.media_autoplay = media_autoplay
                        else:
                            c.errors.add(errors.SCRAPER_ERROR, field="media_url")
                            form.set_error(errors.SCRAPER_ERROR, "media_url")
                            return
                    else:
                        l.set_media_object(None)
                        l.set_secure_media_object(None)
                        l.media_url = None
                        l.media_autoplay = False

                l.media_override = media_override
                l.domain_override = domain_override or None
                l.managed_promo = is_managed
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

    @validatedForm(
        VSponsor('link_id36'),
        VModhash(),
        dates=VDateRange(['startdate', 'enddate'],
            earliest=timedelta(days=g.min_promote_future),
            latest=timedelta(days=g.max_promote_future),
            reference_date=promote.promo_datetime_now,
            business_days=True,
            sponsor_override=True),
        link=VLink('link_id36'),
        bid=VFloat('bid', coerce=False),
        target=VPromoTarget(),
        campaign_id36=nop("campaign_id36"),
        priority=VPriority("priority"),
        location=VLocation(),
    )
    def POST_edit_campaign(self, form, jquery, link, campaign_id36,
                           dates, bid, target, priority, location):
        if not link:
            return

        if not target:
            # run form.has_errors to populate the errors in the response
            form.has_errors('sr', errors.SUBREDDIT_NOEXIST,
                            errors.SUBREDDIT_NOTALLOWED,
                            errors.SUBREDDIT_REQUIRED)
            form.has_errors('collection', errors.COLLECTION_NOEXIST)
            form.has_errors('targeting', errors.INVALID_TARGET)
            return

        start, end = dates or (None, None)

        if not allowed_location_and_target(location, target):
            return abort(403, 'forbidden')

        cpm = PromotionPrices.get_price(target, location)

        if (form.has_errors('startdate', errors.BAD_DATE,
                            errors.DATE_TOO_EARLY, errors.DATE_TOO_LATE) or
            form.has_errors('enddate', errors.BAD_DATE, errors.DATE_TOO_EARLY,
                            errors.DATE_TOO_LATE, errors.BAD_DATE_RANGE)):
            return

        # check that start is not so late that authorization hold will expire
        if not c.user_is_sponsor:
            max_start = promote.get_max_startdate()
            if start > max_start:
                c.errors.add(errors.DATE_TOO_LATE,
                             msg_params={'day': max_start.strftime("%m/%d/%Y")},
                             field='startdate')
                form.has_errors('startdate', errors.DATE_TOO_LATE)
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

        if campaign and link._id != campaign.link_id:
            return abort(404, 'not found')

        if priority.cpm:
            min_bid = 0 if c.user_is_sponsor else g.min_promote_bid
            max_bid = None if c.user_is_sponsor else g.max_promote_bid

            if bid is None or bid < min_bid or (max_bid and bid > max_bid):
                c.errors.add(errors.BAD_BID, field='bid',
                             msg_params={'min': min_bid,
                                         'max': max_bid or g.max_promote_bid})
                form.has_errors('bid', errors.BAD_BID)
                return

            # you cannot edit the bid of a live ad unless it's a freebie
            if (campaign and bid != campaign.bid and
                promote.is_live_promo(link, campaign) and
                not campaign.is_freebie()):
                c.errors.add(errors.BID_LIVE, field='bid')
                form.has_errors('bid', errors.BID_LIVE)
                return

        else:
            bid = 0.   # Set bid to 0 as dummy value

        is_frontpage = (not target.is_collection and
                        target.subreddit_name == Frontpage.name)

        if not target.is_collection and not is_frontpage:
            # targeted to a single subreddit, check roadblock
            sr = target.subreddits_slow[0]
            roadblock = PromotedLinkRoadblock.is_roadblocked(sr, start, end)
            if roadblock and not c.user_is_sponsor:
                msg_params = {"start": roadblock[0].strftime('%m/%d/%Y'),
                              "end": roadblock[1].strftime('%m/%d/%Y')}
                c.errors.add(errors.OVERSOLD, field='sr',
                             msg_params=msg_params)
                form.has_errors('sr', errors.OVERSOLD)
                return

        # Check inventory
        campaign = campaign if campaign_id36 else None
        if not priority.inventory_override:
            oversold = has_oversold_error(form, campaign, start, end, bid, cpm,
                                          target, location)
            if oversold:
                return

        if campaign:
            promote.edit_campaign(link, campaign, dates, bid, cpm, target,
                                  priority, location)
        else:
            campaign = promote.new_campaign(link, dates, bid, cpm, target,
                                            priority, location)
        rc = RenderableCampaign.from_campaigns(link, campaign)
        jquery.update_campaign(campaign._fullname, rc.render_html())

    @validatedForm(VSponsor('link_id36'),
                   VModhash(),
                   l=VLink('link_id36'),
                   campaign=VPromoCampaign("campaign_id36"))
    def POST_delete_campaign(self, form, jquery, l, campaign):
        if not campaign or not l or l._id != campaign.link_id:
            return abort(404, 'not found')

        promote.delete_campaign(l, campaign)

    @validatedForm(VSponsorAdmin(),
                   VModhash(),
                   link=VLink('link_id36'),
                   campaign=VPromoCampaign("campaign_id36"))
    def POST_terminate_campaign(self, form, jquery, link, campaign):
        if not link or not campaign or link._id != campaign.link_id:
            return abort(404, 'not found')

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
        if not g.authorizenetapi:
            return

        if not link or not campaign or link._id != campaign.link_id:
            return abort(404, 'not found')

        # Check inventory
        if campaign_has_oversold_error(form, campaign):
            return

        # check that start is not so late that authorization hold will expire
        max_start = promote.get_max_startdate()
        if campaign.start_date > max_start:
            msg = _("please change campaign start date to %(date)s or earlier")
            date = format_date(max_start, format="short", locale=c.locale)
            msg %= {'date': date}
            form.set_text(".status", msg)
            return

        # check the campaign start date is still valid (user may have created
        # the campaign a few days ago)
        now = promote.promo_datetime_now()
        min_start = now + timedelta(days=g.min_promote_future)
        if campaign.start_date.date() < min_start.date():
            msg = _("please change campaign start date to %(date)s or later")
            date = format_date(min_start, format="short", locale=c.locale)
            msg %= {'date': date}
            form.set_text(".status", msg)
            return

        address_modified = not pay_id or edit
        if address_modified:
            address_fields = ["firstName", "lastName", "company", "address",
                              "city", "state", "zip", "country", "phoneNumber"]
            card_fields = ["cardNumber", "expirationDate", "cardCode"]

            if (form.has_errors(address_fields, errors.BAD_ADDRESS) or
                    form.has_errors(card_fields, errors.BAD_CARD)):
                return

            pay_id = edit_profile(c.user, address, creditcard, pay_id)

        reason = None
        if pay_id:
            success, reason = promote.auth_campaign(link, campaign, c.user,
                                                    pay_id)

            if success:
                form.redirect(promote.promo_edit_url(link))
                return

        msg = reason or _("failed to authenticate card. sorry.")
        form.set_text(".status", msg)

    @validate(VSponsor("link_name"),
              VModhash(),
              link=VByName('link_name'),
              file=VUploadLength('file', 500*1024),
              img_type=VImageType('img_type'))
    def POST_link_thumb(self, link=None, file=None, img_type='jpg'):
        if link and (not promote.is_promoted(link) or c.user_is_sponsor):
            errors = dict(BAD_CSS_NAME="", IMAGE_ERROR="")

            # thumnails for promoted links can change and therefore expire
            force_thumbnail(link, file, file_type=".%s" % img_type)

            if any(errors.values()):
                return UploadedImage("", "", "upload", errors=errors,
                                     form_id="image-upload").render()
            else:
                link._commit()
                return UploadedImage(_('saved'), thumbnail_url(link), "",
                                     errors=errors,
                                     form_id="image-upload").render()
