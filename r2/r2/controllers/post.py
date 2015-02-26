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
from r2.lib.pages import *
from reddit_base import (
    hsts_eligible,
    hsts_modify_redirect,
    set_over18_cookie,
    delete_over18_cookie,
)
from api import ApiController
from r2.lib.errors import BadRequestError, errors
from r2.lib.utils import Storage, query_string, UrlParser
from r2.lib.emailer import opt_in, opt_out
from r2.lib.validator import *
from r2.lib.validator.preferences import (
    filter_prefs,
    PREFS_VALIDATORS,
    set_prefs,
)
from r2.lib.csrf import csrf_exempt
from r2.models.recommend import ExploreSettings
from pylons import request, c, g
from pylons.controllers.util import redirect_to
from pylons.i18n import _
from r2.models import *
import hashlib
from r2.lib.base import abort

class PostController(ApiController):
    @csrf_exempt
    @validate(pref_lang = VLang('lang'),
              all_langs = VOneOf('all-langs', ('all', 'some'), default='all'))
    def POST_unlogged_options(self, all_langs, pref_lang):
        prefs = {"pref_lang": pref_lang}
        set_prefs(c.user, prefs)
        c.user._commit()
        return self.redirect(request.referer)

    @validate(VUser(), VModhash(),
              all_langs=VOneOf('all-langs', ('all', 'some'), default='all'),
              **PREFS_VALIDATORS)
    def POST_options(self, all_langs, **prefs):
        u = UrlParser(c.site.path + "prefs")

        filter_prefs(prefs, c.user)
        if c.errors.errors:
            for error in c.errors.errors:
                if error[1] == 'stylesheet_override':
                    u.update_query(error_style_override=error[0])
                else:
                    u.update_query(generic_error=error[0])
            return self.redirect(u.unparse())

        set_prefs(c.user, prefs)
        c.user._commit()
        u.update_query(done='true')
        if c.cname:
            u.put_in_frame()
        return self.redirect(u.unparse())

    def GET_over18(self):
        return BoringPage(_("over 18?"), content=Over18(),
                          show_sidebar=False).render()

    @validate(VModhash(fatal=False),
              over18 = nop('over18'),
              dest = VDestination(default = '/'))
    def POST_over18(self, over18, dest):
        if over18 == 'yes':
            if c.user_is_loggedin and not c.errors:
                c.user.pref_over_18 = True
                c.user._commit()
            else:
                set_over18_cookie()
            return self.redirect(dest)
        else:
            if c.user_is_loggedin and not c.errors:
                c.user.pref_over_18 = False
                c.user._commit()
            else:
                delete_over18_cookie()
            return self.redirect('/')

    @csrf_exempt
    @validate(msg_hash = nop('x'))
    def POST_optout(self, msg_hash):
        email, sent = opt_out(msg_hash)
        if not email:
            return self.abort404()
        return BoringPage(_("opt out"),
                          content = OptOut(email = email, leave = True,
                                           sent = True,
                                           msg_hash = msg_hash)).render()

    @csrf_exempt
    @validate(msg_hash = nop('x'))
    def POST_optin(self, msg_hash):
        email, sent = opt_in(msg_hash)
        if not email:
            return self.abort404()
        return BoringPage(_("welcome back"),
                          content = OptOut(email = email, leave = False,
                                           sent = True,
                                           msg_hash = msg_hash)).render()


    @csrf_exempt
    @validate(dest = VDestination(default = "/"))
    def POST_login(self, dest, *a, **kw):
        ApiController._handle_login(self, *a, **kw)
        c.render_style = "html"
        response.content_type = "text/html"

        if c.errors:
            return LoginPage(user_login = request.POST.get('user'),
                             dest = dest).render()

        return self.hsts_redirect(dest)

    @csrf_exempt
    @validate(dest = VDestination(default = "/"))
    def POST_reg(self, dest, *a, **kw):
        ApiController._handle_register(self, *a, **kw)
        c.render_style = "html"
        response.content_type = "text/html"

        if c.errors:
            return LoginPage(user_reg = request.POST.get('user'),
                             dest = dest).render()

        return self.hsts_redirect(dest)

    def GET_login(self, *a, **kw):
        return self.redirect('/login' + query_string(dict(dest="/")))

    @validatedForm(
        VUser(),
        VModhash(),
        personalized=VBoolean('pers', default=False),
        discovery=VBoolean('disc', default=False),
        rising=VBoolean('ris', default=False),
        nsfw=VBoolean('nsfw', default=False),
    )
    def POST_explore_settings(self,
                              form,
                              jquery,
                              personalized,
                              discovery,
                              rising,
                              nsfw):
        ExploreSettings.record_settings(
            c.user,
            personalized=personalized,
            discovery=discovery,
            rising=rising,
            nsfw=nsfw,
        )
        return redirect_to(controller='front', action='explore')
