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

from urllib import urlencode
import base64
import simplejson

from pylons import c, g, request
from pylons.i18n import _
from r2.config.extensions import set_extension
from r2.lib.base import abort
from reddit_base import RedditController, MinimalController, require_https
from r2.lib.db.thing import NotFound
from r2.models import Account
from r2.models.token import (
    OAuth2Client, OAuth2AuthorizationCode, OAuth2AccessToken, OAuth2Scope)
from r2.controllers.errors import ForbiddenError, errors
from validator import validate, VRequired, VOneOf, VUser, VModhash, VOAuth2ClientID, VOAuth2Scope
from r2.lib.pages import OAuth2AuthorizationPage
from r2.lib.require import RequirementException, require, require_split
from r2.lib.utils import parse_http_basic

class OAuth2FrontendController(RedditController):
    def pre(self):
        RedditController.pre(self)
        require_https()

    def _check_redirect_uri(self, client, redirect_uri):
        if not redirect_uri or not client or redirect_uri != client.redirect_uri:
            abort(ForbiddenError(errors.OAUTH2_INVALID_REDIRECT_URI))

    def _error_response(self, state, redirect_uri):
        """Return an error redirect, but only if client_id and redirect_uri are valid."""

        resp = {"state": state}

        if (errors.OAUTH2_INVALID_CLIENT, "client_id") in c.errors:
            resp["error"] = "unauthorized_client"
        elif (errors.OAUTH2_ACCESS_DENIED, "authorize") in c.errors:
            resp["error"] = "access_denied"
        elif (errors.BAD_HASH, None) in c.errors:
            resp["error"] = "access_denied"
        elif (errors.INVALID_OPTION, "response_type") in c.errors:
            resp["error"] = "unsupported_response_type"
        elif (errors.OAUTH2_INVALID_SCOPE, "scope") in c.errors:
            resp["error"] = "invalid_scope"
        else:
            resp["error"] = "invalid_request"

        return self.redirect(redirect_uri+"?"+urlencode(resp), code=302)

    @validate(VUser(),
              response_type = VOneOf("response_type", ("code",)),
              client = VOAuth2ClientID(),
              redirect_uri = VRequired("redirect_uri", errors.OAUTH2_INVALID_REDIRECT_URI),
              scope = VOAuth2Scope(),
              state = VRequired("state", errors.NO_TEXT))
    def GET_authorize(self, response_type, client, redirect_uri, scope, state):
        """
        First step in [OAuth 2.0](http://oauth.net/2/) authentication.
        End users will be prompted for their credentials (username/password)
        and asked if they wish to authorize the application identified by
        the **client_id** parameter with the permissions specified by the
        **scope** parameter.  They are then redirected to the endpoint on
        the client application's side specified by **redirect_uri**.

        If the user granted permission to the application, the response will
        contain a **code** parameter with a temporary authorization code
        which can be exchanged for an access token at
        [/api/v1/access_token](#api_method_access_token).

        **redirect_uri** must match the URI configured for the client in the
        [app preferences](/prefs/apps).  If **client_id** or **redirect_uri**
        is not valid, or if the call does not take place over SSL, a 403
        error will be returned.  For all other errors, a redirect to
        **redirect_uri** will be returned, with a **error** parameter
        indicating why the request failed.
        """

        self._check_redirect_uri(client, redirect_uri)

        if not c.errors:
            c.deny_frames = True
            return OAuth2AuthorizationPage(client, redirect_uri, scope, state).render()
        else:
            return self._error_response(state, redirect_uri)

    @validate(VUser(),
              VModhash(fatal=False),
              client = VOAuth2ClientID(),
              redirect_uri = VRequired("redirect_uri", errors.OAUTH2_INVALID_REDIRECT_URI),
              scope = VOAuth2Scope(),
              state = VRequired("state", errors.NO_TEXT),
              authorize = VRequired("authorize", errors.OAUTH2_ACCESS_DENIED))
    def POST_authorize(self, authorize, client, redirect_uri, scope, state):
        """Endpoint for OAuth2 authorization."""

        self._check_redirect_uri(client, redirect_uri)

        if not c.errors:
            code = OAuth2AuthorizationCode._new(client._id, redirect_uri,
                                                c.user._id36, scope)
            resp = {"code": code._id, "state": state}
            return self.redirect(redirect_uri+"?"+urlencode(resp), code=302)
        else:
            return self._error_response(state, redirect_uri)

class OAuth2AccessController(MinimalController):
    def pre(self):
        set_extension(request.environ, "json")
        MinimalController.pre(self)
        require_https()
        c.oauth2_client = self._get_client_auth()

    def _get_client_auth(self):
        auth = request.headers.get("Authorization")
        try:
            client_id, client_secret = parse_http_basic(auth)
            client = OAuth2Client.get_token(client_id)
            require(client)
            require(client.secret == client_secret)
            return client
        except RequirementException:
            abort(401, headers=[("WWW-Authenticate", 'Basic realm="reddit"')])

    @validate(grant_type = VOneOf("grant_type", ("authorization_code",)),
              code = VRequired("code", errors.NO_TEXT),
              redirect_uri = VRequired("redirect_uri", errors.OAUTH2_INVALID_REDIRECT_URI))
    def POST_access_token(self, grant_type, code, redirect_uri):
        """
        Exchange an [OAuth 2.0](http://oauth.net/2/) authorization code
        (from [/api/v1/authorize](#api_method_authorize)) for an access token.

        On success, returns a URL-encoded dictionary containing
        **access_token**, **token_type**, **expires_in**, and **scope**.
        If there is a problem, an **error** parameter will be returned
        instead.

        Must be called using SSL, and must contain a HTTP `Authorization:`
        header which contains the application's client identifier as the
        username and client secret as the password.  (The client id and secret
        are visible on the [app preferences page](/prefs/apps).)

        Per the OAuth specification, **grant_type** must
        be ``authorization_code`` and **redirect_uri** must exactly match the
        value that was used in the call to
        [/api/v1/authorize](#api_method_authorize).
        """

        resp = {}
        if not c.errors:
            auth_token = OAuth2AuthorizationCode.use_token(code, c.oauth2_client._id, redirect_uri)
            if auth_token:
                access_token = OAuth2AccessToken._new(auth_token.client_id, auth_token.user_id, auth_token.scope)
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
            access_token = OAuth2AccessToken.get_token(self._get_bearer_token())
            require(access_token)
            require(access_token.check_valid())
            c.oauth2_access_token = access_token
            account = Account._byID36(access_token.user_id, data=True)
            require(account)
            require(not account._deleted)
            c.oauth_user = account
        except RequirementException:
            self._auth_error(401, "invalid_token")

        handler = self._get_action_handler()
        if handler:
            oauth2_perms = getattr(handler, "oauth2_perms", None)
            if oauth2_perms:
                grant = OAuth2Scope(access_token.scope)
                if grant.subreddit_only and c.site.name not in grant.subreddits:
                    self._auth_error(403, "insufficient_scope")
                required_scopes = set(oauth2_perms['allowed_scopes'])
                if not (grant.scopes >= required_scopes):
                    self._auth_error(403, "insufficient_scope")
            else:
                self._auth_error(400, "invalid_request")

    def check_for_bearer_token(self):
        if self._get_bearer_token(strict=False):
            OAuth2ResourceController.pre(self)
            if c.oauth_user:
                c.user = c.oauth_user
                c.user_is_loggedin = True

    def _auth_error(self, code, error):
        abort(code, headers=[("WWW-Authenticate", 'Bearer realm="reddit", error="%s"' % error)])

    def _get_bearer_token(self, strict=True):
        auth = request.headers.get("Authorization")
        try:
            auth_scheme, bearer_token = require_split(auth, 2)
            require(auth_scheme.lower() == "bearer")
            return bearer_token
        except RequirementException:
            if strict:
                self._auth_error(400, "invalid_request")

def require_oauth2_scope(*scopes):
    def oauth2_scope_wrap(fn):
        fn.oauth2_perms = {"allowed_scopes": scopes}
        return fn
    return oauth2_scope_wrap
