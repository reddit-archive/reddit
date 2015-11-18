import unittest

from mock import MagicMock, patch

from r2.lib.promote import (
    get_nsfw_collections_srnames,
    srnames_from_site,
)
from r2.models import (
    Account,
    Collection,
    FakeAccount,
    Frontpage,
    Subreddit,
    MultiReddit,
)

# use the original function to avoid going out to memcached.
get_nsfw_collections_srnames = get_nsfw_collections_srnames.memoized_fn

subscriptions_srnames = ["foo", "bar"]
subscriptions = map(lambda srname: Subreddit(name=srname), subscriptions_srnames)
multi_srnames = ["bing", "bat"]
multi_subreddits = map(lambda srname: Subreddit(name=srname), multi_srnames)
nice_srname = "mylittlepony"
nsfw_srname = "pr0n"
questionably_nsfw = "sexstories"
quarantined_srname = "croontown"
naughty_subscriptions = [
    Subreddit(name=nice_srname),
    Subreddit(name=nsfw_srname, over_18=True),
    Subreddit(name=quarantined_srname, quarantine=True),
]
nsfw_collection_srnames = [questionably_nsfw, nsfw_srname]
nsfw_collection = Collection(
    name="after dark",
    sr_names=nsfw_collection_srnames,
    over_18=True
)

class TestSRNamesFromSite(unittest.TestCase):
    def setUp(self):
        self.logged_in = Account(name="test")
        self.logged_out = FakeAccount()

    def test_frontpage_logged_out(self):
        srnames = srnames_from_site(self.logged_out, Frontpage)

        self.assertEqual(srnames, {Frontpage.name})

    @patch("r2.models.Subreddit.user_subreddits")
    def test_frontpage_logged_in(self, user_subreddits):
        user_subreddits.return_value = subscriptions
        srnames = srnames_from_site(self.logged_in, Frontpage)

        self.assertEqual(srnames, set(subscriptions_srnames) | {Frontpage.name})

    def test_multi_logged_out(self):
        multi = MultiReddit(path="/user/test/m/multi_test", srs=multi_subreddits)
        srnames = srnames_from_site(self.logged_out, multi)

        self.assertEqual(srnames, set(multi_srnames))

    @patch("r2.models.Subreddit.user_subreddits")
    def test_multi_logged_in(self, user_subreddits):
        user_subreddits.return_value = subscriptions
        multi = MultiReddit(path="/user/test/m/multi_test", srs=multi_subreddits)
        srnames = srnames_from_site(self.logged_in, multi)

        self.assertEqual(srnames, set(multi_srnames))

    def test_subreddit_logged_out(self):
        srname = "test1"
        subreddit = Subreddit(name=srname)
        srnames = srnames_from_site(self.logged_out, subreddit)

        self.assertEqual(srnames, {srname})

    @patch("r2.models.Subreddit.user_subreddits")
    def test_subreddit_logged_in(self, user_subreddits):
        user_subreddits.return_value = subscriptions
        srname = "test1"
        subreddit = Subreddit(name=srname)
        srnames = srnames_from_site(self.logged_in, subreddit)

        self.assertEqual(srnames, {srname})

    @patch("r2.models.Subreddit.user_subreddits")
    def test_quarantined_subscriptions_are_never_included(self, user_subreddits):
        user_subreddits.return_value = naughty_subscriptions
        subreddit = Frontpage
        srnames = srnames_from_site(self.logged_in, subreddit)

        self.assertEqual(srnames, {subreddit.name} | {nice_srname})
        self.assertTrue(len(srnames & {quarantined_srname}) == 0)

    @patch("r2.models.Subreddit.user_subreddits")
    def test_nsfw_subscriptions_arent_included_when_viewing_frontpage(self, user_subreddits):
        user_subreddits.return_value = naughty_subscriptions
        srnames = srnames_from_site(self.logged_in, Frontpage)

        self.assertEqual(srnames, {Frontpage.name} | {nice_srname})
        self.assertTrue(len(srnames & {nsfw_srname}) == 0)

    @patch("r2.models.Collection.get_all")
    def test_get_nsfw_collections_srnames(self, get_all):
        get_all.return_value = [nsfw_collection]
        srnames = get_nsfw_collections_srnames()

        self.assertEqual(srnames, set(nsfw_collection_srnames))

    @patch("r2.lib.promote.get_nsfw_collections_srnames")
    def test_remove_nsfw_collection_srnames_on_frontpage(self, get_nsfw_collections_srnames):
        get_nsfw_collections_srnames.return_value = set(nsfw_collection.sr_names)
        srname = "test1"
        subreddit = Subreddit(name=srname)
        Subreddit.user_subreddits = MagicMock(return_value=[
            Subreddit(name=nice_srname),
            Subreddit(name=questionably_nsfw),
        ])

        frontpage_srnames = srnames_from_site(self.logged_in, Frontpage)
        swf_srnames = srnames_from_site(self.logged_in, subreddit)

        self.assertEqual(frontpage_srnames, {Frontpage.name, nice_srname})
        self.assertTrue(len(frontpage_srnames & {questionably_nsfw}) == 0)

