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
import r2.lib.helpers as h
from pylons import c, g, request
from pylons.controllers.util import abort, redirect_to
from pylons.i18n import _
from pylons.i18n.translation import LanguageError
from r2.lib.base import BaseController, proxyurl
from r2.lib import pages, utils, filters
from r2.lib.cache import LocalCache
import random as rand
from r2.models.account import valid_cookie, FakeAccount
from r2.models.subreddit import Subreddit
import r2.config as config
from r2.models import *
from errors import ErrorSet
from validator import *
from r2.lib.template_helpers import reddit_link
from r2.lib.jsontemplates import api_type

from copy import copy
import sha, inspect, simplejson

from r2.lib.tracking import encrypt, decrypt

NEVER = 'Thu, 31 Dec 2037 23:59:59 GMT'

class UnloggedUser(FakeAccount):
    _cookie = 'options'
    allowed_prefs = ('pref_content_langs', 'pref_lang')

    def __init__(self, browser_langs, *a, **kw):
        FakeAccount.__init__(self, *a, **kw)
        if browser_langs:
            lang = browser_langs[0]
            content_langs = list(browser_langs)
            content_langs.sort()
        else:
            lang = 'en'
            content_langs = 'all'
        self._defaults = self._defaults.copy()
        self._defaults['pref_lang'] = lang
        self._defaults['pref_content_langs'] = content_langs
        self._load()

    @property
    def name(self):
        raise NotImplementedError

    def _from_cookie(self):
        z = read_user_cookie(self._cookie)
        try:
            d = simplejson.loads(decrypt(z))
            return dict((k, v) for k, v in d.iteritems()
                        if k in self.allowed_prefs)
        except ValueError:
            return {}

    def _to_cookie(self, data):
        data = data.copy()
        for k in data.keys():
            if k not in self.allowed_prefs:
                del k
        set_user_cookie(self._cookie, encrypt(simplejson.dumps(data)))

    def _subscribe(self, sr):
        pass

    def _unsubscribe(self, sr):
        pass

    def _commit(self):
        if self._dirty:
            self._t.update(self._dirties)
            self._to_cookie(self._t)

    def _load(self):
        self._t.update(self._from_cookie())
        self._loaded = True

def read_user_cookie(name):
    uname = c.user.name if c.user_is_loggedin else ""
    return request.cookies.get(uname + '_' + name) or ''

def set_user_cookie(name, val):
    uname = c.user.name if c.user_is_loggedin else ""
    c.response.set_cookie(uname + '_' + name,
                          value = val,
                          domain = c.domain)

def read_click_cookie():
    if c.user_is_loggedin:
        cook = [s for s in read_user_cookie('click').split(':') if s]
        if cook:
            things = Thing._by_fullname(cook, return_dict = False)
            for t in things:
                def foo(t1, user):
                    return lambda: t1._click(user)
                utils.worker.do(foo(t, c.user))
            set_user_cookie('click', '')

            
def read_mod_cookie():
    cook = [s.split('=')[0:2] for s in read_user_cookie('mod').split(':') if s]
    if cook:
        set_user_cookie('mod', '')

def firsttime():
    if not c.user_is_loggedin:
        if not request.cookies.get("reddit_first"):
            c.response.set_cookie("reddit_first", "first",
                                  expires = NEVER,
                                  domain = c.domain)
            return True
    return False

def over18():
    if c.user.pref_over_18 or c.user_is_admin:
        return True

    else:
        cookie = request.cookies.get('over18')
        if cookie == sha.new(request.ip).hexdigest():
            return True

def set_subreddit():
    sr_name=request.environ.get("subreddit", request.params.get('r'))

    if not sr_name or sr_name == Default.name:
        c.site = Default
    elif sr_name == 'r':
        c.site = Sub
    else:
        try:
            c.site = Subreddit._by_name(sr_name)
        except NotFound:
            c.site = Default
            redirect_to("/reddits/create?name=%s" % sr_name)

    if isinstance(c.site, FakeSubreddit):
        c.default_sr = True

    # check that the site is available:
    if c.site._spam and not c.user_is_admin:
        abort(404, "not found")

def set_content_type():
    extension = request.environ.get('extension') or \
                request.environ.get('reddit-domain-extension') or \
                'html'
    c.render_style = 'html'
    if extension in ('rss', 'xml'):
        c.render_style = 'xml'
        c.response_content_type = 'text/xml; charset=UTF-8'
    elif extension == 'js':
        c.render_style = 'js'
        c.response_content_type = 'text/javascript; charset=UTF-8'
    elif extension.startswith('json') or extension == "api":
        c.response_content_type = 'application/json; charset=UTF-8'
        c.response_access_control = 'allow <*>'
        if extension == 'json-html':
            c.render_style = api_type('html')
        else:
            c.render_style = api_type()
    elif extension == 'wired':
        c.render_style = 'wired'
        c.response_content_type = 'text/javascript; charset=UTF-8'
        c.response_wrappers.append(utils.to_js)
    elif extension  == 'embed':
        c.render_style = 'htmllite'
        c.response_content_type = 'text/javascript; charset=UTF-8'
        c.response_wrappers.append(utils.to_js)
    elif extension == 'mobile':
        c.render_style = 'mobile'

def get_browser_langs():
    browser_langs = []
    langs = request.environ.get('HTTP_ACCEPT_LANGUAGE')
    if langs:
        langs = langs.split(',')
        browser_langs = []
        seen_langs = set()
        # extract languages from browser string
        for l in langs:
            if ';' in l:
                l = l.split(';')[0]
            if l not in seen_langs:
                browser_langs.append(l)
                seen_langs.add(l)
            if '-' in l:
                l = l.split('-')[0]
            if l not in seen_langs:
                browser_langs.append(l)
                seen_langs.add(l)
    return browser_langs

def set_host_lang():
    # try to grab the language from the domain
    host_lang = request.environ.get('reddit-prefer-lang')
    if host_lang:
        c.host_lang = host_lang

def set_iface_lang():
    lang = ['en']
    # GET param wins
    if c.host_lang:
        lang = [c.host_lang]
    else:
        lang = [c.user.pref_lang]

    #choose the first language
    c.lang = lang[0]

    #then try to overwrite it if we have the translation for another
    #one
    for l in lang:
        try:
            h.set_lang(l)
            c.lang = l
            break
        except h.LanguageError:
            #we don't have a translation for that language
            h.set_lang('en', graceful_fail = True)
            
    #TODO: add exceptions here for rtl languages
    if c.lang in ('ar', 'he', 'fa'):
        c.lang_rtl = True

def set_content_lang():
    if c.user.pref_content_langs != 'all':
        c.content_langs = list(c.user.pref_content_langs)
        c.content_langs.sort()
    else:
        c.content_langs = c.user.pref_content_langs

def ratelimit_agents():
    user_agent = request.user_agent
    for s in g.agents:
        if s and user_agent and s in user_agent.lower():
            key = 'rate_agent_' + s
            if cache.get(s):
                abort(503, 'service temporarily unavailable')
            else:
                cache.set(s, 't', time = 1)

#TODO i want to get rid of this function. once the listings in front.py are
#moved into listingcontroller, we shouldn't have a need for this
#anymore
def base_listing(fn):
    @validate(num    = VLimit('limit'),
              after  = VByName('after'),
              before = VByName('before'),
              count  = VCount('count'))
    def new_fn(self, before, **env):
        kw = self.build_arg_list(fn, env)
        
        #turn before into after/reverse
        kw['reverse'] = False
        if before:
            kw['after'] = before
            kw['reverse'] = True

        return fn(self, **kw)
    return new_fn

class RedditController(BaseController):

    @staticmethod
    def build_arg_list(fn, env):
        """given a fn and and environment the builds a keyword argument list
        for fn"""
        kw = {}
        argspec = inspect.getargspec(fn)

        #if there is a **kw argument in the fn definition, just pass along the environment
        if argspec[2]:
            kw = env
        #else for each entry in the arglist set the value from the environment
        else:
            #skip self
            argnames = argspec[0][1:]
            for name in argnames:
                if name in env:
                    kw[name] = env[name]
        return kw

    def request_key(self):
        key = ''.join((str(c.lang),
                       str(c.content_langs),
                       request.host,
                       request.fullpath,
                       str(c.firsttime),
                       str(c.over18)))
        return key

    def cached_response(self):
        return c.response

    @staticmethod
    def login(user, admin = False, rem = False):
        c.response.set_cookie(g.login_cookie,
                              value = user.make_cookie(admin = admin),
                              domain = c.domain,
                              expires = NEVER if rem else None)
        
    @staticmethod
    def logout(admin = False):
        c.response.set_cookie(g.login_cookie,
                              value = '',
                              domain = c.domain)

    def pre(self):
        g.cache.caches = (LocalCache(),) + g.cache.caches[1:]

        #check if user-agent needs a dose of rate-limiting
        ratelimit_agents()

        c.domain = g.domain
        c.response_wrappers = []
        c.errors = ErrorSet()
        c.firsttime = firsttime()
        (c.user, maybe_admin) = \
            valid_cookie(request.cookies.get(g.login_cookie))

        if c.user:
            c.user_is_loggedin = True
        else:
            c.user = UnloggedUser(get_browser_langs())
            c.user._load()

        if c.user_is_loggedin:
            if not c.user._loaded:
                c.user._load()
            c.modhash = c.user.modhash()
            if request.method.lower() == 'get':
                read_click_cookie()
                read_mod_cookie()
            if hasattr(c.user, 'msgtime') and c.user.msgtime:
                c.have_messages = c.user.msgtime
            c.user_is_admin = maybe_admin and c.user.name in g.admins

        c.over18 = over18()

        #set_browser_langs()
        set_host_lang()
        set_subreddit()
        set_content_type()
        set_iface_lang()
        set_content_lang()

        # check if the user has access to this subreddit
        if not c.site.can_view(c.user):
            abort(403, "forbidden")
 
        #check over 18
        if c.site.over_18 and not c.over18:
            d = dict(dest=reddit_link(request.path, url = True) + utils.query_string(request.GET))
            return redirect_to("/over18" + utils.query_string(d))

        #check content cache
        if not c.user_is_loggedin:
            r = cache.get(self.request_key())
            if r and request.method == 'GET':
                response = c.response
                response.headers = r.headers
                response.content = r.content
                response.status_code = r.status_code
                request.environ['pylons.routes_dict']['action'] = 'cached_response'
                # make sure to carry over the content type
                c.response_content_type = r.headers['content-type']
                if r.headers.has_key('access-control'):
                    c.response_access_control = r.headers['access-control']
                c.used_cache = True
                # response wrappers have already been applied before cache write
                c.response_wrappers = []
                

    def post(self):
        response = c.response
        content = response.content
        if isinstance(content, (list, tuple)):
            content = ''.join(content)
        for w in c.response_wrappers:
            content = w(content)
        response.content = content
        if c.response_content_type:
            response.headers['Content-Type'] = c.response_content_type
        if c.response_access_control:
            c.response.headers['Access-Control'] = c.response_access_control

        if c.user_is_loggedin:
            response.headers['Cache-Control'] = 'no-cache'
            response.headers['Pragma'] = 'no-cache'

        #return
        #set content cache
        if (g.page_cache_time
            and request.method == 'GET'
            and not c.user_is_loggedin
            and not c.used_cache
            and response.content and response.content[0]):
            config.cache.set(self.request_key(),
                             response,
                             g.page_cache_time)

    def abort404(self):
        abort(404, 'not found')

    def sendpng(self, string):
        c.response_content_type = 'image/png'
        c.response.content = string
        return c.response

    def sendstring(self,string):
        '''sends a string and automatically escapes &, < and > to make sure no code injection happens'''
        c.response.headers['Content-Type'] = 'text/html; charset=UTF-8'
        c.response.content = filters.websafe_json(string)
        return c.response

    def update_qstring(self, dict):
        merged = copy(request.get)
        merged.update(dict)
        return request.path + utils.query_string(merged)


