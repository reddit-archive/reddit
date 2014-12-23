from pylons import c, g, request
from pylons.controllers.util import abort

from r2.controllers.reddit_base import (
    get_browser_langs,
    UnloggedUser,
)

def setup_embed():
    if request.GET.get("embed") == "true":
        if request.host != g.media_domain:
            # don't serve up untrusted content except on our
            # specifically untrusted domain
            abort(404)

        c.render_style = "iframe"
        c.user = UnloggedUser(get_browser_langs())
        c.user_is_loggedin = False
        c.forced_loggedout = True
        c.allow_framing = True
