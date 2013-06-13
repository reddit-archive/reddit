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

from pylons import c, request, response

from r2.config.extensions import set_extension
from r2.controllers.api_docs import api_doc, api_section
from r2.controllers.reddit_base import RedditController
from r2.controllers.oauth2 import (
    OAuth2ResourceController,
    require_oauth2_scope,
)
from r2.models.subreddit import (
    FakeSubreddit,
    Subreddit,
    LabeledMulti,
    TooManySubredditsError,
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
from r2.lib.jsontemplates import LabeledMultiJsonTemplate
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

    def _format_multi(self, multi):
        resp = wrap_things(multi)[0].render()
        return self.api_wrapper(resp)

    @require_oauth2_scope("read")
    @api_doc(
        api_section.multis,
        uri="/api/multi/{multipath}",
    )
    @validate(multi=VMultiByPath("multipath", require_view=True))
    def GET_multi(self, multi):
        """Fetch a multi's data and subreddit list by name."""
        return self._format_multi(multi)

    def _check_new_multi_path(self, path_info):
        if path_info['username'].lower() != c.user.name.lower():
            raise RedditError('MULTI_CANNOT_EDIT', code=403,
                              fields='multipath')

    def _write_multi_data(self, multi, data):
        if 'visibility' in data:
            if data['visibility'] not in ('private', 'public'):
                raise RedditError('INVALID_OPTION', code=400, fields="data")
            multi.visibility = data['visibility']

        if 'subreddits' in data:
            multi.clear_srs()
            srs = Subreddit._by_name(sr['name'] for sr in data['subreddits'])

            for sr in srs.itervalues():
                if isinstance(sr, FakeSubreddit):
                    multi._revert()
                    raise RedditError('MULTI_SPECIAL_SUBREDDIT',
                                      msg_params={'path': sr.path},
                                      code=400)

            sr_props = {}
            for sr_data in data['subreddits']:
                try:
                    sr = srs[sr_data['name']]
                except KeyError:
                    raise RedditError('SUBREDDIT_NOEXIST', code=400)
                else:
                    sr_props[sr] = sr_data

            try:
                multi.add_srs(sr_props)
            except TooManySubredditsError as e:
                multi._revert()
                raise RedditError('MULTI_TOO_MANY_SUBREDDITS', code=409)

        multi._commit()
        return multi

    @require_oauth2_scope("subscribe")
    @api_doc(api_section.multis, extends=GET_multi)
    @validate(
        VUser(),
        VModhash(),
        path_info=VMultiPath("multipath"),
        data=VJSON("model"),
    )
    def POST_multi(self, path_info, data):
        """Create a multi. Responds with 409 Conflict if it already exists."""

        self._check_new_multi_path(path_info)

        try:
            LabeledMulti._byID(path_info['path'])
        except tdb_cassandra.NotFound:
            multi = LabeledMulti.create(path_info['path'], c.user)
            response.status = 201
        else:
            raise RedditError('MULTI_EXISTS', code=409, fields='multipath')

        self._write_multi_data(multi, data)
        return self._format_multi(multi)

    @require_oauth2_scope("subscribe")
    @api_doc(api_section.multis, extends=GET_multi)
    @validate(
        VUser(),
        VModhash(),
        path_info=VMultiPath("multipath"),
        data=VJSON("model"),
    )
    def PUT_multi(self, path_info, data):
        """Create or update a multi."""

        self._check_new_multi_path(path_info)

        try:
            multi = LabeledMulti._byID(path_info['path'])
        except tdb_cassandra.NotFound:
            multi = LabeledMulti.create(path_info['path'], c.user)
            response.status = 201

        self._write_multi_data(multi, data)
        return self._format_multi(multi)

    @require_oauth2_scope("subscribe")
    @api_doc(api_section.multis, extends=GET_multi)
    @validate(
        VUser(),
        VModhash(),
        multi=VMultiByPath("multipath", require_edit=True),
    )
    def DELETE_multi(self, multi):
        """Delete a multi."""
        multi.delete()

    @require_oauth2_scope("subscribe")
    @api_doc(
        api_section.multis,
        uri="/api/multi/{multipath}/rename",
    )
    @validate(
        VUser(),
        VModhash(),
        from_multi=VMultiByPath("multipath", require_edit=True),
        to_path_info=VMultiPath("to",
            docs={"to": "destination multireddit url path"},
        ),
    )
    def POST_multi_rename(self, multi, to_path_info):
        """Rename a multi."""

        self._check_new_multi_path(to_path_info)

        try:
            LabeledMulti._byID(to_path_info['path'])
        except tdb_cassandra.NotFound:
            to_multi = LabeledMulti.copy(to_path_info['path'], multi)
        else:
            raise RedditError('MULTI_EXISTS', code=409, fields='multipath')

        multi.delete()
        return self._format_multi(to_multi)

    def _get_multi_subreddit(self, multi, sr):
        resp = LabeledMultiJsonTemplate.sr_props(multi, [sr])[0]
        return self.api_wrapper(resp)

    @require_oauth2_scope("read")
    @api_doc(
        api_section.multis,
        uri="/api/multi/{multipath}/r/{srname}",
    )
    @validate(
        VUser(),
        multi=VMultiByPath("multipath", require_view=True),
        sr=VSRByName('srname'),
    )
    def GET_multi_subreddit(self, multi, sr):
        """Get data about a subreddit in a multi."""
        return self._get_multi_subreddit(multi, sr)

    @require_oauth2_scope("subscribe")
    @api_doc(api_section.multis, extends=GET_multi_subreddit)
    @validate(
        VUser(),
        VModhash(),
        multi=VMultiByPath("multipath", require_edit=True),
        sr=VSRByName('srname'),
    )
    def PUT_multi_subreddit(self, multi, sr):
        """Add a subreddit to a multi."""

        if isinstance(sr, FakeSubreddit):
            raise RedditError('MULTI_SPECIAL_SUBREDDIT',
                              msg_params={'path': sr.path},
                              code=400)

        new = sr not in multi._srs

        try:
            multi.add_srs({sr: {}})
        except TooManySubredditsError as e:
            raise RedditError('MULTI_TOO_MANY_SUBREDDITS', code=409)
        else:
            multi._commit()

        if new:
            response.status = 201

        return self._get_multi_subreddit(multi, sr)

    @require_oauth2_scope("subscribe")
    @api_doc(api_section.multis, extends=GET_multi_subreddit)
    @validate(
        VUser(),
        VModhash(),
        multi=VMultiByPath("multipath", require_edit=True),
        sr=VSRByName('srname'),
    )
    def DELETE_multi_subreddit(self, multi, sr):
        """Remove a subreddit from a multi."""
        multi.del_srs(sr)
        multi._commit()
