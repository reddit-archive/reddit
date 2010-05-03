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
from validator import *
from pylons.i18n import _
from r2.models import *
from r2.lib.authorize import get_account_info, edit_profile
from r2.lib.pages import *
from r2.lib.pages.things import wrap_links
from r2.lib.menus import *
from r2.controllers import ListingController

from r2.controllers.reddit_base import RedditController

from r2.lib.promote import get_promoted, STATUS, PromoteSR
from r2.lib.utils import timetext
from r2.lib.media import force_thumbnail, thumbnail_url
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
        q = Link._query(Link.c.sr_id == PromoteSR._id)
        if not c.user_is_sponsor:
            # get user's own promotions
            q._filter(Link.c.author_id == c.user._id)
        q._filter(Link.c._spam == (True, False),
                  Link.c.promoted == (True, False))
        q._sort = desc('_date')

        if self.sort == "future_promos":
            q._filter(Link.c.promote_status == STATUS.unseen)
        elif self.sort == "pending_promos":
            if c.user_is_admin:
                q._filter(Link.c.promote_status == STATUS.pending)
            else:
                q._filter(Link.c.promote_status == (STATUS.unpaid,
                                                    STATUS.unseen,
                                                    STATUS.accepted,
                                                    STATUS.rejected))
        elif self.sort == "unpaid_promos":
            q._filter(Link.c.promote_status == STATUS.unpaid)
        elif self.sort == "rejected_promos":
            q._filter(Link.c.promote_status == STATUS.rejected)
        elif self.sort == "live_promos":
            q._filter(Link.c.promote_status == STATUS.promoted)

        return q

    def GET_listing(self, sort = "", **env):
        if not c.user_is_loggedin or not c.user.email_verified:
            return self.redirect("/ad_inq")
        self.sort = sort
        return ListingController.GET_listing(self, **env)

    GET_index = GET_listing

    @validate(VVerifiedUser())
    def GET_new_promo(self):
        return PromotePage('content', content = PromoteLinkForm()).render()

    @validate(VSponsor('link'),
              link = VLink('link'))
    def GET_edit_promo(self, link):
        if link.promoted is None:
            return self.abort404()
        rendered = wrap_links(link)
        timedeltatext = ''
        if link.promote_until:
            timedeltatext = timetext(link.promote_until - datetime.now(g.tz),
                                     resultion=2)

        form = PromoteLinkForm(link = link,
                               listing = rendered,
                               timedeltatext = timedeltatext)
        page = PromotePage('new_promo', content = form)

        return page.render()

    @validate(VVerifiedUser())
    def GET_graph(self):
        content = Promote_Graph()
        if c.user_is_sponsor and c.render_style == 'csv':
            c.response.content = content.as_csv()
            return c.response
        return PromotePage("grpaph", content = content).render()


    ### POST controllers below
    @validatedForm(VSponsor(),
                   link = VByName("link"),
                   bid   = VBid('bid', "link"))
    def POST_freebie(self, form, jquery, link, bid):
        if link and link.promoted is not None and bid:
            promote.auth_paid_promo(link, c.user, -1, bid)
        jquery.refresh()

    @validatedForm(VSponsor(),
                   link = VByName("link"),
                   note = nop("note"))
    def POST_promote_note(self, form, jquery, link, note):
        if link and link.promoted is not None:
            form.find(".notes").children(":last").after(
                "<p>" + promote.promotion_log(link, note, True) + "</p>")


    @validatedForm(VSponsor(),
                   link = VByName("link"),
                   refund   = VFloat("refund"))
    def POST_refund(self, form, jquery, link, refund):
        if link:
            # make sure we don't refund more than we should
            author = Account._byID(link.author_id)
            promote.refund_promo(link, author, refund)
        jquery.refresh()

    @noresponse(VSponsor(),
                thing = VByName('id'))
    def POST_promote(self, thing):
        if thing:
            now = datetime.now(g.tz)
            # make accepted if unseen or already rejected
            if thing.promote_status in (promote.STATUS.unseen,
                                        promote.STATUS.rejected):
                promote.accept_promo(thing)
            # if not finished and the dates are current
            elif (thing.promote_status < promote.STATUS.finished and
                  thing._date <= now and thing.promote_until > now):
                # if already pending, cron job must have failed.  Promote.  
                if thing.promote_status == promote.STATUS.accepted:
                    promote.pending_promo(thing)
                promote.promote(thing)

    @noresponse(VSponsor(),
                thing = VByName('id'),
                reason = nop("reason"))
    def POST_unpromote(self, thing, reason):
        if thing:
            # reject anything that hasn't yet been promoted
            if (c.user_is_sponsor and
                thing.promote_status < promote.STATUS.promoted):
                promote.reject_promo(thing, reason = reason)
            # also reject anything that is live but has a reason given
            elif (c.user_is_sponsor and reason and
                  thing.promte_status == promote.STATUS.promoted):
                promote.reject_promo(thing, reason = reason)
            # otherwise, mark it as "finished"
            else:
                promote.unpromote(thing)

    @validatedForm(VSponsor('link_id'),
                   VModhash(),
                   VRatelimit(rate_user = True,
                              rate_ip = True,
                              prefix = 'create_promo_'),
                   ip    = ValidIP(),
                   l     = VLink('link_id'),
                   title = VTitle('title'),
                   url   = VUrl('url', allow_self = False),
                   dates = VDateRange(['startdate', 'enddate'],
                                  future = g.min_promote_future,
                                  reference_date = promote.promo_datetime_now,
                                  business_days = True, 
                                  admin_override = True),
                   disable_comments = VBoolean("disable_comments"),
                   set_clicks = VBoolean("set_maximum_clicks"),
                   max_clicks = VInt("maximum_clicks", min = 0),
                   set_views = VBoolean("set_maximum_views"),
                   max_views = VInt("maximum_views", min = 0),
                   bid   = VBid('bid', 'link_id'))
    def POST_new_promo(self, form, jquery, l, ip, title, url, dates,
                       disable_comments, 
                       set_clicks, max_clicks, set_views, max_views, bid):
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

        # check dates and date range
        start, end = [x.date() for x in dates] if dates else (None, None)
        if (not l or
            (l.promote_status != promote.STATUS.promoted and
             (l._date.date(), l.promote_until.date()) != (start,end))):
            if (form.has_errors('startdate', errors.BAD_DATE,
                                errors.BAD_FUTURE_DATE) or
                form.has_errors('enddate', errors.BAD_DATE,
                                errors.BAD_FUTURE_DATE, errors.BAD_DATE_RANGE)):
                return
            # if the dates have been updated, it is possible that the
            # bid is no longer valid
            duration = max((end - start).days, 1)
            if float(bid) / duration < g.min_promote_bid:
                c.errors.add(errors.BAD_BID, field = 'bid',
                             msg_params = {"min": g.min_promote_bid,
                                           "max": g.max_promote_bid})

        # dates have been validated at this point.  Next validate title, etc.
        if (form.has_errors('title', errors.NO_TEXT,
                            errors.TOO_LONG) or
            form.has_errors('url', errors.NO_URL, errors.BAD_URL) or
            form.has_errors('bid', errors.BAD_BID) or
            (not l and jquery.has_errors('ratelimit', errors.RATELIMIT))):
            return
        elif l:
            if l.promote_status == promote.STATUS.finished:
                form.parent().set_html(".status",
                             _("that promoted link is already finished."))
            else:
                # we won't penalize for changes of dates provided
                # the submission isn't pending (or promoted, or
                # finished)
                changed = False
                if dates and not promote.update_promo_dates(l, *dates):
                    form.parent().set_html(".status",
                                           _("too late to change the date."))
                else:
                    changed = True

                # check for changes in the url and title
                if promote.update_promo_data(l, title, url):
                    changed = True
                # sponsors can change the bid value (at the expense of making
                # the promotion a freebie)
                if c.user_is_sponsor and bid != l.promote_bid:
                    promote.auth_paid_promo(l, c.user, -1, bid)
                    promote.accept_promo(l)
                    changed = True

                if c.user_is_sponsor:
                    l.maximum_clicks = max_clicks
                    l.maximum_views = max_views
                    changed = True

                l.disable_comments = disable_comments
                l._commit()

                if changed:
                    jquery.refresh()

        # no link so we are creating a new promotion
        elif dates:
            promote_start, promote_end = dates
            # check that the bid satisfies the minimum
            duration = max((promote_end - promote_start).days, 1)
            if bid / duration >= g.min_promote_bid:
                l = promote.new_promotion(title, url, c.user, ip,
                                          promote_start, promote_end, bid,
                                          disable_comments = disable_comments,
                                          max_clicks = max_clicks,
                                          max_views = max_views)
                # if the submitter is a sponsor (or implicitly an admin) we can
                # fast-track the approval and auto-accept the bid
                if c.user_is_sponsor:
                    promote.auth_paid_promo(l, c.user, -1, bid)
                    promote.accept_promo(l)

                # register a vote
                v = Vote.vote(c.user, l, True, ip)

                # set the rate limiter
                if should_ratelimit:
                    VRatelimit.ratelimit(rate_user=True, rate_ip = True, 
                                         prefix = "create_promo_",
                                         seconds = 60)

                form.redirect(promote.promo_edit_url(l))
            else:
                c.errors.add(errors.BAD_BID,
                             msg_params = dict(min=g.min_promote_bid,
                                               max=g.max_promote_bid),
                             field = 'bid')
                form.set_error(errors.BAD_BID, "bid")

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
                   customer_id = VInt("customer_id", min = 0),
                   bid   = VBid("bid", "link"),
                   pay_id = VInt("account", min = 0),
                   edit   = VBoolean("edit"),
                   address = ValidAddress(["firstName", "lastName",
                                           "company", "address",
                                           "city", "state", "zip",
                                           "country", "phoneNumber"],
                                          usa_only = True),
                   creditcard = ValidCard(["cardNumber", "expirationDate",
                                           "cardCode"]))
    def POST_update_pay(self, form, jquery, bid, link, customer_id, pay_id,
                        edit, address, creditcard):
        address_modified = not pay_id or edit
        if address_modified:
            if (form.has_errors(["firstName", "lastName", "company", "address",
                                 "city", "state", "zip",
                                 "country", "phoneNumber"],
                                errors.BAD_ADDRESS) or
                form.has_errors(["cardNumber", "expirationDate", "cardCode"],
                                errors.BAD_CARD)):
                pass
            else:
                pay_id = edit_profile(c.user, address, creditcard, pay_id)
        if form.has_errors('bid', errors.BAD_BID) or not bid:
            pass
        # if link is in use or finished, don't make a change
        elif link.promote_status == promote.STATUS.promoted:
            form.set_html(".status",
                          _("that link is currently promoted.  "
                            "you can't update your bid now."))
        elif link.promote_status == promote.STATUS.finished:
            form.set_html(".status",
                          _("that promotion is already over, so updating "
                            "your bid is kind of pointless, don't you think?"))
        elif pay_id:
            # valid bid and created or existing bid id.
            # check if already a transaction
            if promote.auth_paid_promo(link, c.user, pay_id, bid):
                form.redirect(promote.promo_edit_url(link))
            else:
                form.set_html(".status",
                              _("failed to authenticate card.  sorry."))

    @validate(VSponsor("link"),
              article = VLink("link"))
    def GET_pay(self, article):
        data = get_account_info(c.user)
        # no need for admins to play in the credit card area
        if c.user_is_loggedin and c.user._id != article.author_id:
            return self.abort404()

        content = PaymentForm(link = article,
                              customer_id = data.customerProfileId,
                              profiles = data.paymentProfiles)
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
        errors = dict(BAD_CSS_NAME = "", IMAGE_ERROR = "")
        try:
            force_thumbnail(link, file)
        except cssfilter.BadImage:
            # if the image doesn't clean up nicely, abort
            errors["IMAGE_ERROR"] = _("bad image")

        if any(errors.values()):
            return UploadedImage("", "", "upload", errors = errors).render()
        else:
            if not c.user_is_sponsor:
                promote.unapproved_promo(link)
            return UploadedImage(_('saved'), thumbnail_url(link), "",
                                 errors = errors).render()


