from datetime import datetime, timedelta
import string
from urllib import quote, unquote

from .utils import randstr

LOID_COOKIE = "loid"
LOID_CREATED_COOKIE = "loidcreated"
# how long the cookie should last, by default.
EXPIRES_RELATIVE = timedelta(days=2 * 365)


LOID_LENGTH = 18
LOID_CHARSPACE = string.uppercase + string.lowercase + string.digits


def utcnow_isodate():
    # Python's `isoformat` isn't actually perfectly ISO.  This more
    # closely matches the format we were getting in JS
    d = datetime.utcnow()
    milliseconds = ("%06d" % d.microsecond)[0:3]
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + milliseconds + "Z"


def ensure_unquoted(cookie_str):
    # Some of the cookies issued in the first version of this patch ended up
    # doubly quote()d.  As a preventative measure, unquote several times.
    # [This could be a while loop, because every iteration will cause the str
    # to at worst get shorter and at best stay the same and break the loop.  I
    # just don't want to replace an escaping error with a possible infinite
    # loop.]
    for _ in range(3):
        new_str = unquote(cookie_str)
        if new_str == cookie_str:
            return new_str
        cookie_str = new_str


class LoId(object):
    """Container for holding and validating logged out ids."""

    def __init__(self):
        self.loid = None
        self.created = None
        self._new = False

    @classmethod
    def _create(cls):
        """Create and return a new logged out id and timestamp."""
        louser = cls()
        louser._new = True
        louser.loid = randstr(LOID_LENGTH, LOID_CHARSPACE)
        louser.created = utcnow_isodate()
        return louser

    @classmethod
    def load(cls, request, create=True):
        """Load loid (and timestamp) from cookie or optionally create one."""
        loid = request.cookies.get(LOID_COOKIE)
        if create and not loid:
            return cls._create()
        elif loid:
            louser = cls()
            louser.loid = unquote(loid)
            louser.created = ensure_unquoted(
                request.cookies.get(LOID_CREATED_COOKIE, ""))
            return louser
        else:
            return cls()

    def save(self, context, **cookie_attrs):
        """Write to cookie(s) if new."""
        if self._new:
            expires = datetime.utcnow() + EXPIRES_RELATIVE
            for (name, value) in (
                (LOID_COOKIE, self.loid),
                (LOID_CREATED_COOKIE, self.created),
            ):
                d = cookie_attrs.copy()
                d.setdefault("expires", expires)
                context.cookies.add(name, value, **d)

    def to_dict(self, prefix=None):
        """Serialize LoId, generally for use in the event pipeline."""
        d = {
            "loid": self.loid,
            "loid_created": self.created,
            "loid_new": self._new,
        }
        if prefix:
            d = {"{}{}".format(prefix, k): v for k, v in d.iteritems()}

        return d
