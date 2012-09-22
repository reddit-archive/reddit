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

from mako.filters import url_escape
from pylons import c, g, request
from pylons.controllers.util import redirect_to
from pylons.i18n import _
from pylons.i18n.translation import LanguageError
from r2.lib import pages, utils, filters, amqp, stats
from r2.lib.utils import http_utils, is_subdomain, UniqueIterator, is_throttled
from r2.lib.cache import LocalCache, make_key, MemcachedError
import random as rand
from r2.models.account import FakeAccount, valid_feed, valid_admin_cookie
from r2.models.subreddit import Subreddit, Frontpage
from r2.models import *
from errors import ErrorSet, ForbiddenError, errors
from validator import *
from r2.lib.template_helpers import add_sr
from r2.config.extensions import is_api
from r2.lib.translation import set_lang
from r2.lib.contrib import ipaddress
from r2.lib.base import BaseController, proxyurl, abort
from r2.lib.authentication import authenticate_user

from Cookie import CookieError
from copy import copy
from Cookie import CookieError
from datetime import datetime, timedelta
from hashlib import sha1, md5
from urllib import quote, unquote
import simplejson
import locale, socket
import babel.core

from r2.lib.tracking import encrypt, decrypt
from pylons import Response

NEVER = 'Thu, 31 Dec 2037 23:59:59 GMT'
DELETE = 'Thu, 01-Jan-1970 00:00:01 GMT'

cache_affecting_cookies = ('reddit_first','over18','_options')

class Cookies(dict):
    def add(self, name, value, *k, **kw):
        name = name.encode('utf-8')
        self[name] = Cookie(value, *k, **kw)

class Cookie(object):
    def __init__(self, value, expires=None, domain=None,
                 dirty=True, secure=False, httponly=False):
        self.value = value
        self.expires = expires
        self.dirty = dirty
        self.secure = secure
        self.httponly = httponly
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

    def valid_hash(self, hash):
        return False

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

def set_user_cookie(name, val, **kwargs):
    uname = c.user.name if c.user_is_loggedin else ""
    c.cookies[uname + '_' + name] = Cookie(value=val,
                                           **kwargs)

    
valid_click_cookie = fullname_regex(Link, True).match
def set_recent_clicks():
    c.recent_clicks = []
    if not c.user_is_loggedin:
        return

    click_cookie = read_user_cookie('recentclicks2')
    if click_cookie:
        if valid_click_cookie(click_cookie):
            names = [ x for x in UniqueIterator(click_cookie.split(',')) if x ]

            if len(names) > 5:
                names = names[:5]
                set_user_cookie('recentclicks2', ','.join(names))
            #eventually this will look at the user preference
            names = names[:5]

            try:
                c.recent_clicks = Link._by_fullname(names, data = True,
                                                    return_dict = False)
            except NotFound:
                # clear their cookie because it's got bad links in it
                set_user_cookie('recentclicks2', '')
        else:
            #if the cookie wasn't valid, clear it
            set_user_cookie('recentclicks2', '')

def read_mod_cookie():
    cook = [s.split('=')[0:2] for s in read_user_cookie('mod').split(':') if s]
    if cook:
        set_user_cookie('mod', '')

def firsttime():
    if (request.user_agent and
        ('iphone' in request.user_agent.lower() or
         'android' in request.user_agent.lower()) and 
        not get_redditfirst('mobile_suggest')):
        set_redditfirst('mobile_suggest','first')
        return 'mobile_suggest'
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

def set_obey_over18():
    "querystring parameter for API to obey over18 filtering rules"
    c.obey_over18 = request.GET.get("obey_over18") == "true"

def set_subreddit():
    #the r parameter gets added by javascript for POST requests so we
    #can reference c.site in api.py
    sr_name = request.environ.get("subreddit", request.POST.get('r'))
    domain = request.environ.get("domain")

    can_stale = request.method.upper() in ('GET','HEAD')

    c.site = Frontpage
    if not sr_name:
        #check for cnames
        cname = request.environ.get('legacy-cname')
        if cname:
            sr = Subreddit._by_domain(cname) or Frontpage
            domain = g.domain
            if g.domain_prefix:
                domain = ".".join((g.domain_prefix, domain))
            redirect_to('http://%s%s' % (domain, sr.path), _code=301)
    elif sr_name == 'r':
        #reddits
        c.site = Sub
    elif '+' in sr_name:
        sr_names = sr_name.split('+')
        srs = set(Subreddit._by_name(sr_names, stale=can_stale).values())
        if All in srs:
            c.site = All
        elif Friends in srs:
            c.site = Friends
        else:
            srs = [sr for sr in srs if not isinstance(sr, FakeSubreddit)]
            if len(srs) == 0:
                c.site = MultiReddit([], sr_name)
            elif len(srs) == 1:
                c.site = srs.pop()    
            else:
                sr_ids = [sr._id for sr in srs]
                c.site = MultiReddit(sr_ids, sr_name)
    else:
        try:
            c.site = Subreddit._by_name(sr_name, stale=can_stale)
        except NotFound:
            sr_name = chksrname(sr_name)
            if sr_name:
                redirect_to("/reddits/search?q=%s" % sr_name)
            elif not c.error_page and not request.path.startswith("/api/login/") :
                abort(404)

    #if we didn't find a subreddit, check for a domain listing
    if not sr_name and isinstance(c.site, DefaultSR) and domain:
        c.site = DomainSR(domain)

    if isinstance(c.site, FakeSubreddit):
        c.default_sr = True

def set_content_type():
    e = request.environ
    c.render_style = e['render_style']
    c.response_content_type = e['content_type']

    if e.has_key('extension'):
        c.extension = ext = e['extension']
        if ext in ('embed', 'wired', 'widget'):
            def to_js(content):
                return utils.to_js(content,callback = request.params.get(
                    "callback", "document.write"))
            c.response_wrappers.append(to_js)
        if ext in ("rss", "api", "json") and request.method.upper() == "GET":
            user = valid_feed(request.GET.get("user"),
                              request.GET.get("feed"),
                              request.path)
            if user and not g.read_only_mode:
                c.user = user
                c.user_is_loggedin = True
        if ext in ("mobile", "m") and not request.GET.get("keep_extension"):
            try:
                if request.cookies['reddit_mobility'] == "compact":
                    c.extension = "compact"
                    c.render_style = "compact"
            except (ValueError, KeyError):
                c.suggest_compact = True
        if ext in ("mobile", "m", "compact"):
            if request.GET.get("keep_extension"):
                c.cookies['reddit_mobility'] = Cookie(ext, expires = NEVER)
    # allow JSONP requests to generate callbacks, but do not allow
    # the user to be logged in for these 
    if (is_api() and request.method.upper() == "GET" and
        request.GET.get("jsonp")):
        c.allowed_callback = request.GET['jsonp']
        c.user = UnloggedUser(get_browser_langs())
        c.user_is_loggedin = False

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
    locale.setlocale(locale.LC_ALL, g.locale)
    lang = [g.lang]
    # GET param wins
    if c.host_lang:
        lang = [c.host_lang]
    else:
        lang = [c.user.pref_lang]

    if getattr(g, "lang_override") and lang[0] == "en":
        lang.insert(0, g.lang_override)

    #choose the first language
    c.lang = lang[0]

    #then try to overwrite it if we have the translation for another
    #one
    for l in lang:
        try:
            set_lang(l, fallback_lang=g.lang)
            c.lang = l
            break
        except LanguageError:
            #we don't have a translation for that language
            set_lang(g.lang, graceful_fail=True)

    try:
        c.locale = babel.core.Locale.parse(c.lang, sep='-')
    except (babel.core.UnknownLocaleError, ValueError):
        c.locale = babel.core.Locale.parse(g.lang, sep='-')

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
    color_rx = re.compile(r'\A([a-fA-F0-9]){3}(([a-fA-F0-9]){3})?\Z')
    c.theme = None
    if color_rx.match(request.get.get('bgcolor') or ''):
        c.bgcolor = request.get.get('bgcolor')
    if color_rx.match(request.get.get('bordercolor') or ''):
        c.bordercolor = request.get.get('bordercolor')

def ratelimit_agent(agent):
    key = 'rate_agent_' + agent
    if g.cache.get(key):
        request.environ['retry_after'] = 1
        abort(429)
    else:
        g.cache.set(key, 't', time = 1)

appengine_re = re.compile(r'AppEngine-Google; \(\+http://code.google.com/appengine; appid: s~([a-z0-9-]{6,30})\)\Z')
def ratelimit_agents():
    user_agent = request.user_agent

    if not user_agent:
        return

    # parse out the appid for appengine apps
    appengine_match = appengine_re.match(user_agent)
    if appengine_match:
        appid = appengine_match.group(1)
        ratelimit_agent(appid)
        return

    user_agent = user_agent.lower()
    for s in g.agents:
        if s and user_agent and s in user_agent:
            ratelimit_agent(s)

def ratelimit_throttled():
    ip = request.ip.strip()
    if is_throttled(ip):
        abort(429)


def paginated_listing(default_page_size=25, max_page_size=100, backend='sql'):
    def decorator(fn):
        @validate(num=VLimit('limit', default=default_page_size,
                             max_limit=max_page_size),
                  after=VByName('after', backend=backend),
                  before=VByName('before', backend=backend),
                  count=VCount('count'),
                  target=VTarget("target"),
                  show=VLength('show', 3))
        @utils.wraps_api(fn)
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
    return decorator

#TODO i want to get rid of this function. once the listings in front.py are
#moved into listingcontroller, we shouldn't have a need for this
#anymore
def base_listing(fn):
    return paginated_listing()(fn)

def is_trusted_origin(origin):
    try:
        origin = urlparse(origin)
    except ValueError:
        return False
    
    return any(is_subdomain(origin.hostname, domain) for domain in g.trusted_domains)

def cross_domain(origin_check=is_trusted_origin, **options):
    """Set up cross domain validation and hoisting for a request handler."""
    def cross_domain_wrap(fn):
        cors_perms = {
            "origin_check": origin_check,
            "allow_credentials": bool(options.get("allow_credentials"))
        }

        def cross_domain_handler(self, *args, **kwargs):
            if request.params.get("hoist") == "cookie":
                # Cookie polling response
                if cors_perms["origin_check"](g.origin):
                    name = request.environ["pylons.routes_dict"]["action_name"]
                    resp = fn(self, *args, **kwargs)
                    c.cookies.add('hoist_%s' % name, ''.join(resp.content))
                    c.response_content_type = 'text/html'
                    resp.content = ''
                    return resp
                else:
                    abort(403)
            else:
                self.check_cors()
                return fn(self, *args, **kwargs)

        cross_domain_handler.cors_perms = cors_perms
        return cross_domain_handler
    return cross_domain_wrap

def require_https():
    if not c.secure:
        abort(ForbiddenError(errors.HTTPS_REQUIRED))

def prevent_framing_and_css(allow_cname_frame=False):
    def wrap(f):
        @utils.wraps_api(f)
        def no_funny_business(*args, **kwargs):
            c.allow_styles = False
            if not (allow_cname_frame and c.cname and not c.authorized_cname):
                c.deny_frames = True
            return f(*args, **kwargs)
        return no_funny_business
    return wrap

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
                        c.secure,
                        c.cname,
                        request.fullpath,
                        c.over18,
                        c.firsttime,
                        c.extension,
                        c.render_style,
                        cookies_key)

    def cached_response(self):
        return c.response

    def pre(self):

        c.start_time = datetime.now(g.tz)
        g.reset_caches()

        c.domain_prefix = request.environ.get("reddit-domain-prefix",
                                              g.domain_prefix)
        c.secure = request.host in g.secure_domains

        #check if user-agent needs a dose of rate-limiting
        if not c.error_page:
            ratelimit_throttled()
            ratelimit_agents()

        c.allow_loggedin_cache = False
        
        c.show_wiki_actions = False
        
        # the domain has to be set before Cookies get initialized
        set_subreddit()
        c.errors = ErrorSet()
        c.cookies = Cookies()
        # if an rss feed, this will also log the user in if a feed=
        # GET param is included
        set_content_type()

    def try_pagecache(self):
        #check content cache
        if request.method.upper() == 'GET' and not c.user_is_loggedin:
            r = g.rendercache.get(self.request_key())
            if r:
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
                                            path    = cookie.get('path',None),
                                            secure  = cookie.get('secure', False),
                                            httponly = cookie.get('httponly', False))

                response.status_code = r.status_code
                request.environ['pylons.routes_dict']['action'] = 'cached_response'
                # make sure to carry over the content type
                c.response_content_type = r.headers['content-type']
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

        if c.user_is_loggedin and not c.allow_loggedin_cache:
            response.headers['Cache-Control'] = 'no-cache'
            response.headers['Pragma'] = 'no-cache'

        if c.deny_frames:
            response.headers["X-Frame-Options"] = "DENY"

        #return
        #set content cache
        if (g.page_cache_time
            and request.method.upper() == 'GET'
            and (not c.user_is_loggedin or c.allow_loggedin_cache)
            and not c.used_cache
            and response.status_code not in (429, 503)
            and response.content and response.content[0]):
            try:
                g.rendercache.set(self.request_key(),
                                  (response, c.cookies),
                                  g.page_cache_time)
            except MemcachedError as e:
                # this codepath will actually never be hit as long as
                # the pagecache memcached client is in no_reply mode.
                g.log.warning("Ignored exception (%r) on pagecache "
                              "write for %r", e, request.path)

        # send cookies
        for k,v in c.cookies.iteritems():
            if v.dirty:
                response.set_cookie(key     = k,
                                    value   = quote(v.value),
                                    domain  = v.domain,
                                    expires = v.expires,
                                    secure  = getattr(v, 'secure', False),
                                    httponly = getattr(v, 'httponly', False))

        end_time = datetime.now(g.tz)

        # update last_visit
        if (c.user_is_loggedin and not g.disallow_db_writes and
            request.path != '/validuser'):
            c.user.update_last_visit(c.start_time)

        if ('pylons.routes_dict' in request.environ and
            'action' in request.environ['pylons.routes_dict']):
            action = str(request.environ['pylons.routes_dict']['action'])
        else:
            action = "unknown"
            log_text("unknown action", "no action for %r" % path_info,
                     "warning")
        if g.usage_sampling >= 1.0 or rand.random() < g.usage_sampling:

            amqp.add_kw("usage_q",
                        start_time = c.start_time,
                        end_time = end_time,
                        sampling_rate = g.usage_sampling,
                        action = action)

        check_request(end_time)

        # this thread is probably going to be reused, but it could be
        # a while before it is. So we might as well dump the cache in
        # the mean time so that we don't have dead objects hanging
        # around taking up memory
        g.reset_caches()

        # push data to statsd
        if 'pylons.action_method' in request.environ:
            # only report web timing data if an action handler was called
            g.stats.transact('web.%s' % action,
                             (end_time - c.start_time).total_seconds())
        g.stats.flush_timing_stats()

    def abort404(self):
        abort(404, "not found")

    def abort403(self):
        abort(403, "forbidden")

    def check_cors(self):
        origin = request.headers.get("Origin")
        if not origin:
            return

        method = request.method
        if method == 'OPTIONS':
            # preflight request
            method = request.headers.get("Access-Control-Request-Method")
            if not method:
                self.abort403()

        action = request.environ["pylons.routes_dict"]["action_name"]

        handler = self._get_action_handler(action, method)
        cors = handler and getattr(handler, "cors_perms", None)

        if cors and cors["origin_check"](origin):
            response.headers["Access-Control-Allow-Origin"] = origin
            if cors.get("allow_credentials"):
                response.headers["Access-Control-Allow-Credentials"] = "true"

    def OPTIONS(self):
        """Return empty responses for CORS preflight requests"""
        self.check_cors()

    def sendpng(self, string):
        c.response_content_type = 'image/png'
        c.response.content = string
        return c.response

    def update_qstring(self, dict):
        merged = copy(request.get)
        merged.update(dict)
        return request.path + utils.query_string(merged)

    def api_wrapper(self, kw):
        data = simplejson.dumps(kw)
        c.response.content = filters.websafe_json(data)
        return c.response

    def iframe_api_wrapper(self, kw):
        data = simplejson.dumps(kw)
        c.response_content_type = 'text/html'
        c.response.content = (
            '<html><head><script type="text/javascript">\n'
            'parent.$.handleResponse().call('
            'parent.$("#" + window.frameElement.id).parent(), %s)\n'
            '</script></head></html>') % filters.websafe_json(data)
        return c.response


class RedditController(MinimalController):

    @staticmethod
    def login(user, rem=False):
        c.cookies[g.login_cookie] = Cookie(value = user.make_cookie(),
                                           expires = NEVER if rem else None)

    @staticmethod
    def logout():
        c.cookies[g.login_cookie] = Cookie(value='', expires=DELETE)

    @staticmethod
    def enable_admin_mode(user, first_login=None):
        # no expiration time so the cookie dies with the browser session
        c.cookies[g.admin_cookie] = Cookie(value=user.make_admin_cookie(first_login=first_login))

    @staticmethod
    def remember_otp(user):
        cookie = user.make_otp_cookie()
        expiration = datetime.utcnow() + timedelta(seconds=g.OTP_COOKIE_TTL)
        expiration = expiration.strftime("%a, %d %b %Y %H:%M:%S GMT")
        set_user_cookie(g.otp_cookie,
                        cookie,
                        secure=True,
                        httponly=True,
                        expires=expiration)

    @staticmethod
    def disable_admin_mode(user):
        c.cookies[g.admin_cookie] = Cookie(value='', expires=DELETE)

    def pre(self):
        c.response_wrappers = []
        MinimalController.pre(self)

        set_cnameframe()

        # populate c.cookies unless we're on the unsafe media_domain
        if request.host != g.media_domain or g.media_domain == g.domain:
            try:
                for k,v in request.cookies.iteritems():
                    # minimalcontroller can still set cookies
                    if k not in c.cookies:
                        # we can unquote even if it's not quoted
                        c.cookies[k] = Cookie(value=unquote(v), dirty=False)
            except CookieError:
                #pylons or one of the associated retarded libraries
                #can't handle broken cookies
                request.environ['HTTP_COOKIE'] = ''

        c.firsttime = firsttime()

        # the user could have been logged in via one of the feeds 
        maybe_admin = False
        is_otpcookie_valid = False

        # no logins for RSS feed unless valid_feed has already been called
        if not c.user:
            if c.extension != "rss":
                authenticate_user()

                admin_cookie = c.cookies.get(g.admin_cookie)
                if c.user_is_loggedin and admin_cookie:
                    maybe_admin, first_login = valid_admin_cookie(admin_cookie.value)

                    if maybe_admin:
                        self.enable_admin_mode(c.user, first_login=first_login)
                    else:
                        self.disable_admin_mode(c.user)

                otp_cookie = read_user_cookie(g.otp_cookie)
                if c.user_is_loggedin and otp_cookie:
                    is_otpcookie_valid = valid_otp_cookie(otp_cookie)

            if not c.user:
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
            if request.method.upper() == 'GET':
                read_mod_cookie()
            if hasattr(c.user, 'msgtime') and c.user.msgtime:
                c.have_messages = c.user.msgtime
            c.show_mod_mail = Subreddit.reverse_moderator_ids(c.user)
            c.have_mod_messages = getattr(c.user, "modmsgtime", False)
            c.user_is_admin = maybe_admin and c.user.name in g.admins
            c.user_special_distinguish = c.user.special_distinguish()
            c.user_is_sponsor = c.user_is_admin or c.user.name in g.sponsors
            c.otp_cached = is_otpcookie_valid
            if not isinstance(c.site, FakeSubreddit) and not g.disallow_db_writes:
                c.user.update_sr_activity(c.site)

        c.over18 = over18()
        set_obey_over18()

        #set_browser_langs()
        set_host_lang()
        set_iface_lang()
        set_content_lang()
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
        
        if not request.path.startswith("/api/login/"):
            # is the subreddit banned?
            if c.site.spammy() and not c.user_is_admin and not c.error_page:
                ban_info = getattr(c.site, "ban_info", {})
                if "message" in ban_info:
                    message = ban_info['message']
                else:
                    sitelink = url_escape(add_sr("/"))
                    subject = ("/r/%s has been incorrectly banned" %
                                   c.site.name)
                    link = ("/r/redditrequest/submit?url=%s&title=%s" %
                                (sitelink, subject))
                    message = strings.banned_subreddit_message % dict(
                                                                    link=link)
                errpage = pages.RedditError(strings.banned_subreddit_title,
                                            message,
                                            image="subreddit-banned.png")
                request.environ['usable_error_content'] = errpage.render()
                self.abort404()

            # check if the user has access to this subreddit
            if not c.site.can_view(c.user) and not c.error_page:
                public_description = c.site.public_description
                errpage = pages.RedditError(strings.private_subreddit_title,
                                            strings.private_subreddit_message,
                                            image="subreddit-private.png",
                                            sr_description=public_description)
                request.environ['usable_error_content'] = errpage.render()
                self.abort403()

            #check over 18
            if (c.site.over_18 and not c.over18 and
                request.path not in ("/frame", "/over18")
                and c.render_style == 'html'):
                return self.intermediate_redirect("/over18")

        #check whether to allow custom styles
        c.allow_styles = True
        c.can_apply_styles = self.allow_stylesheets
        if g.css_killswitch:
            c.can_apply_styles = False
        #if the preference is set and we're not at a cname
        elif not c.user.pref_show_stylesheets and not c.cname:
            c.can_apply_styles = False
        #if the site has a cname, but we're not using it
        elif c.site.domain and c.site.css_on_cname and not c.cname:
            c.can_apply_styles = False

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

    def search_fail(self, exception):
        from r2.lib.search import SearchException
        if isinstance(exception, SearchException + (socket.error,)):
            g.log.error("Search Error: %s" % repr(exception))

        errpage = pages.RedditError(_("search failed"),
                                    strings.search_failed)

        request.environ['usable_error_content'] = errpage.render()
        request.environ['retry_after'] = 60
        abort(503)
