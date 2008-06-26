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
# All portions of the code written by CondeNet are Copyright (c) 2006-2008
# CondeNet, Inc. All Rights Reserved.
################################################################################
from r2.lib.pages import *
from api import ApiController
from r2.lib.utils import Storage, query_string
from pylons import request, c, g
from validator import *
from pylons.i18n import _
import sha

def to_referer(func, **params):
    def _to_referer(self, *a, **kw):
        res = func(self, *a, **kw)
        dest = res.get('redirect') or request.referer or '/'
        return self.redirect(dest + query_string(params))        
    return _to_referer


class PostController(ApiController):
    def response_func(self, **kw):
        return Storage(**kw)

#TODO: feature disabled for now
#     @to_referer
#     @validate(VUser(),
#               key = VOneOf('key', ('pref_bio','pref_location',
#                                    'pref_url')),
#               value = nop('value'))
#     def POST_user_desc(self, key, value):
#         setattr(c.user, key, value)
#         c.user._commit()
#         return {}

    @validate(pref_frame = VBoolean('frame'),
              pref_organic = VBoolean('organic'),
              pref_newwindow = VBoolean('newwindow'),
              pref_public_votes = VBoolean('public_votes'),
              pref_hide_ups = VBoolean('hide_ups'),
              pref_hide_downs = VBoolean('hide_downs'),
              pref_over_18 = VBoolean('over_18'),
              pref_numsites = VInt('numsites', 1, 100),
              pref_lang = VLang('lang'),
              pref_compress = VBoolean('compress'),
              pref_min_link_score = VInt('min_link_score', -100, 100),
              pref_min_comment_score = VInt('min_comment_score', -100, 100),
              pref_num_comments = VInt('num_comments', 1, g.max_comments,
                                       default = g.num_comments),
              all_langs = nop('all-langs', default = 'all'))
    def POST_options(self, all_langs, pref_lang, **kw):
        #TODO
        if c.errors.errors:
            print "fucker"
            raise "broken"

        if all_langs == 'all':
            langs = 'all'
        elif all_langs == 'some':
            langs = []
            for lang in g.all_languages:
                if request.post.get('lang-' + lang):
                    langs.append(str(lang)) #unicode
            if langs:
                langs.sort()
                langs = tuple(langs)
            else:
                langs = 'all'

        for k, v in kw.iteritems():
            #startswith is important because kw has all sorts of
            #request info in it
            if k.startswith('pref_'):
                setattr(c.user, k, v)

        c.user.pref_content_langs = langs
        c.user.pref_lang = pref_lang
        c.user._commit()

        if c.user_is_loggedin: 
            return self.redirect("/prefs?done=true")
        return self.redirect(request.referer)        
            
    def GET_over18(self):
        return BoringPage(_("over 18?"),
                          content = Over18()).render()

    @validate(over18 = nop('over18'),
              uh = nop('uh'),
              dest = nop('dest'))
    def POST_over18(self, over18, uh, dest):
        if over18 == 'yes':
            if c.user_is_loggedin and c.user.valid_hash(uh):
                c.user.pref_over_18 = True
                c.user._commit()
            else:
                ip_hash = sha.new(request.ip).hexdigest()
                c.response.set_cookie('over18',
                                      value = ip_hash,
                                      domain = c.domain)
            return self.redirect(dest)
        else:
            return self.redirect('/')
