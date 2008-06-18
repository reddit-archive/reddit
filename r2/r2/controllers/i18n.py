# "The contents of this file are subject to the Common Public Attribution
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
from pylons import request, g
from reddit_base import RedditController
from api import Json
from r2.lib.pages import UnfoundPage, AdminTranslations, AdminPage

from r2.lib.translation import Translator, TranslatorTemplate, get_translator
from validator import *
from gettext import _translations

from r2.lib.wrapped import Wrapped

class VTranslator(Validator):
    def run(self, lang):
        if (not c.user_is_admin and
            (not c.user_is_loggedin or not lang or
             c.user.name not in Translator.get_author(lang))):
            abort(404, 'page not found')

class VTranslationEnabled(Validator):
    def run(self):
        if not g.translator:
            abort(403, 'forbidden')
            

class I18nController(RedditController):

    @validate(VTranslationEnabled(),
              VAdmin(),
              lang = nop('lang'),
              a = VExistingUname('name'))
    def POST_adduser(self, lang, a):
        if a and Translator.exists(lang):
            tr = get_translator(locale = lang)
            tr.author.add(a.name)
            tr.save()
        return self.redirect("/admin/i18n")


    @validate(VTranslationEnabled(),
              VAdmin())
    def GET_list(self):
        res = AdminPage(content = AdminTranslations(),
                        title = 'translate reddit').render()
        return res


    @validate(VTranslationEnabled(),
              VAdmin(),
              lang = nop('name'))
    def POST_new(self, lang):
        if lang and not Translator.exists(lang):
            tr = get_translator(locale = lang)
            tr.save()
        return self.redirect("/admin/i18n")
        

    @validate(VTranslationEnabled(),
              VTranslator('lang'),
              lang = nop('lang'))
    def GET_edit(self, lang):
        if not lang and c.user_is_admin:
            content = Wrapped(TranslatorTemplate())
        elif Translator.exists(lang):
            content = Wrapped(get_translator(locale = lang))
        else:
            content = UnfoundPage()
        res = AdminPage(content = content, 
                        title = 'translate reddit').render()
        return res

    @validate(VTranslationEnabled(),
              VTranslator('lang'),
              lang = nop('lang'))
    def GET_try(self, lang):
        if lang:
            tr = get_translator(locale = lang)
            tr.save(compile=True)

            tran_keys = _translations.keys()
            for key in tran_keys:
                if key.endswith(tr._out_file('mo')):
                    del _translations[key]

            return self.redirect("http://%s.%s/" %
                                 (lang, c.domain))
        return abort(404, 'page not found')

    @validate(VTranslationEnabled(),
              VTranslator('lang'),
              post = nop('post'),
              try_trans = nop('try'),
              lang = nop('lang'))
    def POST_edit(self, lang, post, try_trans):
        if (lang and not Translator.exists(lang)):
            return self.redirect('/admin/i18n')

        if lang:
            tr = get_translator(locale = lang)
        else:
            tr = TranslatorTemplate()

        enabled = set()
        for k, val in request.post.iteritems():
            if k.startswith('trans_'):
                k = k.split('_')
                # check if this is a translation string
                if k[1:] and tr.get(k[1]):
                    tr.set(k[1], val, indx = int(k[2] if k[2:] else -1))
                # check if this is an admin editing the source/comment lines
                elif c.user_is_admin and tr.sources.get(k[1]):
                    source = tr.sources.get(k[1])
                    tr.source_trans[source] = val
            elif c.user_is_admin and k.startswith('enabled_'):
                k = k.split('_')
                enabled.add(k[1])

        # update the enabled state of the buttons
        if c.user_is_admin and enabled:
            strings = set(tr.string_dict.keys())
            disabled = strings - enabled
            for s in strings:
                tr.set_enabled(s, True)
            for s in disabled:
                tr.set_enabled(s, False)

        if request.post.get('nplurals'):
            try:
                tr.plural_names = [request.post.get('pluralform_%d' % i) \
                                   for i in xrange(tr.nplurals)]
                tr.nplurals = int(request.post.get('nplurals'))
            except ValueError:
                pass
        if request.post.get('langname'):
            tr.name = request.post['langname']
        if request.post.get('enlangname'):
            tr.en_name = request.post['enlangname']
            
        tr.save(compile=bool(try_trans))
        
        if try_trans:
            tran_keys = _translations.keys()
            for key in tran_keys:
                if key.endswith(tr._out_file('mo')):
                     del _translations[key]

            return self.redirect("http://%s/?lang=%s" %
                                 (c.domain, lang))
        
        whereto = request.post.get('bttn_num', '')
        if whereto:
            whereto = 'bttn_num_%s' % whereto
        return self.redirect("/admin/i18n/edit/%s#%s" % (lang or '', whereto))
        return res
        
