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

from r2.lib.db.thing import Thing, Relation, NotFound
from r2.lib.db.operators import asc, desc, lower
from r2.lib.memoize import memoize
from r2.models import Subreddit
from pylons import c, g, request

class Ad (Thing):
    _defaults = dict(
        codename = None,
        imgurl = None,
        linkurl = None,
        raw_html = None,
        )

    @classmethod
    @memoize('ad.all_ads')
    def _all_ads_cache(cls):
        return [ a._id for a in Ad._query(sort=desc('_date'), limit=1000) ]

    @classmethod
    def _all_ads(cls, _update=False):
        all = cls._all_ads_cache(_update=_update)
        # Can't just return Ad._byID() results because
        # the ordering will be lost
        d = Ad._byID(all, data=True)
        return [ d[id] for id in all ]

    @classmethod
    def _new(cls, codename, imgurl, raw_html, linkurl):
        a = Ad(codename=codename, imgurl=imgurl, raw_html=raw_html,
               linkurl=linkurl)
        a._commit()
        Ad._all_ads_cache(_update=True)

    @classmethod
    def _by_codename(cls, codename):
        q = cls._query(lower(Ad.c.codename) == codename.lower())
        q._limit = 1
        ad = list(q)

        if ad:
            return cls._byID(ad[0]._id, True)
        else:
            raise NotFound, 'Ad %s' % codename

    def url(self):
        return "%s/ads/%s" % (g.ad_domain, self.codename)

    def submit_link(self):
        from r2.lib.template_helpers import get_domain
        from mako.filters import url_escape

        d = get_domain(subreddit=False)
        u = self.url()

        return "http://%s/r/ads/submit?url=%s" % (d, url_escape(u))

    def rendering(self):
        if self.raw_html:
            return self.raw_html
        else:
            return "<img src='%s' />" % self.imgurl

    def important_attrs(self):
        return dict(rendering=self.rendering(), linkurl=self.linkurl,
                    submit_link=self.submit_link())

class AdSR(Relation(Ad, Subreddit)):
    @classmethod
    def _new(cls, ad, sr, weight=100):
        t = AdSR(ad, sr, "adsr")
        t.weight = weight
        t._commit()

        AdSR.by_ad(ad, _update=True)
        AdSR.by_sr(sr, _update=True)

    @classmethod
    @memoize('adsr.by_ad')
    def by_ad_cache(cls, ad_id):
        q = AdSR._query(AdSR.c._thing1_id == ad_id,
                        sort = desc('_date'))
        q._limit = 500
        return [ t._id for t in q ]

    @classmethod
    def by_ad(cls, ad, _update=False):
        rel_ids = cls.by_ad_cache(ad._id, _update=_update)
        adsrs = AdSR._byID_rel(rel_ids, data=True, eager_load=True,
                               thing_data=True, return_dict = False)
        return adsrs

    @classmethod
    @memoize('adsr.by_sr')
    def by_sr_cache(cls, sr_id):
        q = AdSR._query(AdSR.c._thing2_id == sr_id,
                        sort = desc('_date'))
        q._limit = 500
        return [ t._id for t in q ]

    @classmethod
    def by_sr(cls, sr, _update=False):
        rel_ids = cls.by_sr_cache(sr._id, _update=_update)
        adsrs = AdSR._byID_rel(rel_ids, data=True, eager_load=True,
                               thing_data=True, return_dict = False)
        return adsrs

    @classmethod
    def by_sr_merged(cls, sr, _update=False):
        if sr.name == g.default_sr:
            return cls.by_sr(sr)

        my_adsrs =     cls.by_sr(sr)
        global_adsrs = cls.by_sr(Subreddit._by_name(g.default_sr, stale=True))

        seen = {}
        for adsr in my_adsrs:
            seen[adsr._thing1.codename] = True
        for adsr in global_adsrs:
            if adsr._thing1.codename not in seen:
                my_adsrs.append(adsr)

        return my_adsrs

    @classmethod
    def by_ad_and_sr(cls, ad, sr):
        q = cls._fast_query(ad, sr, "adsr")
        return q.values()[0]
