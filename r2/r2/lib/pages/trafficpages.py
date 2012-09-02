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

import datetime
import collections

from pylons.i18n import _
from pylons import g, c
import babel.core

from r2.lib.menus import menu
from r2.lib.wrapped import Templated
from r2.lib.pages.pages import Reddit, TimeSeriesChart, UserList
from r2.lib.menus import NavButton, NamedButton, PageNameNav, NavMenu
from r2.lib import promote
from r2.lib.utils import Storage
from r2.models import Thing, Link, traffic
from r2.models.subreddit import Subreddit, _DefaultSR


COLORS = Storage(UPVOTE_ORANGE="#ff5700",
                 DOWNVOTE_BLUE="#9494ff",
                 MISCELLANEOUS="#006600")


class TrafficPage(Reddit):
    extension_handling = False
    extra_page_classes = ["traffic"]

    def __init__(self, content):
        Reddit.__init__(self, title=_("traffic stats"), content=content)

    def build_toolbars(self):
        main_buttons = [NavButton(menu.sitewide, "/"),
                        NamedButton("languages"),
                        NamedButton("adverts")]

        toolbar = [PageNameNav("nomenu", title=self.title),
                   NavMenu(main_buttons, base_path="/traffic", type="tabmenu")]

        return toolbar


class SitewideTrafficPage(TrafficPage):
    extra_page_classes = TrafficPage.extra_page_classes + ["traffic-sitewide"]

    def __init__(self):
        TrafficPage.__init__(self, SitewideTraffic())


class LanguageTrafficPage(TrafficPage):
    def __init__(self, langcode):
        if langcode:
            content = LanguageTraffic(langcode)
        else:
            content = LanguageTrafficSummary()

        TrafficPage.__init__(self, content)


class AdvertTrafficPage(TrafficPage):
    def __init__(self, code):
        if code:
            content = AdvertTraffic(code)
        else:
            content = AdvertTrafficSummary()
        TrafficPage.__init__(self, content)


class RedditTraffic(Templated):
    def __init__(self, place):
        self.place = place

        self.traffic_last_modified = traffic.get_traffic_last_modified()
        self.traffic_lag = (datetime.datetime.utcnow() -
                            self.traffic_last_modified)

        self.get_tables()

        Templated.__init__(self)

    def get_tables(self):
        self.tables = []

        for interval in ("month", "day", "hour"):
            columns = [
                dict(color=COLORS.UPVOTE_ORANGE,
                     title=_("uniques by %s" % interval),
                     shortname=_("uniques")),
                dict(color=COLORS.DOWNVOTE_BLUE,
                     title=_("pageviews by %s" % interval),
                     shortname=_("pageviews")),
            ]

            data = self.get_data_for_interval(interval, columns)

            title = _("traffic by %s" % interval)
            graph = TimeSeriesChart("traffic-" + interval,
                                    title,
                                    interval,
                                    columns,
                                    data,
                                    self.traffic_last_modified,
                                    classes=["traffic-table"])
            self.tables.append(graph)

        try:
            self.dow_summary = self.get_dow_summary()
        except NotImplementedError:
            self.dow_summary = None
        else:
            uniques_total = collections.Counter()
            pageviews_total = collections.Counter()
            days_total = collections.Counter()

            # don't include the latest (likely incomplete) day
            for date, (uniques, pageviews) in self.dow_summary[1:]:
                dow = date.weekday()
                uniques_total[dow] += uniques
                pageviews_total[dow] += pageviews
                days_total[dow] += 1

            # make a summary of the averages for each day of the week
            self.dow_summary = []
            for dow in xrange(7):
                day_count = days_total[dow]
                if day_count:
                    avg_uniques = uniques_total[dow] / day_count
                    avg_pageviews = pageviews_total[dow] / day_count
                    self.dow_summary.append((dow,
                                             (avg_uniques, avg_pageviews)))
                else:
                    self.dow_summary.append((dow, (0, 0)))

            # calculate the averages for *any* day of the week
            mean_uniques = sum(r[1][0] for r in self.dow_summary) / 7.0
            mean_pageviews = sum(r[1][1] for r in self.dow_summary) / 7.0
            self.dow_means = (round(mean_uniques), round(mean_pageviews))

    def get_dow_summary(self):
        raise NotImplementedError()

    def get_data_for_interval(self, interval, columns):
        raise NotImplementedError()


class SitewideTraffic(RedditTraffic):
    def __init__(self):
        subreddit_summary = traffic.PageviewsBySubreddit.top_last_month()
        self.subreddit_summary = []
        for srname, data in subreddit_summary:
            if srname == _DefaultSR.name:
                name = _("[frontpage]")
                url = None
            elif srname in Subreddit._specials:
                name = "[%s]" % srname
                url = None
            else:
                name = "/r/%s" % srname
                url = name + "/about/traffic"

            self.subreddit_summary.append(((name, url), data))

        RedditTraffic.__init__(self, g.domain)

    def get_dow_summary(self):
        return traffic.SitewidePageviews.history("day")

    def get_data_for_interval(self, interval, columns):
        return traffic.SitewidePageviews.history(interval)


class LanguageTrafficSummary(Templated):
    def __init__(self):
        # convert language codes to real names
        language_summary = traffic.PageviewsByLanguage.top_last_month()
        locale = c.locale
        self.language_summary = []
        for language_code, data in language_summary:
            name = LanguageTraffic.get_language_name(language_code, locale)
            self.language_summary.append(((language_code, name), data))

        Templated.__init__(self)


class AdvertTrafficSummary(RedditTraffic):
    def __init__(self):
        RedditTraffic.__init__(self, _("adverts"))

    def get_tables(self):
        # overall promoted link traffic
        impressions = traffic.AdImpressionsByCodename.historical_totals("day")
        clicks = traffic.ClickthroughsByCodename.historical_totals("day")
        data = traffic.zip_timeseries(impressions, clicks)

        columns = [
            dict(color=COLORS.UPVOTE_ORANGE,
                 title=_("total impressions by day"),
                 shortname=_("impressions")),
            dict(color=COLORS.DOWNVOTE_BLUE,
                 title=_("total clicks by day"),
                 shortname=_("clicks")),
        ]

        self.totals = TimeSeriesChart("traffic-ad-totals",
                                      _("ad totals"),
                                      "day",
                                      columns,
                                      data,
                                      self.traffic_last_modified,
                                      classes=["traffic-table"])

        # get summary of top ads
        advert_summary = traffic.AdImpressionsByCodename.top_last_month()
        things = AdvertTrafficSummary.get_things(ad for ad, data
                                                 in advert_summary)
        self.advert_summary = []
        for id, data in advert_summary:
            name = AdvertTrafficSummary.get_ad_name(id, things=things)
            url = AdvertTrafficSummary.get_ad_url(id, things=things)
            self.advert_summary.append(((name, url), data))

    @staticmethod
    def split_codename(codename):
        """Codenames can be "fullname_campaign". Rend the parts asunder."""
        split_code = codename.split("_")
        fullname = "_".join(split_code[:2])
        campaign = "_".join(split_code[2:])
        return fullname, campaign

    @staticmethod
    def get_things(codes):
        fullnames = [AdvertTrafficSummary.split_codename(code)[0]
                     for code in codes
                     if code.startswith(Thing._type_prefix)]
        return Thing._by_fullname(fullnames, data=True, return_dict=True)

    @staticmethod
    def get_sr_name(name):
        if name == g.default_sr:
            return _("frontpage")
        else:
            return "/r/" + name

    @staticmethod
    def get_ad_name(code, things=None):
        if not things:
            things = AdvertTrafficSummary.get_things([code])

        thing = things.get(code)
        campaign = None

        # if it's not at first a thing, see if it's a thing with campaign
        # appended to it.
        if not thing:
            fullname, campaign = AdvertTrafficSummary.split_codename(code)
            thing = things.get(fullname)

        if not thing:
            if code.startswith("dart_"):
                srname = code.split("_", 1)[1]
                srname = AdvertTrafficSummary.get_sr_name(srname)
                return "DART: " + srname
            else:
                return code
        elif isinstance(thing, Link):
            return "Link: " + thing.title
        elif isinstance(thing, Subreddit):
            srname = AdvertTrafficSummary.get_sr_name(thing.name)
            name = "300x100: " + srname
            if campaign:
                name += " (%s)" % campaign
            return name

    @staticmethod
    def get_ad_url(code, things):
        thing = things.get(code)

        if isinstance(thing, Link):
            return "/traffic/%s" % thing._id36

        return "/traffic/adverts/%s" % code


class LanguageTraffic(RedditTraffic):
    def __init__(self, langcode):
        self.langcode = langcode
        name = LanguageTraffic.get_language_name(langcode)
        RedditTraffic.__init__(self, name)

    def get_data_for_interval(self, interval, columns):
        return traffic.PageviewsByLanguage.history(interval, self.langcode)

    @staticmethod
    def get_language_name(language_code, locale=None):
        if not locale:
            locale = c.locale

        try:
            lang_locale = babel.core.Locale.parse(language_code, sep="-")
        except (babel.core.UnknownLocaleError, ValueError):
            return language_code
        else:
            return lang_locale.get_display_name(locale)


class AdvertTraffic(RedditTraffic):
    def __init__(self, code):
        self.code = code
        name = AdvertTrafficSummary.get_ad_name(code)
        RedditTraffic.__init__(self, name)

    def get_data_for_interval(self, interval, columns):
        columns[1]["title"] = _("impressions by %s" % interval)
        columns[1]["shortname"] = _("impressions")

        columns += [
            dict(shortname=_("unique clicks")),
            dict(color=COLORS.MISCELLANEOUS,
                 title=_("clicks by %s" % interval),
                 shortname=_("total clicks")),
        ]

        imps = traffic.AdImpressionsByCodename.history(interval, self.code)
        clicks = traffic.ClickthroughsByCodename.history(interval, self.code)
        return traffic.zip_timeseries(imps, clicks)


class SubredditTraffic(RedditTraffic):
    def __init__(self):
        RedditTraffic.__init__(self, "/r/" + c.site.name)

        if c.user_is_sponsor:
            fullname = c.site._fullname
            codes = traffic.AdImpressionsByCodename.recent_codenames(fullname)
            self.codenames = [(code,
                               AdvertTrafficSummary.split_codename(code)[1])
                               for code in codes]

    def get_dow_summary(self):
        return traffic.PageviewsBySubreddit.history("day", c.site.name)

    def get_data_for_interval(self, interval, columns):
        pageviews = traffic.PageviewsBySubreddit.history(interval, c.site.name)

        if interval == "day":
            columns.append(dict(color=COLORS.MISCELLANEOUS,
                                title=_("subscriptions by day"),
                                shortname=_("subscriptions")))

            sr_name = c.site.name
            subscriptions = traffic.SubscriptionsBySubreddit.history(interval,
                                                                     sr_name)

            return traffic.zip_timeseries(pageviews, subscriptions)
        else:
            return pageviews


class PromotedLinkTraffic(RedditTraffic):
    def __init__(self, thing):
        self.thing = thing

        editable = c.user_is_sponsor or c.user._id == thing.author_id
        self.viewer_list = TrafficViewerList(thing, editable)

        RedditTraffic.__init__(self, None)

    @staticmethod
    def calculate_clickthrough_rate(impressions, clicks):
        if impressions:
            return (float(clicks) / impressions) * 100.
        else:
            return 0

    def get_tables(self):
        start, end = promote.get_total_run(self.thing)

        if not start or not end:
            self.history = []
            return

        fullname = self.thing._fullname
        imps = traffic.AdImpressionsByCodename.promotion_history(fullname,
                                                                 start, end)
        clicks = traffic.ClickthroughsByCodename.promotion_history(fullname,
                                                                   start, end)

        # promotion might have no clicks, zip_timeseries needs valid columns
        if imps and not clicks:
            clicks = [(imps[0][0], (0, 0))]

        history = traffic.zip_timeseries(imps, clicks, order="ascending")
        computed_history = []
        self.total_impressions, self.total_clicks = 0, 0
        for date, data in history:
            u_imps, imps, u_clicks, clicks = data

            u_ctr = self.calculate_clickthrough_rate(u_imps, u_clicks)
            ctr = self.calculate_clickthrough_rate(imps, clicks)

            self.total_impressions += imps
            self.total_clicks += clicks
            computed_history.append((date, data + (u_ctr, ctr)))

        self.history = computed_history

        if self.total_impressions > 0:
            self.total_ctr = ((float(self.total_clicks) /
                               self.total_impressions) * 100.)

        # the results are preliminary until 1 day after the promotion ends
        now = datetime.datetime.utcnow()
        self.is_preliminary = end + datetime.timedelta(days=1) > now

        # we should only graph a sane number of data points (not everything)
        self.max_points = traffic.points_for_interval("hour")

        return computed_history

    def as_csv(self):
        import csv
        import cStringIO

        out = cStringIO.StringIO()
        writer = csv.writer(out)

        history = self.get_tables()
        writer.writerow((_("date and time (UTC)"),
                         _("unique impressions"),
                         _("total impressions"),
                         _("unique clicks"),
                         _("total clicks"),
                         _("unique click-through rate (%)"),
                         _("total click-through rate (%)")))
        for date, values in history:
            # flatten (date, value-tuple) to (date, value1, value2...)
            writer.writerow((date,) + values)

        return out.getvalue()


class TrafficViewerList(UserList):
    """Traffic share list on /traffic/*"""
    destination = "traffic_viewer"
    remove_action = "rm_traffic_viewer"
    type = "traffic"

    def __init__(self, link, editable=True):
        self.link = link
        UserList.__init__(self, editable=editable)

    @property
    def form_title(self):
        return _("share traffic")

    @property
    def table_title(self):
        return _("current viewers")

    def user_ids(self):
        return promote.traffic_viewers(self.link)

    @property
    def container_name(self):
        return self.link._fullname
