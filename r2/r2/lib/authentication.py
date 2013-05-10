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
# All portions of the code written by reddit are Copyright (c) 2006-2013 reddit
# Inc. All Rights Reserved.
###############################################################################
"""Authentication providers for setting c.user on every request.

This system is intended to allow pluggable authentication for intranets etc. It
is not intended to cover all login/logout functionality and in non-cookie
scenarios those are probably nonsensical to allow user control of (i.e.
single-signon on an intranet doesn't generally allow new account creation on a
single website.)
"""

import bcrypt
from pylons import g, c, request
from urllib import unquote

from r2.models import Account, NotFound
from r2.lib.utils import constant_time_compare, parse_http_basic
from r2.lib.require import RequirementException


_AUTHENTICATION_PROVIDERS = {}


def authentication_provider(allow_logout):
    """Register an authentication provider with the framework.

    Authentication providers should return None if authentication failed or an
    Account object if it succeeded.
    """
    def authentication_provider_decorator(fn):
        _AUTHENTICATION_PROVIDERS[fn.__name__] = fn
        fn.allow_logout = allow_logout
        return fn
    return authentication_provider_decorator


@authentication_provider(allow_logout=True)
def cookie():
    """Authenticate the user given a session cookie."""
    session_cookie = request.cookies.get(g.login_cookie)
    if session_cookie:
        session_cookie = unquote(session_cookie)
    else:
        return None

    try:
        uid, timestr, hash = session_cookie.split(",")
        uid = int(uid)
    except:
        return None

    try:
        account = Account._byID(uid, data=True)
    except NotFound:
        return None

    if not constant_time_compare(session_cookie, account.make_cookie(timestr)):
        return None
    return account


@authentication_provider(allow_logout=False)
def http_basic():
    """Authenticate the user based on their HTTP "Authorization" header."""
    import crypt

    try:
        authorization = request.environ.get("HTTP_AUTHORIZATION")
        username, password = parse_http_basic(authorization)
    except RequirementException:
        return None

    try:
        account = Account._by_name(username)
    except NotFound:
        return None

    # not all systems support bcrypt in the standard crypt
    if account.password.startswith("$2a$"):
        expected_hash = bcrypt.hashpw(password, account.password)
    else:
        expected_hash = crypt.crypt(password, account.password)

    if not constant_time_compare(expected_hash, account.password):
        return None
    return account


def _get_authenticator():
    """Return the configured authenticator."""
    return _AUTHENTICATION_PROVIDERS[g.authentication_provider]


def user_can_log_out():
    """Return if the configured authenticator allows users to log out."""
    authenticator = _get_authenticator()
    return authenticator.allow_logout


def authenticate_user():
    """Attempt to authenticate the user using the configured authenticator."""

    if not g.read_only_mode:
        authenticator = _get_authenticator()
        c.user = authenticator()

        if c.user and c.user._deleted:
            c.user = None
    else:
        c.user = None

    c.user_is_loggedin = bool(c.user)
