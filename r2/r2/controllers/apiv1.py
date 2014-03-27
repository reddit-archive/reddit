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

from pylons import c
from r2.controllers.api_docs import api_doc, api_section
from r2.controllers.oauth2 import require_oauth2_scope
from r2.controllers.reddit_base import OAuth2ResourceController
from r2.lib.jsontemplates import IdentityJsonTemplate, PrefsJsonTemplate
from r2.lib.validator import (
    nop,
    validate,
    VContentLang,
    VList,
    VValidatedJSON,
)
from r2.models import Account
import r2.lib.errors as errors
import r2.lib.validator.preferences as vprefs


PREFS_JSON_SPEC = VValidatedJSON.PartialObject({
    k[len("pref_"):]: v for k, v in
    vprefs.PREFS_VALIDATORS.iteritems()
    if k in Account._preference_attrs
})

PREFS_JSON_SPEC.spec["content_langs"] = VValidatedJSON.ArrayOf(
        VContentLang("content_langs")
)


class APIv1Controller(OAuth2ResourceController):
    def pre(self):
        OAuth2ResourceController.pre(self)
        self.check_for_bearer_token()
        self.run_sitewide_ratelimits()

    def try_pagecache(self):
        pass

    @staticmethod
    def on_validation_error(error):
        abort_with_error(error, error.code or 400)

    @require_oauth2_scope("identity")
    @api_doc(api_section.account)
    def GET_me(self):
        """Returns the identity of the user currently authenticated via OAuth."""
        resp = IdentityJsonTemplate().data(c.oauth_user)
        return self.api_wrapper(resp)

    @require_oauth2_scope("identity")
    @api_doc(api_section.account)
    @validate(
        fields=VList(
            "fields",
            choices=PREFS_JSON_SPEC.spec.keys(),
            error=errors.errors.NON_PREFERENCE,
        ),
    )
    def GET_prefs(self, fields):
        """Return the preference settings of the logged in user"""
        resp = PrefsJsonTemplate(fields).data(c.oauth_user)
        return self.api_wrapper(resp)
