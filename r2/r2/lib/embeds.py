import hashlib
import hmac

from pylons import c, g, request
from pylons.controllers.util import abort

from r2.controllers.reddit_base import UnloggedUser
from r2.lib.utils import constant_time_compare
from r2.models.subreddit import Subreddit


DISALLOWED_SR_TYPES = {"private", "gold_restricted"}


def can_embed(thing):
    try:
        sr = Subreddit._byID(thing.sr_id) if thing.sr_id else None
    except NotFound:
        sr = None

    return (sr != None and not sr.type in DISALLOWED_SR_TYPES)


def setup_embed(thing):
    embed_key = request.GET.get('embed')
    if embed_key:
        if request.host != g.media_domain:
            # don't serve up untrusted content except on our
            # specifically untrusted domain
            abort(404)

        if not can_embed(thing):
            abort(404)

        expected_mac = hmac.new(g.secrets['comment_embed'], thing._id36,
                                hashlib.sha1).hexdigest()
        if not constant_time_compare(embed_key or '', expected_mac):
            abort(401)

        c.render_style = "iframe"
        c.user = UnloggedUser([c.lang])
        c.user_is_loggedin = False
        c.forced_loggedout = True
        c.allow_framing = True
