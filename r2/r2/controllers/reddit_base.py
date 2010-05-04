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
# All portions of the code written by CondeNet are Copyright (c) 2006-2010
# CondeNet, Inc. All Rights Reserved.
################################################################################
import r2.lib.helpers as h
from pylons import c, g, request
from pylons.controllers.util import abort, redirect_to
from pylons.i18n import _
from pylons.i18n.translation import LanguageError
from r2.lib.base import BaseController, proxyurl
from r2.lib import pages, utils, filters, amqp
from r2.lib.utils import http_utils, UniqueIterator, ip_and_slash16
from r2.lib.cache import LocalCache, make_key, MemcachedError
import random as rand
from r2.models.account import valid_cookie, FakeAccount, valid_feed
from r2.models.subreddit import Subreddit
from r2.models import *
from errors import ErrorSet
from validator import *
from r2.lib.template_helpers import add_sr
from r2.lib.jsontemplates import api_type

from Cookie import CookieError
from copy import copy
from Cookie import CookieError
from datetime import datetime
from hashlib import sha1, md5
from urllib import quote, unquote
import simplejson
import locale

from r2.lib.tracking import encrypt, decrypt

NEVER = 'Thu, 31 Dec 2037 23:59:59 GMT'

cache_affecting_cookies = ('reddit_first','over18','_options')

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
        elif c.authorized_cname and not c.default_sr:
            self.domain = utils.common_subdomain(request.host, c.site.domain)
        else:
            self.domain = g.domain

    def __repr__(self):
        return ("Cookie(value=%r, expires=%r, domain=%r, dirty=%r)"
                % (self.value, self.expires, self.domain, self.dirty))

class UnloggedUser(FakeAccount):
    _cookie = 'options'
    allowed_prefs = ('pref_content_langs', 'pref_lang', 'pref_frame_commentspanel')

    def __init__(self, browser_langs, *a, **kw):
        FakeAccount.__init__(self, *a, **kw)
        if browser_langs:
            lang = browser_langs[0]
            content_langs = list(browser_langs)
            # try to coerce the default language 
            if g.lang not in content_langs:
                content_langs.append(g.lang)
            content_langs.sort()
        else:
            lang = g.lang
            content_langs = 'all'
        self._defaults = self._defaults.copy()
        self._defaults['pref_lang'] = lang
        self._defaults['pref_content_langs'] = content_langs
        self._defaults['pref_frame_commentspanel'] = False
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
            for k, (oldv, newv) in self._dirties.iteritems():
                self._t[k] = newv
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

    
valid_click_cookie = fullname_regex(Link, True).match
def set_recent_clicks():
    c.recent_clicks = []
    if not c.user_is_loggedin:
        return

    click_cookie = read_user_cookie('recentclicks2')
    if click_cookie:
        if valid_click_cookie(click_cookie):
            names = [ x for x in UniqueIterator(click_cookie.split(',')) if x ]

            if len(click_cookie) > 1000:
                names = names[:20]
                set_user_cookie('recentclicks2', ','.join(names))
            #eventually this will look at the user preference
            names = names[:5]
            c.recent_clicks = Link._by_fullname(names, data = True,
                                                return_dict = False)
        else:
            #if the cookie wasn't valid, clear it
            set_user_cookie('recentclicks2', '')

def read_mod_cookie():
    cook = [s.split('=')[0:2] for s in read_user_cookie('mod').split(':') if s]
    if cook:
        set_user_cookie('mod', '')

def firsttime():
    if (request.user_agent and 'iphone' in request.user_agent.lower() and 
        not get_redditfirst('iphone')):
        set_redditfirst('iphone','first')
        return 'iphone'
    elif get_redditfirst('firsttime'):
        return False
    else:
        set_redditfirst('firsttime','first')
        return True

def get_redditfirst(key,default=None):
    try:
        val = c.cookies['reddit_first'].value
        # on cookie presence, return as much
        if default is None:
            default = True
        cookie = simplejson.loads(val)
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
    pos = get_redditfirst(organic_pos_key, 0)
    if not isinstance(pos, int):
        pos = 0
    return pos

def set_organic_pos(pos):
    "set_organic_pos(str(), int()) -> None"
    set_redditfirst(organic_pos_key, pos)


def over18():
    if c.user.pref_over_18 or c.user_is_admin:
        return True

    else:
        if 'over18' in c.cookies:
            cookie = c.cookies['over18'].value
            if cookie == sha1(request.ip).hexdigest():
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

def set_content_type():
    e = request.environ
    c.render_style = e['render_style']
    c.response_content_type = e['content_type']

    if e.has_key('extension'):
        c.extension = ext = e['extension']
        if ext == 'api' or ext.startswith('json'):
            c.response_access_control = 'allow <*>'
        if ext in ('embed', 'wired', 'widget'):
            def to_js(content):
                return utils.to_js(content,callback = request.params.get(
                    "callback", "document.write"))
            c.response_wrappers.append(to_js)
        if ext in ("rss", "api", "json") and request.method.upper() == "GET":
            user = valid_feed(request.GET.get("user"),
                              request.GET.get("feed"),
                              request.path)
            if user:
                c.user = user
                c.user_is_loggedin = True

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
            if l not in seen_langs and l in g.languages:
                browser_langs.append(l)
                seen_langs.add(l)
            if '-' in l:
                l = l.split('-')[0]
            if l not in seen_langs and l in g.languages:
                browser_langs.append(l)
                seen_langs.add(l)
    return browser_langs

def set_host_lang():
    # try to grab the language from the domain
    host_lang = request.environ.get('reddit-prefer-lang')
    if host_lang:
        c.host_lang = host_lang

def set_iface_lang():
    # TODO: internationalize.  This seems the best place to put this
    # (used for formatting of large numbers to break them up with ",").
    # unfortunately, not directly compatible with gettext
    locale.setlocale(locale.LC_ALL, g.locale)
    lang = [g.lang]
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
            h.set_lang(g.lang, graceful_fail = True)
            
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

def set_recent_reddits():
    names = read_user_cookie('recent_reddits')
    c.recent_reddits = []
    if names:
        names = filter(None, names.strip('[]').split(','))
        try:
            c.recent_reddits = Subreddit._by_fullname(names, data = True,
                                                      return_dict = False)
        except NotFound:
            pass

def set_colors():
    theme_rx = re.compile(r'')
    color_rx = re.compile(r'^([a-fA-F0-9]){3}(([a-fA-F0-9]){3})?$')
    c.theme = None
    if color_rx.match(request.get.get('bgcolor') or ''):
        c.bgcolor = request.get.get('bgcolor')
    if color_rx.match(request.get.get('bordercolor') or ''):
        c.bordercolor = request.get.get('bordercolor')

def ratelimit_agents():
    user_agent = request.user_agent
    for s in g.agents:
        if s and user_agent and s in user_agent.lower():
            key = 'rate_agent_' + s
            if g.cache.get(s):
                abort(503, 'service temporarily unavailable')
            else:
                g.cache.set(s, 't', time = 1)

def throttled(key):
    return g.cache.get("throttle_" + key)

def ratelimit_throttled():
    ip, slash16 = ip_and_slash16(request)

    if throttled(ip) or throttled(slash16):
        abort(503, 'service temporarily unavailable')


#TODO i want to get rid of this function. once the listings in front.py are
#moved into listingcontroller, we shouldn't have a need for this
#anymore
def base_listing(fn):
    @validate(num    = VLimit('limit'),
              after  = VByName('after'),
              before = VByName('before'),
              count  = VCount('count'),
              target = VTarget("target"),
              show = VLength('show', 3))
    def new_fn(self, before, **env):
        if c.render_style == "htmllite":
            c.link_target = env.get("target")
        elif "target" in env:
            del env["target"]

        if "show" in env and env['show'] == 'all':
            c.ignore_hide_rules = True
        kw = build_arg_list(fn, env)

        #turn before into after/reverse
        kw['reverse'] = False
        if before:
            kw['after'] = before
            kw['reverse'] = True

        return fn(self, **kw)
    return new_fn

class MinimalController(BaseController):

    allow_stylesheets = False

    def request_key(self):
        # note that this references the cookie at request time, not
        # the current value of it
        try:
            cookies_key = [(x, request.cookies.get(x,''))
                           for x in cache_affecting_cookies]
        except CookieError:
            cookies_key = ''

        return make_key('request_key_',
                        c.lang,
                        c.content_langs,
                        request.host,
                        c.cname,
                        request.fullpath,
                        c.over18,
                        c.firsttime,
                        cookies_key)

    def cached_response(self):
        return c.response

    def pre(self):
        c.start_time = datetime.now(g.tz)
        g.reset_caches()

        c.domain_prefix = request.environ.get("reddit-domain-prefix", 
                                              g.domain_prefix)
        #check if user-agent needs a dose of rate-limiting
        if not c.error_page:
            ratelimit_agents()
            ratelimit_throttled()

        c.allow_loggedin_cache = False

        # the domain has to be set before Cookies get initialized
        set_subreddit()
        c.errors = ErrorSet()
        c.cookies = Cookies()

    def try_pagecache(self):
        #check content cache
        if not c.user_is_loggedin:
            r = g.rendercache.get(self.request_key())
            if r and request.method == 'GET':
                r, c.cookies = r
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
        content = filter(None, response.content)
        if isinstance(content, (list, tuple)):
            content = ''.join(content)
        for w in c.response_wrappers:
            content = w(content)
        response.content = content
        if c.response_content_type:
            response.headers['Content-Type'] = c.response_content_type
        if c.response_access_control:
            c.response.headers['Access-Control'] = c.response_access_control

        if c.user_is_loggedin and not c.allow_loggedin_cache:
            response.headers['Cache-Control'] = 'no-cache'
            response.headers['Pragma'] = 'no-cache'

        #return
        #set content cache
        if (g.page_cache_time
            and request.method == 'GET'
            and (not c.user_is_loggedin or c.allow_loggedin_cache)
            and not c.used_cache
            and not c.dontcache
            and response.status_code != 503
            and response.content and response.content[0]):
            try:
                g.rendercache.set(self.request_key(),
                                  (response, c.cookies),
                                  g.page_cache_time)
            except MemcachedError:
                # the key was too big to set in the rendercache
                g.log.debug("Ignored too-big render cache")

        # send cookies
        for k,v in c.cookies.iteritems():
            if v.dirty:
                response.set_cookie(key     = k,
                                    value   = quote(v.value),
                                    domain  = v.domain,
                                    expires = v.expires)

        if g.usage_sampling <= 0.0:
            return

        if g.usage_sampling >= 1.0 or rand.random() < g.usage_sampling:
            if ('pylons.routes_dict' in request.environ and
                'action' in request.environ['pylons.routes_dict']):
                action = str(request.environ['pylons.routes_dict']['action'])
            else:
                action = "unknown"
                log_text("unknown action",
                         "no action for %r" % path_info,
                         "warning")

            amqp.add_kw("usage_q",
                        start_time = c.start_time,
                        end_time = datetime.now(g.tz),
                        sampling_rate = g.usage_sampling,
                        action = action)


class RedditController(MinimalController):

    @staticmethod
    def login(user, admin = False, rem = False):
        c.cookies[g.login_cookie] = Cookie(value = user.make_cookie(admin = admin),
                                           expires = NEVER if rem else None)
        
    @staticmethod
    def logout(admin = False):
        c.cookies[g.login_cookie] = Cookie(value='')

    def pre(self):
        MinimalController.pre(self)

        set_cnameframe()

        # populate c.cookies unless we're on the unsafe media_domain
        if request.host != g.media_domain or g.media_domain == g.domain:
            try:
                for k,v in request.cookies.iteritems():
                    # we can unquote even if it's not quoted
                    c.cookies[k] = Cookie(value=unquote(v), dirty=False)
            except CookieError:
                #pylons or one of the associated retarded libraries
                #can't handle broken cookies
                request.environ['HTTP_COOKIE'] = ''

        c.response_wrappers = []
        c.firsttime = firsttime()
        (c.user, maybe_admin) = \
            valid_cookie(c.cookies[g.login_cookie].value
                         if g.login_cookie in c.cookies
                         else '')

        if c.user:
            c.user_is_loggedin = True
        else:
            c.user = UnloggedUser(get_browser_langs())
            # patch for fixing mangled language preferences
            if (not isinstance(c.user.pref_lang, basestring) or
                not all(isinstance(x, basestring)
                        for x in c.user.pref_content_langs)):
                c.user.pref_lang = g.lang
                c.user.pref_content_langs = [g.lang]
                c.user._commit()
        if c.user_is_loggedin:
            if not c.user._loaded:
                c.user._load()
            c.modhash = c.user.modhash()
            if request.method.lower() == 'get':
                read_mod_cookie()
            if hasattr(c.user, 'msgtime') and c.user.msgtime:
                c.have_messages = c.user.msgtime
            if hasattr(c.user, 'modmsgtime'):
                c.show_mod_mail = True
                if c.user.modmsgtime:
                    c.have_mod_messages = c.user.modmsgtime
            else:
                c.show_mod_mail = Subreddit.reverse_moderator_ids(c.user)
            c.user_is_admin = maybe_admin and c.user.name in g.admins
            c.user_is_sponsor = c.user_is_admin or c.user.name in g.sponsors
            if not g.disallow_db_writes:
                c.user.update_last_visit(c.start_time)

        c.over18 = over18()

        #set_browser_langs()
        set_host_lang()
        set_content_type()
        set_iface_lang()
        set_content_lang()
        set_recent_reddits()
        set_recent_clicks()
        # used for HTML-lite templates
        set_colors()

        # set some environmental variables in case we hit an abort
        if not isinstance(c.site, FakeSubreddit):
            request.environ['REDDIT_NAME'] = c.site.name

        # random reddit trickery -- have to do this after the content lang is set
        if c.site == Random:
            c.site = Subreddit.random_reddit()
            redirect_to("/" + c.site.path.strip('/') + request.path)
        elif c.site == RandomNSFW:
            c.site = Subreddit.random_reddit(over18 = True)
            redirect_to("/" + c.site.path.strip('/') + request.path)


        # check that the site is available:
        if c.site._spam and not c.user_is_admin and not c.error_page:
            abort(404, "not found")

        # check if the user has access to this subreddit
        if not c.site.can_view(c.user) and not c.error_page:
            abort(403, "forbidden")
 
        #check over 18
        if (c.site.over_18 and not c.over18 and
            request.path not in  ("/frame", "/over18")
            and c.render_style == 'html'):
            return self.intermediate_redirect("/over18")

        #check whether to allow custom styles
        c.allow_styles = self.allow_stylesheets
        if g.css_killswitch:
            c.allow_styles = False
        #if the preference is set and we're not at a cname
        elif not c.user.pref_show_stylesheets and not c.cname:
            c.allow_styles = False
        #if the site has a cname, but we're not using it
        elif c.site.domain and c.site.css_on_cname and not c.cname:
            c.allow_styles = False

    def check_modified(self, thing, action,
                       private=True, max_age=0, must_revalidate=True):
        if c.user_is_loggedin and not c.allow_loggedin_cache:
            return

        last_modified = utils.last_modified_date(thing, action)
        date_str = http_utils.http_date_str(last_modified)
        c.response.headers['last-modified'] = date_str

        cache_control = []
        if private:
            cache_control.append('private')
        cache_control.append('max-age=%d' % max_age)
        if must_revalidate:
            cache_control.append('must-revalidate')
        c.response.headers['cache-control'] = ', '.join(cache_control)

        modified_since = request.if_modified_since
        if modified_since and modified_since >= last_modified:
            abort(304, 'not modified')

    def abort404(self):
        abort(404, "not found")

    def abort403(self):
        abort(403, "forbidden")

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

    def api_wrapper(self, kw):
        data = simplejson.dumps(kw)
        if request.method == "GET" and request.GET.get("callback"):
            return "%s(%s)" % (websafe_json(request.GET.get("callback")),
                               websafe_json(data))
        return self.sendstring(data)

