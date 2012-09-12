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

from validator import *
from pylons.i18n import _
from r2.models import *
from r2.lib.authorize import get_account_info, edit_profile
from r2.lib.pages import *
from r2.lib.pages.trafficpages import TrafficViewerList
from r2.lib.pages.things import wrap_links
from r2.lib.strings import strings
from r2.lib.menus import *
from r2.controllers.listingcontroller import ListingController
from r2.lib.db import queries

from r2.controllers.reddit_base import RedditController

from r2.lib.utils import make_offset_date
from r2.lib.media import force_thumbnail, thumbnail_url
from r2.lib.scraper import MediaEmbed
from r2.lib import cssfilter
from datetime import datetime

class PromoteController(ListingController):
    skip = False
    where = 'promoted'
    render_cls = PromotePage

    @property
    def title_text(self):
        return _('promoted by you')

    def query(self):
        author_id = None if c.user_is_sponsor else c.user._id
        if self.sort == "future_promos":
            return promote.get_unapproved_links(author_id)
        elif self.sort == "pending_promos":
            return promote.get_accepted_links(author_id)
        elif self.sort == "unpaid_promos":
            return promote.get_unpaid_links(author_id)
        elif self.sort == "rejected_promos":
            return promote.get_rejected_links(author_id)
        elif self.sort == "live_promos":
            return promote.get_live_links(author_id)
        return promote.get_all_links(author_id)

    @validate(VSponsor())
    def GET_listing(self, sort = "", **env):
        if not c.user_is_loggedin or not c.user.email_verified:
            return self.redirect("/ad_inq")
        self.sort = sort
        return ListingController.GET_listing(self, **env)

    GET_index = GET_listing

    @validate(VSponsor())
    def GET_new_promo(self):
        return PromotePage('content', content = PromoteLinkForm()).render()

    @validate(VSponsor('link'),
              link = VLink('link'))
    def GET_edit_promo(self, link):
        if not link or link.promoted is None:
            return self.abort404()
        rendered = wrap_links(link, wrapper = promote.sponsor_wrapper,
                              skip = False)

        form = PromoteLinkForm(link = link,
                               listing = rendered,
                               timedeltatext = "")

        page = PromotePage('new_promo', content = form)

        return page.render()

    @validate(VSponsor())
    def GET_graph(self):
        content = Promote_Graph()
        if c.user_is_sponsor and c.render_style == 'csv':
            c.response.content = content.as_csv()
            return c.response
        return PromotePage("graph", content = content).render()


    ### POST controllers below
    @validatedForm(VSponsorAdmin(),
                   link = VLink("link_id"),
                   indx = VInt("indx"))
    def POST_freebie(self, form, jquery, link, indx):
        if promote.is_promo(link) and indx is not None:
            promote.free_campaign(link, indx, c.user)
            form.redirect(promote.promo_edit_url(link))

    @validatedForm(VSponsorAdmin(),
                   link = VByName("link"),
                   note = nop("note"))
    def POST_promote_note(self, form, jquery, link, note):
        if promote.is_promo(link):
            form.find(".notes").children(":last").after(
                "<p>" + promote.promotion_log(link, note, True) + "</p>")


    @noresponse(VSponsorAdmin(),
                thing = VByName('id'))
    def POST_promote(self, thing):
        if promote.is_promo(thing):
            promote.accept_promotion(thing)

    @noresponse(VSponsorAdmin(),
                thing = VByName('id'),
                reason = nop("reason"))
    def POST_unpromote(self, thing, reason):
        if promote.is_promo(thing):
            promote.reject_promotion(thing, reason = reason)

    @validatedForm(VSponsor('link_id'),
                   VModhash(),
                   VRatelimit(rate_user = True,
                              rate_ip = True,
                              prefix = 'create_promo_'),
                   l     = VLink('link_id'),
                   title = VTitle('title'),
                   url   = VUrl('url', allow_self = False, lookup = False),
                   ip    = ValidIP(),
                   disable_comments = VBoolean("disable_comments"),
                   set_clicks = VBoolean("set_maximum_clicks"),
                   max_clicks = VInt("maximum_clicks", min = 0),
                   set_views = VBoolean("set_maximum_views"),
                   max_views = VInt("maximum_views", min = 0),
                   media_width = VInt("media-width", min = 0),
                   media_height = VInt("media-height", min = 0),
                   media_embed = VLength("media-embed", 1000),
                   media_override = VBoolean("media-override"),
                   domain_override = VLength("domain", 100)
                   )
    def POST_edit_promo(self, form, jquery, ip, l, title, url,
                        disable_comments,
                        set_clicks, max_clicks,
                        set_views,  max_views,
                        media_height, media_width, media_embed,
                        media_override, domain_override):

        should_ratelimit = False
        if not c.user_is_sponsor:
            set_clicks = False
            set_views = False
            should_ratelimit = True
        if not set_clicks:
            max_clicks = None
        if not set_views:
            max_views = None

        if not should_ratelimit:
            c.errors.remove((errors.RATELIMIT, 'ratelimit'))

        # demangle URL in canonical way
        if url:
            if isinstance(url, (unicode, str)):
                form.set_inputs(url = url)
            elif isinstance(url, tuple) or isinstance(url[0], Link):
                # there's already one or more links with this URL, but
                # we're allowing mutliple submissions, so we really just
                # want the URL
                url = url[0].url

        # users can change the disable_comments on promoted links
        if ((not l or not promote.is_promoted(l)) and 
            (form.has_errors('title', errors.NO_TEXT,
                            errors.TOO_LONG) or
            form.has_errors('url', errors.NO_URL, errors.BAD_URL) or
            jquery.has_errors('ratelimit', errors.RATELIMIT))):
            return

        if not l:
            l = promote.new_promotion(title, url, c.user, ip)
        elif promote.is_promo(l):
            changed = False
            # live items can only be changed by a sponsor, and also
            # pay the cost of de-approving the link
            trusted = c.user_is_sponsor or c.user.trusted_sponsor
            if not promote.is_promoted(l) or trusted:
                if title and title != l.title:
                    l.title = title
                    changed = not trusted
                if url and url != l.url:
                    l.url = url
                    changed = not trusted

            # only trips if the title and url are changed by a non-sponsor
            if changed and not promote.is_unpaid(l):
                promote.unapprove_promotion(l)
            if trusted and promote.is_unapproved(l):
                promote.accept_promotion(l)

            if c.user_is_sponsor:
                l.maximum_clicks = max_clicks
                l.maximum_views = max_views

            # comment disabling is free to be changed any time.
            l.disable_comments = disable_comments
            if c.user_is_sponsor or c.user.trusted_sponsor:
                if media_embed and media_width and media_height:
                    l.media_object = dict(height = media_height,
                                          width = media_width,
                                          content = media_embed,
                                          type = 'custom')
                else:
                    l.media_object = None

                l.media_override = media_override
                if getattr(l, "domain_override", False) or domain_override:
                    l.domain_override = domain_override
            l._commit()

        form.redirect(promote.promo_edit_url(l))

    @validate(VSponsorAdmin())
    def GET_roadblock(self):
        return PromotePage('content', content = Roadblocks()).render()

    @validatedForm(VSponsorAdmin(),
                   VModhash(),
                   dates = VDateRange(['startdate', 'enddate'],
                                      future = 1, 
                                      reference_date = promote.promo_datetime_now,
                                      business_days = False, 
                                      admin_override = True),
                   sr = VSubmitSR('sr', promotion=True))
    def POST_add_roadblock(self, form, jquery, dates, sr):
        if (form.has_errors('startdate', errors.BAD_DATE,
                            errors.BAD_FUTURE_DATE) or
            form.has_errors('enddate', errors.BAD_DATE,
                            errors.BAD_FUTURE_DATE, errors.BAD_DATE_RANGE)):
            return
        if form.has_errors('sr', errors.SUBREDDIT_NOEXIST,
                           errors.SUBREDDIT_NOTALLOWED,
                           errors.SUBREDDIT_REQUIRED):
            return
        if dates and sr:
            sd, ed = dates
            promote.roadblock_reddit(sr.name, sd.date(), ed.date())
            jquery.refresh()

    @validatedForm(VSponsorAdmin(),
                   VModhash(),
                   dates = VDateRange(['startdate', 'enddate'],
                                      future = 1, 
                                      reference_date = promote.promo_datetime_now,
                                      business_days = False, 
                                      admin_override = True),
                   sr = VSubmitSR('sr', promotion=True))
    def POST_rm_roadblock(self, form, jquery, dates, sr):
        if dates and sr:
            sd, ed = dates
            promote.unroadblock_reddit(sr.name, sd.date(), ed.date())
            jquery.refresh()

    @validatedForm(VSponsor('link_id'),
                   VModhash(),
                   dates = VDateRange(['startdate', 'enddate'],
                                  future = 1, 
                                  reference_date = promote.promo_datetime_now,
                                  business_days = False, 
                                  admin_override = True),
                   l     = VLink('link_id'),
                   bid   = VFloat('bid', min=0, max=g.max_promote_bid, 
                                  coerce=False, error=errors.BAD_BID),
                   sr = VSubmitSR('sr', promotion=True),
                   indx = VInt("indx"), 
                   targeting = VLength("targeting", 10))
    def POST_edit_campaign(self, form, jquery, l, indx,
                          dates, bid, sr, targeting):
        if not l:
            return
        
        start, end = dates or (None, None)

        if start and end and not promote.is_accepted(l) and not c.user_is_sponsor:
            # if the ad is not approved already, ensure the start date
            # is at least 2 days in the future
            start = start.date()
            end = end.date()
            now = promote.promo_datetime_now()
            future = make_offset_date(now, g.min_promote_future,
                                      business_days = True)
            if start < future.date():
                c.errors.add(errors.BAD_FUTURE_DATE,
                             msg_params = dict(day=g.min_promote_future),
                             field = "startdate")


        if (form.has_errors('startdate', errors.BAD_DATE,
                            errors.BAD_FUTURE_DATE) or
            form.has_errors('enddate', errors.BAD_DATE,
                            errors.BAD_FUTURE_DATE, errors.BAD_DATE_RANGE)):
            return

        duration = max((end - start).days, 1)

        if form.has_errors('bid', errors.BAD_BID):
            return

        # minimum bid depends on user privilege and targeting, checked here
        # instead of in the validator b/c current duration is needed
        if c.user_is_admin:
            min_daily_bid = 0
        elif targeting == 'one':
            min_daily_bid = g.min_promote_bid * 1.5
        else:
            min_daily_bid = g.min_promote_bid

        if bid is None or bid / duration < min_daily_bid:
            c.errors.add(errors.BAD_BID, field = 'bid',
                         msg_params = {'min': min_daily_bid,
                                       'max': g.max_promote_bid})
            form.has_errors('bid', errors.BAD_BID)
            return

        if targeting == 'one':
            if form.has_errors('sr', errors.SUBREDDIT_NOEXIST,
                               errors.SUBREDDIT_NOTALLOWED,
                               errors.SUBREDDIT_REQUIRED):
                # checking to get the error set in the form, but we can't
                # check for rate-limiting if there's no subreddit
                return
            oversold = promote.is_roadblocked(sr.name, start, end)
            if oversold and not c.user_is_sponsor:
                c.errors.add(errors.OVERSOLD, field = 'sr',
                             msg_params = {"start": oversold[0].strftime('%m/%d/%Y'),
                                           "end": oversold[1].strftime('%m/%d/%Y')})
                form.has_errors('sr', errors.OVERSOLD)
                return
        if targeting == 'none':
            sr = None

        if indx is not None:
            promote.edit_campaign(l, indx, dates, bid, sr)
            l = promote.editable_add_props(l)
            jquery.update_campaign(*l.campaigns[indx])
        else:
            indx = promote.new_campaign(l, dates, bid, sr)
            l = promote.editable_add_props(l)
            jquery.new_campaign(*l.campaigns[indx])

    @validatedForm(VSponsor('link_id'),
                   VModhash(),
                   l     = VLink('link_id'),
                   indx = VInt("indx"))
    def POST_delete_campaign(self, form, jquery, l, indx):
        if l and indx is not None:
            promote.delete_campaign(l, indx)


    @validatedForm(VSponsor('container'),
                   VModhash(),
                   user = VExistingUname('name'),
                   thing = VByName('container'))
    def POST_traffic_viewer(self, form, jquery, user, thing):
        """
        Adds a user to the list of users allowed to view a promoted
        link's traffic page.
        """
        if not form.has_errors("name",
                               errors.USER_DOESNT_EXIST, errors.NO_USER):
            form.set_inputs(name = "")
            form.set_html(".status:first", _("added"))
            if promote.add_traffic_viewer(thing, user):
                user_row = TrafficViewerList(thing).user_row(user)
                jquery("#traffic-table").show(
                    ).find("table").insert_table_rows(user_row)

                # send the user a message
                msg = strings.msg_add_friend.get("traffic")
                subj = strings.subj_add_friend.get("traffic")
                if msg and subj:
                    d = dict(url = thing.make_permalink_slow(),
                             traffic_url = promote.promo_traffic_url(thing),
                             title = thing.title)
                    msg = msg % d
                    subk =msg % d
                    item, inbox_rel = Message._new(c.user, user,
                                                   subj, msg, request.ip)
                    if g.write_query_queue:
                        queries.new_message(item, inbox_rel)


    @validatedForm(VSponsor('container'),
                   VModhash(),
                   iuser = VByName('id'),
                   thing = VByName('container'))
    def POST_rm_traffic_viewer(self, form, jquery, iuser, thing):
        if thing and iuser:
            promote.rm_traffic_viewer(thing, iuser)


    @validatedForm(VSponsor('link'),
                   link = VByName("link"),
                   indx = VInt("indx"),
                   customer_id = VInt("customer_id", min = 0),
                   pay_id = VInt("account", min = 0),
                   edit   = VBoolean("edit"),
                   address = ValidAddress(
                    ["firstName", "lastName", "company", "address",
                     "city", "state", "zip", "country", "phoneNumber"],
                    allowed_countries = g.allowed_pay_countries),
                   creditcard = ValidCard(["cardNumber", "expirationDate",
                                           "cardCode"]))
    def POST_update_pay(self, form, jquery, link, indx, customer_id, pay_id,
                        edit, address, creditcard):
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
                success, reason = promote.auth_campaign(link, indx, c.user, pay_id)
            else:
                success = True
            if success:
                form.redirect(promote.promo_edit_url(link))
            else:
                form.set_html(".status",
                              reason or
                              _("failed to authenticate card.  sorry."))

    @validate(VSponsor("link"),
              article = VLink("link"),
              indx = VInt("indx"))
    def GET_pay(self, article, indx):
        # no need for admins to play in the credit card area
        if c.user_is_loggedin and c.user._id != article.author_id:
            return self.abort404()

        if not promote.is_valid_campaign(article, indx):
            return self.abort404()

        if g.authorizenetapi:
            data = get_account_info(c.user)
            content = PaymentForm(article, indx,
                                  customer_id = data.customerProfileId,
                                  profiles = data.paymentProfiles)
        else:
            content = PaymentForm(article, 0, customer_id = 0,
                                  profiles = [])
        res =  LinkInfoPage(link = article,
                            content = content,
                            show_sidebar = False)
        return res.render()

    def GET_link_thumb(self, *a, **kw):
        """
        See GET_upload_sr_image for rationale
        """
        return "nothing to see here."

    @validate(VSponsor("link_id"),
              link = VByName('link_id'),
              file = VLength('file', 500*1024))
    def POST_link_thumb(self, link=None, file=None):
        if link and (not promote.is_promoted(link) or
                     c.user_is_sponsor or c.user.trusted_sponsor):
            errors = dict(BAD_CSS_NAME = "", IMAGE_ERROR = "")
            try:
                # thumnails for promoted links can change and therefore expire
                force_thumbnail(link, file, file_type=".jpg")
            except cssfilter.BadImage:
                # if the image doesn't clean up nicely, abort
                errors["IMAGE_ERROR"] = _("bad image")
            if any(errors.values()):
                return UploadedImage("", "", "upload", errors = errors,
                                     form_id = "image-upload").render()
            else:
                link._commit()
                return UploadedImage(_('saved'), thumbnail_url(link), "",
                                     errors = errors,
                                     form_id = "image-upload").render()

