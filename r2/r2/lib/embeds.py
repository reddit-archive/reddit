from datetime import datetime
import hashlib
import hmac
import math
from pylons import c, g, request
from pylons.controllers.util import abort
import pytz

from r2.controllers.reddit_base import UnloggedUser
from r2.lib.utils import constant_time_compare
from r2.models import Account
from r2.models.subreddit import Subreddit


DISALLOWED_SR_TYPES = {"private", "gold_restricted"}


def embeddable_sr(thing):
    try:
        sr = Subreddit._byID(thing.sr_id) if thing.sr_id else None
    except NotFound:
        sr = None

    return sr if (sr is not None and sr.type not in DISALLOWED_SR_TYPES) else False


def edited_after(thing, iso_timestamp, showedits):
    if not thing:
        return False

    if not isinstance(getattr(thing, "editted", False), datetime):
        return False

    try:
        created = datetime.strptime(iso_timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        return not showedits

    created = created.replace(tzinfo=pytz.utc)

    return created < thing.editted


def setup_embed(thing, showedits):
    embed_key = request.GET.get('embed')
    if embed_key:
        if request.host != g.media_domain:
            # don't serve up untrusted content except on our
            # specifically untrusted domain
            abort(404)

        sr = embeddable_sr(thing)
        if not sr:
            abort(404)

        expected_mac = hmac.new(g.secrets['comment_embed'], thing._id36,
                                hashlib.sha1).hexdigest()
        if not constant_time_compare(embed_key or '', expected_mac):
            abort(401)

        try:
            author = Account._byID(thing.author_id) if thing.author_id else None
        except NotFound:
            author = None

        iso_timestamp = request.GET.get("created", "")

        c.embed_config = {
            "logged": c.user_is_loggedin,
            "stats_domain": g.stats_domain or "",
            "created": iso_timestamp,
            "showedits": showedits,
            "thing": {
                "id": thing._id,
                "sr_id": sr._id,
                "sr_name": sr.name,
                "edited": edited_after(thing, iso_timestamp, showedits),
                "deleted": thing.deleted or author._deleted,
            },
        }

        c.render_style = "iframe"
        c.user = UnloggedUser([c.lang])
        c.user_is_loggedin = False
        c.forced_loggedout = True
        c.allow_framing = True


def is_embed():
    return c.render_style == "iframe"
