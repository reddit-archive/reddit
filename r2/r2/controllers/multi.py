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

from pylons import c, request

from r2.config.extensions import set_extension
from r2.controllers.api_docs import api_doc, api_section
from r2.controllers.reddit_base import RedditController
from r2.controllers.oauth2 import (
    OAuth2ResourceController,
    require_oauth2_scope,
)
from r2.models.subreddit import (
    Subreddit,
    LabeledMulti,
    TooManySubredditsException,
)
from r2.lib.db import tdb_cassandra
from r2.lib.wrapped import Wrapped
from r2.lib.validator import (
    validate,
    VUser,
    VModhash,
    VSRByName,
    VJSON,
    VMultiPath,
    VMultiByPath,
)
from r2.lib.pages.things import wrap_things
from r2.lib.errors import errors, reddit_http_error, RedditError
from r2.lib.base import abort


class MultiApiController(RedditController, OAuth2ResourceController):
    def pre(self):
        set_extension(request.environ, "json")
        self.check_for_bearer_token()
        RedditController.pre(self)

    def on_validation_error(self, error):
        if not error.code:
            return

        abort(reddit_http_error(
            code=error.code,
            error_name=error.name,
            explanation=error.message,
            fields=error.fields,
        ))

    @require_oauth2_scope("read")
    @api_doc(api_section.multis)
    @validate(VUser())
    def GET_my_multis(self):
        """Fetch a list of multis belonging to the current user."""
        multis = LabeledMulti.by_owner(c.user)
        wrapped = wrap_things(*multis)
        resp = [w.render() for w in wrapped]
        return self.api_wrapper(resp)

    @require_oauth2_scope("read")
    @api_doc(
        api_section.multis,
        uri="/api/multi/{multipath}",
    )
    @validate(multi=VMultiByPath("path", require_view=True))
    def GET_multi(self, multi):
        """Fetch a multi's data and subreddit list by name."""
        resp = wrap_things(multi)[0].render()
        return self.api_wrapper(resp)

    @require_oauth2_scope("subscribe")
    @api_doc(api_section.multis, extends=GET_multi)
    @validate(
        VUser(),
        VModhash(),
        info=VMultiPath("path"),
        data=VJSON("model"),
    )
    def PUT_multi(self, info, data):
        """Create or update a multi."""
        if info['username'].lower() != c.user.name.lower():
            raise RedditError('BAD_MULTI_NAME', code=400, fields="path")

        try:
            multi = LabeledMulti._byID(info['path'])
        except tdb_cassandra.NotFound:
            multi = LabeledMulti.create(info['path'], c.user)

        if 'visibility' in data:
            if data['visibility'] not in ('private', 'public'):
                raise RedditError('INVALID_OPTION', code=400, fields="data")
            multi.visibility = data['visibility']
            multi._commit()

        return self.GET_multi(path=info['path'])

    @require_oauth2_scope("subscribe")
    @api_doc(api_section.multis, extends=GET_multi)
    @validate(
        VUser(),
        VModhash(),
        multi=VMultiByPath("path", require_edit=True),
    )
    def DELETE_multi(self, multi):
        """Delete a multi."""
        multi.delete()

    @require_oauth2_scope("subscribe")
    @api_doc(
        api_section.multis,
        uri="/api/multi/{multipath}/r/{srname}",
    )
    @validate(
        VUser(),
        VModhash(),
        multi=VMultiByPath("path", require_edit=True),
        sr=VSRByName('sr_name'),
    )
    def PUT_multi_subreddit(self, multi, sr):
        """Add a subreddit to a multi."""

        try:
            multi.add_srs({sr: {}})
        except TooManySubredditsException as e:
            raise RedditError('MULTI_TOO_MANY_SUBREDDITS', code=409)
        else:
            multi._commit()

    @require_oauth2_scope("subscribe")
    @api_doc(api_section.multis, extends=PUT_multi_subreddit)
    @validate(
        VUser(),
        VModhash(),
        multi=VMultiByPath("path", require_edit=True),
        sr=VSRByName('sr_name'),
    )
    def DELETE_multi_subreddit(self, multi, sr):
        """Remove a subreddit from a multi."""
        multi.del_srs(sr)
        multi._commit()
