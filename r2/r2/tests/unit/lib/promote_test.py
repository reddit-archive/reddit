import unittest

from mock import MagicMock

from r2.lib.promote import srnames_from_site
from r2.models import Account, FakeAccount, Frontpage, Subreddit, MultiReddit


subscriptions_srnames = ["foo", "bar"]
subscriptions = map(lambda srname: Subreddit(name=srname), subscriptions_srnames)
multi_srnames = ["bing", "bat"]
multi_subreddits = map(lambda srname: Subreddit(name=srname), multi_srnames)
nice_srname = "mylittlepony"
nsfw_srname = "pr0n"
quarantined_srname = "croontown"
naughty_subscriptions = [
    Subreddit(name=nice_srname),
    Subreddit(name=nsfw_srname, over_18=True),
    Subreddit(name=quarantined_srname, quarantine=True),
]

user_subreddits = Subreddit.user_subreddits

class TestSRNamesFromSite(unittest.TestCase):
    def setUp(self):
        self.logged_in = Account(name="test")
        self.logged_out = FakeAccount()

    def tearDown(self):
        Subreddit.user_subreddits = user_subreddits

    def test_frontpage_logged_out(self):
        srnames = srnames_from_site(self.logged_out, Frontpage)

        self.assertEqual(srnames, {Frontpage.name})

    def test_frontpage_logged_in(self):
        Subreddit.user_subreddits = MagicMock(return_value=subscriptions)
        srnames = srnames_from_site(self.logged_in, Frontpage)

        self.assertEqual(srnames, set(subscriptions_srnames) | {Frontpage.name})

    def test_multi_logged_out(self):
        multi = MultiReddit(path="/user/test/m/multi_test", srs=multi_subreddits)
        srnames = srnames_from_site(self.logged_out, multi)

        self.assertEqual(srnames, set(multi_srnames))

    def test_multi_logged_in(self):
        Subreddit.user_subreddits = MagicMock(return_value=subscriptions)
        multi = MultiReddit(path="/user/test/m/multi_test", srs=multi_subreddits)
        srnames = srnames_from_site(self.logged_in, multi)

        self.assertEqual(srnames, set(multi_srnames) | set(subscriptions_srnames))

    def test_subreddit_logged_out(self):
        srname = "test1"
        subreddit = Subreddit(name=srname)
        srnames = srnames_from_site(self.logged_out, subreddit)

        self.assertEqual(srnames, {srname})

    def test_subreddit_logged_in(self):
        Subreddit.user_subreddits = MagicMock(return_value=subscriptions)
        srname = "test1"
        subreddit = Subreddit(name=srname)
        srnames = srnames_from_site(self.logged_in, subreddit)

        self.assertEqual(srnames, {srname} | set(subscriptions_srnames))

    def test_quarantined_subscriptions_are_never_included(self):
        Subreddit.user_subreddits = MagicMock(return_value=naughty_subscriptions)
        srname = "test1"
        subreddit = Subreddit(name=srname)
        srnames = srnames_from_site(self.logged_in, subreddit)

        self.assertEqual(srnames, {srname} | {nice_srname})
        self.assertTrue(len(srnames & {quarantined_srname}) == 0)

    def test_nsfw_subscriptions_arent_included_when_viewing_frontpage(self):
        Subreddit.user_subreddits = MagicMock(return_value=naughty_subscriptions)
        srnames = srnames_from_site(self.logged_in, Frontpage)

        self.assertEqual(srnames, {Frontpage.name} | {nice_srname})
        self.assertTrue(len(srnames & {nsfw_srname}) == 0)

    def test_nsfw_subscriptions_arent_included_when_viewing_sfw(self):
        Subreddit.user_subreddits = MagicMock(return_value=naughty_subscriptions)
        srname = "test1"
        subreddit = Subreddit(name=srname)
        srnames = srnames_from_site(self.logged_in, subreddit)

        self.assertEqual(srnames, {srname} | {nice_srname})
        self.assertTrue(len(srnames & {nsfw_srname}) == 0)

    def test_only_nsfw_subscriptions_are_included_when_viewing_nswf(self):
        Subreddit.user_subreddits = MagicMock(return_value=naughty_subscriptions)
        srname = "bad"
        subreddit = Subreddit(name=srname, over_18=True)
        srnames = srnames_from_site(self.logged_in, subreddit)

        self.assertEqual(srnames, {srname} | {nsfw_srname})
        self.assertTrue(len(srnames & {nsfw_srname}) == 1)
        self.assertTrue(len(srnames & {nice_srname}) == 0)
