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
# All portions of the code written by reddit are Copyright (c) 2006-2015 reddit
# Inc. All Rights Reserved.
###############################################################################
"""Module for request (and eventually cookie) signing.

"""
import hmac
import hashlib
import re
import pytz

from datetime import datetime
from collections import namedtuple
from pylons import app_globals as g

from r2.lib.utils import Storage, epoch_timestamp, constant_time_compare

GLOBAL_TOKEN_VERSION = 1
SIGNATURE_UA_HEADER = "X-hmac-signed-result"
SIGNATURE_BODY_HEADER = "X-hmac-signed-body"

SIG_HEADER_RE = re.compile(r"^(?P<global_version>\d+?):(?P<payload>.*)$")
SIG_CONTENT_V1_RE = re.compile(
    r"^(?P<platform>.+?):(?P<version>\d+?):(?P<epoch>\d+?):(?P<mac>.*)$"
)

ERRORS = Storage()
SignatureError = namedtuple("SignatureError", "code msg")
for code, msg in (
    ("UNKNOWN", "default signature failure mode (shouldn't happen!)"),
    ("INVALID_FORMAT", "no signature header or completely unparsable"),
    ("UNKOWN_GLOBAL_VERSION", "token global version is from the future"),
    ("UNPARSEABLE", "couldn't parse signature for this global version"),
    ("INVALIDATED_TOKEN", "platform/version combination is invalid."),
    ("EXPIRED_TOKEN", "epoch provided is too old."),
    ("SIGNATURE_MISMATCH", "the payload's signature doesn't match the header"),
):
    code = code.upper()
    ERRORS[code] = SignatureError(code, msg)


def current_epoch():
    return int(epoch_timestamp(datetime.now(pytz.UTC)))


def valid_epoch(platform, epoch, max_age=5 * 60):
    now = current_epoch()
    dt = abs(now - epoch)
    g.stats.simple_timing("signing.%s.skew" % platform, dt * 1000)
    return dt < max_age


def epoch_wrap(epoch, payload):
    return "Epoch:{}|{}".format(epoch, payload)


def versioned_hmac(secret, body, global_version=GLOBAL_TOKEN_VERSION):
    """Provide an hex hmac for the provided global_version.

    This provides future compatibility if we want to bump the token version
    and change our hashing algorithm.
    """
    # If we want to change the hashing algo or anything else about this hmac,
    # this is the place to make that change based on global_version.
    assert global_version <= GLOBAL_TOKEN_VERSION, (
        "Invalid version signing version '%s'!" % global_version
    )
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def get_secret_token(platform, version, global_version=GLOBAL_TOKEN_VERSION):
    """For a given platform and version, provide the signing token.

    The signing token for a given platform ("ios", "android", etc.) and version
    is derived by hashing the platform and versions with a server secret. This
    ensures that we can issue new tokens to new clients as need be without
    needing to keep them in a database.  It also means we can invalidate
    old versions of tokens in `is_invalid_token` and trust that the client
    isn't lying to us.
    """
    token_identifier = "{global_version}:{platform}:{version}".format(
        global_version=global_version,
        platform=platform,
        version=version,
    )
    # NOTE: this is the only place in this file where we reference g.secrets.
    # If we wanted to rotate the global secret, this is the place to do it.
    global_secret = g.secrets["request_signature_secret"]
    return versioned_hmac(global_secret, token_identifier, global_version)


def is_invalid_token(platform, version):
    """Conditionally reject a token based on platform and version."""
    return False


def valid_post_signature(request, signature_header=SIGNATURE_BODY_HEADER):
    "Validate that the request has a properly signed body."
    return valid_signature(
        "Body:{}".format(request.body),
        request.headers.get(signature_header)
    )


def valid_ua_signature(
    request,
    signed_headers=("User-Agent", "Client-Vendor-ID"),
    signature_header=SIGNATURE_UA_HEADER,
):
    "Validate that the request has a properly signed user-agent."
    payload = "|".join(
        "{}:{}".format(h, request.headers.get(h) or "")
        for h in signed_headers
    )
    return valid_signature(payload, request.headers.get(signature_header))


def valid_signature(payload, signature):
    """Checks if `signature` matches `payload`.

    `Signature` (at least as of version 1) be of the form:

       {global_version}:{platform}:{version}:{signature}

    where:

      * global_version (currently hard-coded to be "1") can be used to change
            this header's underlying schema later if needs be.  As such, can
            be treated as a protocol version.
      * platform is the client platform type (generally "ios" or "android")
      * version is the client's token version (can be updated and incremented
            per app build as needs be.
      * signature is the hmac of the request's POST body with the token derived
            from the above three parameters via `get_secret_token`
    """
    result = Storage(
        global_version=-1,
        platform=None,
        version=-1,
        mac=None,
        valid=False,
        epoch=None,
        error=ERRORS.UNKNOWN,
    )

    sig_match = SIG_HEADER_RE.match(signature or "")
    if not sig_match:
        result.error = ERRORS.INVALID_FORMAT
        return result

    sig_header_dict = sig_match.groupdict()
    # we're matching \d so this shouldn't throw a TypeError
    result.global_version = int(sig_header_dict['global_version'])
    # incrementing this value is drastic.  We can't validate a token protocol
    # we don't understand.
    if result.global_version > GLOBAL_TOKEN_VERSION:
        result.error = ERRORS.UNKOWN_GLOBAL_VERSION
        return result

    # currently there's only one version, but here's where we'll eventually
    # patch in more.
    sig_match = SIG_CONTENT_V1_RE.match(sig_header_dict['payload'])
    if not sig_match:
        result.error = ERRORS.UNPARSEABLE
        return result

    result.update(sig_match.groupdict())
    result.version = int(result.version)
    result.epoch = int(result.epoch)

    # verify that the token provided hasn't been invalidated
    if is_invalid_token(result.platform, result.version):
        result.error = ERRORS.INVALIDATED_TOKEN
        return result

    if not valid_epoch(result.platform, result.epoch):
        result.error = ERRORS.EXPIRED_TOKEN
        return result

    # get the expected secret used to verify this request.
    secret_token = get_secret_token(
        result.platform,
        result.version,
        global_version=result.global_version,
    )
    result.valid = constant_time_compare(
        result.mac,
        versioned_hmac(
            secret_token,
            epoch_wrap(result.epoch, payload),
            result.global_version
        ),
    )
    if result.valid:
        result.error = None
    else:
        result.error = ERRORS.SIGNATURE_MISMATCH

    return result


def sign_v1_message(body, platform, version, epoch=None):
    """Reference implementation of the v1 mobile body signing."""
    token = get_secret_token(platform, version, global_version=1)
    epoch = epoch or current_epoch()
    payload = epoch_wrap(epoch, body)
    signature = versioned_hmac(token, payload, global_version=1)
    return "{global_version}:{platform}:{version}:{epoch}:{signature}".format(
        global_version=1,
        platform=platform,
        version=version,
        epoch=epoch,
        signature=signature,
    )
