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
import r2.lib.helpers as h
from pylons import c, g, request
from pylons.controllers.util import abort, redirect_to
from pylons.i18n import _
from pylons.i18n.translation import LanguageError
from r2.lib.base import BaseController, proxyurl
from r2.lib import pages, utils, filters
from r2.lib.utils import http_utils
from r2.lib.cache import LocalCache
import random as rand
from r2.models.account import valid_cookie, FakeAccount
from r2.models.subreddit import Subreddit
import r2.config as config
from r2.models import *
from errors import ErrorSet
from validator import *
from r2.lib.template_helpers import add_sr
from r2.lib.jsontemplates import api_type

from copy import copy
from Cookie import CookieError
from datetime import datetime
import sha, inspect, simplejson
from urllib import quote, unquote

from r2.lib.tracking import encrypt, decrypt

NEVER = 'Thu, 31 Dec 2037 23:59:59 GMT'

cache_affecting_cookies = ('reddit_first','over18')

class Cookies(dict):
    def add(self, name, value, *k, **kw):
        self[name] = Cookie(value, *k, **kw)

class Cookie(object):
    def __init__(self, value, expires = None, domain = None, dirty = True):
        self.value = value
        self.expires = expires
        self.dirty = dirty
        if domain:
            self.domain = domain
        elif c.authorized_cname:
            self.domain = c.site.domain
        else:
            self.domain = g.domain

    def __repr__(self):
        return ("Cookie(value=%r, expires=%r, domain=%r, dirty=%r)"
                % (self.value, self.expires, self.domain, self.dirty))

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
    cookie_name = uname + '_' + name
    if cookie_name in c.cookies:
        return c.cookies[cookie_name].value
    else:
        return ''

def set_user_cookie(name, val):
    uname = c.user.name if c.user_is_loggedin else ""
    c.cookies[uname + '_' + name] = Cookie(value = val)
    
valid_click_cookie = re.compile(r'(t[0-9]_[a-zA-Z0-9]+:)+').match
def read_click_cookie():
    if c.user_is_loggedin:
        click_cookie = read_user_cookie('click')
        if click_cookie and valid_click_cookie(click_cookie):
            ids = [s for s in click_cookie.split(':') if s]
            things = Thing._by_fullname(ids, return_dict = False)
            for t in things:
                def foo(t1, user):
                    return lambda: t1._click(user)
                #don't record clicks for the time being
                #utils.worker.do(foo(t, c.user))
    set_user_cookie('click', '')

            
def read_mod_cookie():
    cook = [s.split('=')[0:2] for s in read_user_cookie('mod').split(':') if s]
    if cook:
        set_user_cookie('mod', '')

def firsttime():
    if get_redditfirst('firsttime'):
        return False
    else:
        set_redditfirst('firsttime','first')
        return True

def get_redditfirst(key,default=None):
    try:
        cookie = simplejson.loads(c.cookies['reddit_first'].value)
        return cookie[key]
    except (ValueError,TypeError,KeyError),e:
        # it's not a proper json dict, or the cookie isn't present, or
        # the key isn't part of the cookie; we don't really want a
        # broken cookie to propogate an exception up
        return default

def set_redditfirst(key,val):
    try:
        cookie = simplejson.loads(c.cookies['reddit_first'].value)
        cookie[key] = val
    except (ValueError,TypeError,KeyError),e:
        # invalid JSON data; we'll just construct a new cookie
        cookie = {key: val}

    c.cookies['reddit_first'] = Cookie(simplejson.dumps(cookie),
                                       expires = NEVER)

# this cookie is also accessed by organic.js, so changes to the format
# will have to be made there as well
organic_pos_key = 'organic_pos'
def organic_pos():
    "organic_pos() -> (calc_date = str(), pos  = int())"
    try:
        d,p = get_redditfirst(organic_pos_key, ('',0))
    except ValueError:
        d,p = ('',0)
    return d,p

def set_organic_pos(key,pos):
    "set_organic_pos(str(), int()) -> None"
    set_redditfirst(organic_pos_key,[key,pos])


def over18():
    if c.user.pref_over_18 or c.user_is_admin:
        return True

    else:
        if 'over18' in c.cookies:
            cookie = c.cookies['over18'].value
            if cookie == sha.new(request.ip).hexdigest():
                return True

def set_subreddit():
    #the r parameter gets added by javascript for POST requests so we
    #can reference c.site in api.py
    sr_name = request.environ.get("subreddit", request.POST.get('r'))
    domain = request.environ.get("domain")

    if not sr_name:
        #check for cnames
        sub_domain = request.environ.get('sub_domain')
        sr = Subreddit._by_domain(sub_domain) if sub_domain else None
        c.site = sr or Default
    elif sr_name == 'r':
        #reddits
        c.site = Sub
    else:
        try:
            if '+' in sr_name:
                srs = set()
                sr_names = sr_name.split('+')
                real_path = sr_name
                for sr_name in sr_names:
                    srs.add(Subreddit._by_name(sr_name))
                sr_ids = [sr._id for sr in srs]
                c.site = MultiReddit(sr_ids, real_path)
            else:
                c.site = Subreddit._by_name(sr_name)
        except NotFound:
            c.site = Default
            if chksrname(sr_name):
                redirect_to("/reddits/create?name=%s" % sr_name)
            elif not c.error_page:
                abort(404, "not found")

    #if we didn't find a subreddit, check for a domain listing
    if not sr_name and c.site == Default and domain:
        c.site = DomainSR(domain)

    if isinstance(c.site, FakeSubreddit):
        c.default_sr = True

    # check that the site is available:
    if c.site._spam and not c.user_is_admin and not c.error_page:
        abort(404, "not found")

def set_content_type():
    e = request.environ
    c.render_style = e['render_style']
    c.response_content_type = e['content_type']

    if e.has_key('extension'):
        ext = e['extension']
        if ext == 'api' or ext.startswith('json'):
            c.response_access_control = 'allow <*>'
        if ext in ('embed', 'wired'):
            c.response_wrappers.append(utils.to_js)

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

def set_cnameframe():
    if (bool(request.params.get(utils.UrlParser.cname_get)) 
        or not request.host.split(":")[0].endswith(g.domain)):
        c.cname = True
        request.environ['REDDIT_CNAME'] = 1
        if request.params.has_key(utils.UrlParser.cname_get):
            del request.params[utils.UrlParser.cname_get]
        if request.get.has_key(utils.UrlParser.cname_get):
            del request.get[utils.UrlParser.cname_get]
    c.frameless_cname  = request.environ.get('frameless_cname',  False)
    if hasattr(c.site, 'domain'):
        c.authorized_cname = request.environ.get('authorized_cname', False)

def set_colors():
    theme_rx = re.compile(r'')
    color_rx = re.compile(r'^([a-fA-F0-9]){3}(([a-fA-F0-9]){3})?$')
    c.theme = None
    if color_rx.match(request.get.get('bgcolor') or ''):
        c.bgcolor = request.get.get('bgcolor')
    if color_rx.match(request.get.get('bordercolor') or ''):
        c.bordercolor = request.get.get('bordercolor')

def set_recent_reddits():
    names = read_user_cookie('recent_reddits')
    c.recent_reddits = []
    if names:
        names = filter(None, names.split(','))
        c.recent_reddits = Subreddit._by_fullname(names, data = True,
                                                  return_dict = False)

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

        # if there is a **kw argument in the fn definition,
        # just pass along the environment
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
        # note that this references the cookie at request time, not
        # the current value of it
        cookie_keys = []
        for x in cache_affecting_cookies:
            cookie_keys.append(request.cookies.get(x,''))

        key = ''.join((str(c.lang),
                       str(c.content_langs),
                       request.host,
                       str(c.cname), 
                       str(request.fullpath),
                       str(c.over18),
                       ''.join(cookie_keys)))
        return key

    def cached_response(self):
        return c.response

    @staticmethod
    def login(user, admin = False, rem = False):
        c.cookies[g.login_cookie] = Cookie(value = user.make_cookie(admin = admin),
                                           expires = NEVER if rem else None)
        
    @staticmethod
    def logout(admin = False):
        c.cookies[g.login_cookie] = Cookie(value='')

    def pre(self):
        g.cache.caches = (LocalCache(),) + g.cache.caches[1:]

        #check if user-agent needs a dose of rate-limiting
        if not c.error_page:
            ratelimit_agents()

        # the domain has to be set before Cookies get initialized
        set_subreddit()
        set_cnameframe()

        # populate c.cookies
        c.cookies = Cookies()
        try:
            for k,v in request.cookies.iteritems():
                # we can unquote even if it's not quoted
                c.cookies[k] = Cookie(value=unquote(v), dirty=False)
        except CookieError:
            #pylons or one of the associated retarded libraries can't
            #handle broken cookies
            request.environ['HTTP_COOKIE'] = ''

        c.response_wrappers = []
        c.errors = ErrorSet()
        c.firsttime = firsttime()
        (c.user, maybe_admin) = \
            valid_cookie(c.cookies[g.login_cookie].value
                         if g.login_cookie in c.cookies
                         else '')

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

            c.user_is_sponsor = c.user_is_admin or c.user.name in g.sponsors

        c.over18 = over18()

        #set_browser_langs()
        set_host_lang()
        set_content_type()
        set_iface_lang()
        set_content_lang()
        set_colors()
        set_recent_reddits()

        # set some environmental variables in case we hit an abort
        if not isinstance(c.site, FakeSubreddit):
            request.environ['REDDIT_NAME'] = c.site.name

        # check if the user has access to this subreddit
        if not c.site.can_view(c.user) and not c.error_page:
            abort(403, "forbidden")
 
        #check over 18
        if (c.site.over_18 and not c.over18 and
            request.path not in  ("/frame", "/over18")
            and c.render_style == 'html'):
            return self.intermediate_redirect("/over18")

        #check content cache
        if not c.user_is_loggedin:
            r = cache.get(self.request_key())
            if r and request.method == 'GET':
                response = c.response
                response.headers = r.headers
                response.content = r.content

                for x in r.cookies.keys():
                    if x in cache_affecting_cookies:
                        cookie = r.cookies[x]
                        response.set_cookie(key     = x,
                                            value   = cookie.value,
                                            domain  = cookie.get('domain',None),
                                            expires = cookie.get('expires',None),
                                            path    = cookie.get('path',None))

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

        # send cookies
        if not c.used_cache:
            # if we used the cache, these cookies should be set by the
            # cached response object instead
            for k,v in c.cookies.iteritems():
                if v.dirty:
                    response.set_cookie(key     = k,
                                        value   = quote(v.value),
                                        domain  = v.domain,
                                        expires = v.expires)

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

    def check_modified(self, thing, action):
        if c.user_is_loggedin:
            return

        date = utils.is_modified_since(thing, action, request.if_modified_since)
        if date is True:
            abort(304, 'not modified')
        else:
            c.response.headers['Last-Modified'] = http_utils.http_date_str(date)

    def abort404(self):
        abort(404, "not found")

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


