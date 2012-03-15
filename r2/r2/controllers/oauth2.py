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
# The Original Code is Reddit.
#
# The Original Developer is the Initial Developer.  The Initial Developer of the
# Original Code is CondeNet, Inc.
#
# All portions of the code written by CondeNet are Copyright (c) 2006-2010
# CondeNet, Inc. All Rights Reserved.
################################################################################
from urllib import urlencode
import base64
import simplejson

from pylons import c, g, request
from pylons.controllers.util import abort
from pylons.i18n import _
from r2.config.extensions import set_extension
from reddit_base import RedditController, MinimalController, require_https
from r2.lib.db.thing import NotFound
from r2.models import Account
from r2.models.oauth2 import OAuth2Client, OAuth2AuthorizationCode, OAuth2AccessToken
from r2.controllers.errors import errors
from validator import validate, VRequired, VOneOf, VUrl, VUser, VModhash
from r2.lib.pages import OAuth2AuthorizationPage
from r2.lib.require import RequirementException, require, require_split

scope_info = {
    "identity": {
        "id": "identity",
        "name": _("My Identity"),
        "description": _("Access my reddit username and signup date.")
    }
}

class VClientID(VRequired):
    default_param = "client_id"
    def __init__(self, param=None, *a, **kw):
        VRequired.__init__(self, param, errors.OAUTH2_INVALID_CLIENT, *a, **kw)

    def run(self, client_id):
        if not client_id:
            return self.error()

        client = OAuth2Client.get_token(client_id)
        if client:
            return client
        else:
            return self.error()

class OAuth2FrontendController(RedditController):
    def pre(self):
        RedditController.pre(self)
        require_https()

    def _check_redirect_uri(self, client, redirect_uri):
        if not redirect_uri or not client or redirect_uri != client.redirect_uri:
            abort(403)

    def _error_response(self, resp):
        if (errors.OAUTH2_INVALID_CLIENT, "client_id") in c.errors:
            resp["error"] = "unauthorized_client"
        elif (errors.OAUTH2_ACCESS_DENIED, "authorize") in c.errors:
            resp["error"] = "access_denied"
        elif (errors.BAD_HASH, None) in c.errors:
            resp["error"] = "access_denied"
        elif (errors.INVALID_OPTION, "response_type") in c.errors:
            resp["error"] = "unsupported_response_type"
        elif (errors.INVALID_OPTION, "scope") in c.errors:
            resp["error"] = "invalid_scope"
        else:
            resp["error"] = "invalid_request"

    @validate(VUser(),
              response_type = VOneOf("response_type", ("code",)),
              client = VClientID(),
              redirect_uri = VUrl("redirect_uri", allow_self=False, lookup=False),
              scope = VOneOf("scope", scope_info.keys()),
              state = VRequired("state", errors.NO_TEXT))
    def GET_authorize(self, response_type, client, redirect_uri, scope, state):
        """Endpoint for OAuth2 authorization."""

        self._check_redirect_uri(client, redirect_uri)

        resp = {}
        if not c.errors:
            c.deny_frames = True
            return OAuth2AuthorizationPage(client, redirect_uri, scope_info[scope], state).render()
        else:
            self._error_response(resp)
            return self.redirect(redirect_uri+"?"+urlencode(resp), code=302)

    @validate(VUser(),
              VModhash(fatal=False),
              client = VClientID(),
              redirect_uri = VUrl("redirect_uri", allow_self=False, lookup=False),
              scope = VOneOf("scope", scope_info.keys()),
              state = VRequired("state", errors.NO_TEXT),
              authorize = VRequired("authorize", errors.OAUTH2_ACCESS_DENIED))
    def POST_authorize(self, authorize, client, redirect_uri, scope, state):
        """Endpoint for OAuth2 authorization."""

        self._check_redirect_uri(client, redirect_uri)

        resp = {}
        if state:
            resp["state"] = state

        if not c.errors:
            code = OAuth2AuthorizationCode._new(client._id, redirect_uri, c.user._id, scope)
            resp["code"] = code._id
        else:
            self._error_response(resp)

        return self.redirect(redirect_uri+"?"+urlencode(resp), code=302)

class OAuth2AccessController(MinimalController):
    def pre(self):
        set_extension(request.environ, "json")
        MinimalController.pre(self)
        require_https()
        c.oauth2_client = self._get_client_auth()

    def _get_client_auth(self):
        auth = request.headers.get("Authorization")
        try:
            auth_scheme, auth_token = require_split(auth, 2)
            require(auth_scheme.lower() == "basic")
            try:
                auth_data = base64.b64decode(auth_token)
            except TypeError:
                raise RequirementException
            client_id, client_secret = require_split(auth_data, 2, ":")
            client = OAuth2Client.get_token(client_id)
            require(client)
            require(client.secret == client_secret)
            return client
        except RequirementException:
            abort(401, headers=[("WWW-Authenticate", 'Basic realm="reddit"')])

    @validate(grant_type = VOneOf("grant_type", ("authorization_code",)),
              code = VRequired("code", errors.NO_TEXT),
              redirect_uri = VUrl("redirect_uri", allow_self=False, lookup=False))
    def POST_access_token(self, grant_type, code, redirect_uri):
        resp = {}
        if not c.errors:
            auth_token = OAuth2AuthorizationCode.use_token(code, c.oauth2_client._id, redirect_uri)
            if auth_token:
                access_token = OAuth2AccessToken._new(auth_token.user_id, auth_token.scope)
                resp["access_token"] = access_token._id
                resp["token_type"] = access_token.token_type
                resp["expires_in"] = access_token._ttl
                resp["scope"] = auth_token.scope
            else:
                resp["error"] = "invalid_grant"
        else:
            if (errors.INVALID_OPTION, "grant_type") in c.errors:
                resp["error"] = "unsupported_grant_type"
            elif (errors.INVALID_OPTION, "scope") in c.errors:
                resp["error"] = "invalid_scope"
            else:
                resp["error"] = "invalid_request"

        return self.api_wrapper(resp)

class OAuth2ResourceController(MinimalController):
    def pre(self):
        set_extension(request.environ, "json")
        MinimalController.pre(self)
        require_https()

        try:
            access_token = self._get_bearer_token()
            require(access_token)
            c.oauth2_access_token = access_token
            account = Account._byID(access_token.user_id, data=True)
            require(account)
            require(not account._deleted)
            c.oauth_user = account
        except RequirementException:
            self._auth_error(401, "invalid_token")

        handler = self._get_action_handler()
        if handler:
            oauth2_perms = getattr(handler, "oauth2_perms", None)
            if oauth2_perms:
                if access_token.scope not in oauth2_perms["allowed_scopes"]:
                    self._auth_error(403, "insufficient_scope")
            else:
                self._auth_error(400, "invalid_request")

    def _auth_error(self, code, error):
        abort(code, headers=[("WWW-Authenticate", 'Bearer realm="reddit", error="%s"' % error)])

    def _get_bearer_token(self):
        auth = request.headers.get("Authorization")
        try:
            auth_scheme, bearer_token = require_split(auth, 2)
            require(auth_scheme.lower() == "bearer")
            return OAuth2AccessToken.get_token(bearer_token)
        except RequirementException:
            self._auth_error(400, "invalid_request")

def require_oauth2_scope(*scopes):
    def oauth2_scope_wrap(fn):
        fn.oauth2_perms = {"allowed_scopes": scopes}
        return fn
    return oauth2_scope_wrap
