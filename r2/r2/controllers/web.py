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

import hashlib
import hmac

from pylons import g, c, request
from pylons.i18n import _

from r2.controllers.reddit_base import RedditController, abort_with_error
from r2.lib.base import abort
from r2.lib.csrf import csrf_exempt
from r2.lib.utils import constant_time_compare
from r2.lib.validator import (
    validate,
    VFloat,
    VOneOf,
    VPrintable,
    VRatelimit,
    VValidatedJSON,
)


class WebLogController(RedditController):
    on_validation_error = staticmethod(abort_with_error)

    @csrf_exempt
    @validate(
        VRatelimit(rate_user=False, rate_ip=True, prefix='rate_weblog_'),
        level=VOneOf('level', ('error',)),
        logs=VValidatedJSON('logs',
            VValidatedJSON.ArrayOf(VValidatedJSON.PartialObject({
                'msg': VPrintable('msg', max_length=256),
                'url': VPrintable('url', max_length=256),
                'tag': VPrintable('tag', max_length=32),
            }))
        ),
    )
    def POST_message(self, level, logs):
        # Whitelist tags to keep the frontend from creating too many keys in statsd
        valid_frontend_log_tags = {
            'unknown',
            'jquery-migrate-bad-html',
        }

        # prevent simple CSRF by requiring a custom header
        if not request.headers.get('X-Loggit'):
            abort(403)

        uid = c.user._id if c.user_is_loggedin else '-'

        # only accept a maximum of 3 entries per request
        for log in logs[:3]:
            if 'msg' not in log or 'url' not in log:
                continue

            tag = 'unknown'

            if log.get('tag') in valid_frontend_log_tags:
                tag = log['tag']

            g.stats.simple_event('frontend.error.' + tag)

            g.log.warning('[web frontend] %s: %s | U: %s FP: %s UA: %s',
                          level, log['msg'], uid, log['url'],
                          request.user_agent)

        VRatelimit.ratelimit(rate_user=False, rate_ip=True,
                             prefix="rate_weblog_", seconds=10)

