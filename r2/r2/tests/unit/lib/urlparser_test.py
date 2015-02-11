#!/usr/bin/env python
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
# All portions of the code written by reddit are Copyright (c) 2006-2015 reddit
# Inc. All Rights Reserved.
###############################################################################
import unittest

from r2.lib.utils import UrlParser
from r2.tests import stage_for_paste
from pylons import g


class TestIsRedditURL(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        stage_for_paste()
        cls._old_offsite = g.offsite_subdomains
        g.offsite_subdomains = ["blog"]

    @classmethod
    def tearDownClass(cls):
        g.offsite_subdomains = cls._old_offsite

    def _is_safe_reddit_url(self, url, subreddit=None):
        web_safe = UrlParser(url).is_web_safe_url()
        return web_safe and UrlParser(url).is_reddit_url(subreddit)

    def assertIsSafeRedditUrl(self, url, subreddit=None):
        self.assertTrue(self._is_safe_reddit_url(url, subreddit))

    def assertIsNotSafeRedditUrl(self, url, subreddit=None):
        self.assertFalse(self._is_safe_reddit_url(url, subreddit))

    def test_normal_urls(self):
        self.assertIsSafeRedditUrl("https://%s/" % g.domain)
        self.assertIsSafeRedditUrl("https://en.%s/" % g.domain)
        self.assertIsSafeRedditUrl("https://foobar.baz.%s/quux/?a" % g.domain)
        self.assertIsSafeRedditUrl("#anchorage")
        self.assertIsSafeRedditUrl("?path_relative_queries")
        self.assertIsSafeRedditUrl("/")
        self.assertIsSafeRedditUrl("/cats")
        self.assertIsSafeRedditUrl("/cats/")
        self.assertIsSafeRedditUrl("/cats/#maru")
        self.assertIsSafeRedditUrl("//foobaz.%s/aa/baz#quux" % g.domain)
        # XXX: This is technically a legal relative URL, are there any UAs
        # stupid enough to treat this as absolute?
        self.assertIsSafeRedditUrl("path_relative_subpath.com")
        # "blog.reddit.com" is not a reddit URL.
        self.assertIsNotSafeRedditUrl("http://blog.%s/" % g.domain)
        self.assertIsNotSafeRedditUrl("http://foo.blog.%s/" % g.domain)

    def test_incorrect_anchoring(self):
        self.assertIsNotSafeRedditUrl("http://www.%s.whatever.com/" % g.domain)

    def test_protocol_relative(self):
        self.assertIsNotSafeRedditUrl("//foobaz.example.com/aa/baz#quux")

    def test_weird_protocols(self):
        self.assertIsNotSafeRedditUrl(
            "javascript://%s/%%0d%%0aalert(1)" % g.domain
        )
        self.assertIsNotSafeRedditUrl("hackery:whatever")

    def test_http_auth(self):
        # There's no legitimate reason to include HTTP auth details in the URL,
        # they only serve to confuse everyone involved.
        # For example, this used to be the behaviour of `UrlParser`, oops!
        # > UrlParser("http://everyoneforgets:aboutthese@/baz.com/").unparse()
        # 'http:///baz.com/'
        self.assertIsNotSafeRedditUrl("http://foo:bar@/example.com/")

    def test_browser_quirks(self):
        # Some browsers try to be helpful and ignore characters in URLs that
        # they think might have been accidental (I guess due to things like:
        # `<a href=" http://badathtml.com/ ">`. We need to ignore those when
        # determining if a URL is local.
        self.assertIsNotSafeRedditUrl("/\x00/example.com")
        self.assertIsNotSafeRedditUrl("\x09//example.com")
        self.assertIsNotSafeRedditUrl(" http://example.com/")

        # This is makes sure we're not vulnerable to a bug in
        # urlparse / urlunparse.
        # urlunparse(urlparse("////foo.com")) == "//foo.com"! screwy!
        self.assertIsNotSafeRedditUrl("////example.com/")
        self.assertIsNotSafeRedditUrl("//////example.com/")
        # Similar, but with a scheme
        self.assertIsNotSafeRedditUrl(r"http:///example.com/")
        # Webkit and co like to treat backslashes as equivalent to slashes in
        # different places, maybe to make OCD Windows users happy.
        self.assertIsNotSafeRedditUrl(r"/\example.com/")
        # On chrome this goes to example.com, not a subdomain of reddit.com!
        self.assertIsNotSafeRedditUrl(
            r"http://\\example.com\a.%s/foo" % g.domain
        )

        # Combo attacks!
        self.assertIsNotSafeRedditUrl(r"///\example.com/")
        self.assertIsNotSafeRedditUrl(r"\\example.com")
        self.assertIsNotSafeRedditUrl("/\x00//\\example.com/")
        self.assertIsNotSafeRedditUrl(
            "\x09javascript://%s/%%0d%%0aalert(1)" % g.domain
        )
        self.assertIsNotSafeRedditUrl(
            "http://\x09example.com\\%s/foo" % g.domain
        )

    def test_url_mutation(self):
        u = UrlParser("http://example.com/")
        u.hostname = g.domain
        self.assertTrue(u.is_reddit_url())

        u = UrlParser("http://%s/" % g.domain)
        u.hostname = "example.com"
        self.assertFalse(u.is_reddit_url())

    def test_nbsp_allowances(self):
        # We have to allow nbsps in URLs, let's just allow them where they can't
        # do any damage.
        self.assertIsNotSafeRedditUrl("http://\xa0.%s/" % g.domain)
        self.assertIsNotSafeRedditUrl("\xa0http://%s/" % g.domain)
        self.assertIsSafeRedditUrl("http://%s/\xa0" % g.domain)
        self.assertIsSafeRedditUrl("/foo/bar/\xa0baz")


class TestSwitchSubdomainByExtension(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._old_domain = g.domain
        g.domain = 'reddit.com'
        cls._old_domain_prefix = g.domain_prefix
        g.domain_prefix = 'www'

    @classmethod
    def tearDownClass(cls):
        g.domain = cls._old_domain
        g.domain_prefix = cls._old_domain_prefix

    def test_normal_urls(self):
        u = UrlParser('http://www.reddit.com/r/redditdev')
        u.switch_subdomain_by_extension('compact')
        result = u.unparse()
        self.assertEquals('http://i.reddit.com/r/redditdev', result)

        u = UrlParser(result)
        u.switch_subdomain_by_extension('mobile')
        result = u.unparse()
        self.assertEquals('http://m.reddit.com/r/redditdev', result)

    def test_default_prefix(self):
        u = UrlParser('http://i.reddit.com/r/redditdev')
        u.switch_subdomain_by_extension()
        self.assertEquals('http://www.reddit.com/r/redditdev', u.unparse())

        u = UrlParser('http://i.reddit.com/r/redditdev')
        u.switch_subdomain_by_extension('does-not-exist')
        self.assertEquals('http://www.reddit.com/r/redditdev', u.unparse())
