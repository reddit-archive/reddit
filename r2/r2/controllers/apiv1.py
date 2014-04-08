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
import json

from pylons import c
from r2.controllers.api_docs import api_doc, api_section
from r2.controllers.oauth2 import require_oauth2_scope
from r2.controllers.reddit_base import (
    abort_with_error,
    OAuth2ResourceController,
)
from r2.lib.base import abort
from r2.lib.jsontemplates import (
    IdentityJsonTemplate,
    PrefsJsonTemplate,
    TrophyListJsonTemplate,
    KarmaListJsonTemplate,
)
from r2.lib.validator import (
    validate,
    VAccountByName,
    VContentLang,
    VList,
    VValidatedJSON,
)
from r2.models import Account, Trophy
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
        self.authenticate_with_token()
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
    @validate(
        fields=VList(
            "fields",
            choices=PREFS_JSON_SPEC.spec.keys(),
            error=errors.errors.NON_PREFERENCE,
        ),
    )
    @api_doc(api_section.account, uri='/api/v1/me/prefs')
    def GET_prefs(self, fields):
        """Return the preference settings of the logged in user"""
        resp = PrefsJsonTemplate(fields).data(c.oauth_user)
        return self.api_wrapper(resp)

    def _get_usertrophies(self, user):
        trophies = Trophy.by_account(user)
        def visible_trophy(trophy):
            return trophy._thing2.awardtype != 'invisible'
        trophies = filter(visible_trophy, trophies)
        resp = TrophyListJsonTemplate().render(trophies)
        return self.api_wrapper(resp.finalize())

    @require_oauth2_scope("read")
    @validate(
        user=VAccountByName('username'),
    )
    @api_doc(
        section=api_section.users,
        uri='/api/v1/user/{username}/trophies',
    )
    def GET_usertrophies(self, user):
        """Return a list of trophies for the a given user."""
        return self._get_usertrophies(user)

    @require_oauth2_scope("identity")
    @api_doc(
        section=api_section.account,
        uri='/api/v1/me/trophies',
    )
    def GET_trophies(self):
        """Return a list of trophies for the current user."""
        return self._get_usertrophies(c.oauth_user)

    @require_oauth2_scope("mysubreddits")
    @api_doc(
        section=api_section.account,
        uri='/api/v1/me/karma',
    )
    def GET_karma(self):
        """Return a breakdown of subreddit karma."""
        karmas = c.oauth_user.all_karmas(include_old=False)
        resp = KarmaListJsonTemplate().render(karmas)
        return self.api_wrapper(resp.finalize())

    PREFS_JSON_VALIDATOR = VValidatedJSON("json", PREFS_JSON_SPEC,
                                          body=True)

    @require_oauth2_scope("account")
    @validate(validated_prefs=PREFS_JSON_VALIDATOR)
    @api_doc(api_section.account, json_model=PREFS_JSON_VALIDATOR,
             uri='/api/v1/me/prefs')
    def PATCH_prefs(self, validated_prefs):
        user_prefs = c.user.preferences()
        for short_name, new_value in validated_prefs.iteritems():
            pref_name = "pref_" + short_name
            if pref_name == "pref_content_langs":
                new_value = vprefs.format_content_lang_pref(new_value)
            user_prefs[pref_name] = new_value
        vprefs.filter_prefs(user_prefs, c.user)
        vprefs.set_prefs(c.user, user_prefs)
        c.user._commit()
        return self.api_wrapper(PrefsJsonTemplate().data(c.user))
