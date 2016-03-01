from mock import MagicMock, ANY, call
from urllib import quote
from r2.tests import RedditTestCase
from r2.lib.loid import LoId, LOID_COOKIE, LOID_CREATED_COOKIE

class LoidTests(RedditTestCase):

    def test_ftue_autocreate(self):
        request = MagicMock()
        context = MagicMock()
        request.cookies = {}
        loid = LoId.load(request, create=True)
        self.assertIsNotNone(loid.loid)
        self.assertIsNotNone(loid.created)
        self.assertTrue(loid._new)

        loid.save(context)

        context.cookies.add.assert_has_calls([
            call(
                LOID_COOKIE,
                quote(loid.loid),
                expires=ANY,
            ),
            call(
                LOID_CREATED_COOKIE,
                loid.created,
                expires=ANY,
            )
        ])

    def test_ftue_nocreate(self):
        request = MagicMock()
        context = MagicMock()
        request.cookies = {}
        loid = LoId.load(request, create=False)
        self.assertIsNone(loid.loid)
        self.assertIsNone(loid.created)
        self.assertFalse(loid._new)
        loid.save(context)
        self.assertFalse(bool(context.cookies.add.called))

    def test_returning(self):
        request = MagicMock()
        context = MagicMock()
        request.cookies = {LOID_COOKIE: "foo", LOID_CREATED_COOKIE: "bar"}
        loid = LoId.load(request, create=False)
        self.assertEqual(loid.loid, "foo")
        self.assertEqual(loid.created, "bar")
        self.assertFalse(loid._new)
        loid.save(context)
        self.assertFalse(bool(context.cookies.add.called))
