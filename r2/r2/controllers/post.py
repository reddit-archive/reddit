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

from r2.lib.pages import *
from reddit_base import cross_domain
from api import ApiController
from r2.lib.utils import Storage, query_string, UrlParser
from r2.lib.emailer import opt_in, opt_out
from r2.lib.validator import *
from pylons import request, c, g
from pylons.i18n import _
from r2.models import *
import hashlib

class PostController(ApiController):
    def set_options(self, all_langs, pref_lang, **kw):
        if c.errors.errors:
            print "fucker"
            return

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


    @validate(pref_lang = VLang('lang'),
              all_langs = VOneOf('all-langs', ('all', 'some'), default='all'))
    def POST_unlogged_options(self, all_langs, pref_lang):
        self.set_options( all_langs, pref_lang)
        return self.redirect(request.referer)

    @validate(VUser(),
              VModhash(),
              pref_frame = VBoolean('frame'),
              pref_clickgadget = VBoolean('clickgadget'),
              pref_organic = VBoolean('organic'),
              pref_newwindow = VBoolean('newwindow'),
              pref_public_votes = VBoolean('public_votes'),
              pref_hide_from_robots = VBoolean('hide_from_robots'),
              pref_hide_ups = VBoolean('hide_ups'),
              pref_hide_downs = VBoolean('hide_downs'),
              pref_over_18 = VBoolean('over_18'),
              pref_research = VBoolean('research'),
              pref_numsites = VInt('numsites', 1, 100),
              pref_lang = VLang('lang'),
              pref_media = VOneOf('media', ('on', 'off', 'subreddit')),
              pref_compress = VBoolean('compress'),
              pref_min_link_score = VInt('min_link_score', -100, 100),
              pref_min_comment_score = VInt('min_comment_score', -100, 100),
              pref_num_comments = VInt('num_comments', 1, g.max_comments,
                                       default = g.num_comments),
              pref_show_stylesheets = VBoolean('show_stylesheets'),
              pref_show_flair = VBoolean('show_flair'),
              pref_show_link_flair = VBoolean('show_link_flair'),
              pref_no_profanity = VBoolean('no_profanity'),
              pref_label_nsfw = VBoolean('label_nsfw'),
              pref_show_promote = VBoolean('show_promote'),
              pref_mark_messages_read = VBoolean("mark_messages_read"),
              pref_threaded_messages = VBoolean("threaded_messages"),
              pref_collapse_read_messages = VBoolean("collapse_read_messages"),
              pref_private_feeds = VBoolean("private_feeds"),
              pref_local_js = VBoolean('local_js'),
              pref_show_adbox = VBoolean("show_adbox"),
              pref_show_sponsors = VBoolean("show_sponsors"),
              pref_show_sponsorships = VBoolean("show_sponsorships"),
              pref_highlight_new_comments = VBoolean("highlight_new_comments"),
              pref_monitor_mentions=VBoolean("monitor_mentions"),
              all_langs = VOneOf('all-langs', ('all', 'some'), default='all'))
    def POST_options(self, all_langs, pref_lang, **kw):
        #temporary. eventually we'll change pref_clickgadget to an
        #integer preference
        kw['pref_clickgadget'] = kw['pref_clickgadget'] and 5 or 0
        if c.user.pref_show_promote is None:
            kw['pref_show_promote'] = None
        elif not kw.get('pref_show_promote'):
            kw['pref_show_promote'] = False

        if not kw.get("pref_over_18") or not c.user.pref_over_18:
            kw['pref_no_profanity'] = True

        if kw.get("pref_no_profanity") or c.user.pref_no_profanity:
            kw['pref_label_nsfw'] = True

        # default all the gold options to on if they don't have gold
        if not c.user.gold:
            for pref in ('pref_show_adbox',
                         'pref_show_sponsors',
                         'pref_show_sponsorships',
                         'pref_highlight_new_comments',
                         'pref_monitor_mentions'):
                kw[pref] = True

        self.set_options(all_langs, pref_lang, **kw)
        u = UrlParser(c.site.path + "prefs")
        u.update_query(done = 'true')
        if c.cname:
            u.put_in_frame()
        return self.redirect(u.unparse())

    def GET_over18(self):
        return BoringPage(_("over 18?"),
                          content = Over18()).render()

    @validate(VModhash(fatal=False),
              over18 = nop('over18'),
              dest = VDestination(default = '/'))
    def POST_over18(self, over18, dest):
        if over18 == 'yes':
            if c.user_is_loggedin and not c.errors:
                c.user.pref_over_18 = True
                c.user._commit()
            else:
                c.cookies.add("over18", "1")
            return self.redirect(dest)
        else:
            return self.redirect('/')


    @validate(msg_hash = nop('x'))
    def POST_optout(self, msg_hash):
        email, sent = opt_out(msg_hash)
        if not email:
            return self.abort404()
        return BoringPage(_("opt out"),
                          content = OptOut(email = email, leave = True,
                                           sent = True,
                                           msg_hash = msg_hash)).render()

    @validate(msg_hash = nop('x'))
    def POST_optin(self, msg_hash):
        email, sent = opt_in(msg_hash)
        if not email:
            return self.abort404()
        return BoringPage(_("welcome back"),
                          content = OptOut(email = email, leave = False,
                                           sent = True,
                                           msg_hash = msg_hash)).render()


    @validate(dest = VDestination(default = "/"))
    def POST_login(self, dest, *a, **kw):
        ApiController._handle_login(self, *a, **kw)
        c.render_style = "html"
        response.content_type = "text/html"

        if c.errors:
            return LoginPage(user_login = request.post.get('user'),
                             dest = dest).render()

        return self.redirect(dest)

    @validate(dest = VDestination(default = "/"))
    def POST_reg(self, dest, *a, **kw):
        ApiController._handle_register(self, *a, **kw)
        c.render_style = "html"
        response.content_type = "text/html"

        if c.errors:
            return LoginPage(user_reg = request.post.get('user'),
                             dest = dest).render()

        return self.redirect(dest)

    def GET_login(self, *a, **kw):
        return self.redirect('/login' + query_string(dict(dest="/")))

