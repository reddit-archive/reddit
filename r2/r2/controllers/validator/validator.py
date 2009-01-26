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
from pylons import c, request, g
from pylons.i18n import _
from pylons.controllers.util import abort
from r2.lib import utils, captcha
from r2.lib.filters import unkeep_space, websafe, _force_unicode
from r2.lib.db.operators import asc, desc
from r2.lib.template_helpers import add_sr
from r2.lib.jsonresponse import json_respond, JQueryResponse
from r2.lib.jsontemplates import api_type

from r2.models import *

from r2.controllers.errors import errors, UserRequiredException

from copy import copy
from datetime import datetime, timedelta
import re, inspect

class Validator(object):
    default_param = None
    def __init__(self, param=None, default=None, post=True, get=True, url=True):
        if param:
            self.param = param
        else:
            self.param = self.default_param

        self.default = default
        self.post, self.get, self.url = post, get, url

    def set_error(self, error, msg_params = {}):
        """
        Adds the provided error to c.errors and flags that it is come
        from the validator's param
        """
        c.errors.add(error, msg_params = msg_params, field = self.param)

    def __call__(self, url):
        a = []
        if self.param:
            for p in utils.tup(self.param):
                if self.post and request.post.get(p):
                    val = request.post[p]
                elif self.get and request.get.get(p):
                    val = request.get[p]
                elif self.url and url.get(p):
                    val = url[p]
                else:
                    val = self.default
                a.append(val)
        return self.run(*a)


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

def _make_validated_kw(fn, simple_vals, param_vals, env):
    for validator in simple_vals:
        validator(env)
    kw = build_arg_list(fn, env)
    for var, validator in param_vals.iteritems():
        kw[var] = validator(env)
    return kw
    

def validate(*simple_vals, **param_vals):
    def val(fn):
        def newfn(self, *a, **env):
            try:
                kw = _make_validated_kw(fn, simple_vals, param_vals, env)
                return fn(self, *a, **kw)
            except UserRequiredException:
                return self.intermediate_redirect('/login')
        return newfn
    return val

def noresponse(*simple_vals, **param_vals):
    """
    AJAXy decorator which takes the place of validate when no response
    is expected from the controller method.
    """
    def val(fn):
        def newfn(self, *a, **env):
            c.render_style = api_type('html')
            c.response_content_type = 'application/json; charset=UTF-8'
            jquery = JQueryResponse()

            validate(*simple_vals, **param_vals)(fn)(self, *a, **env)

            return self.response_func()
        return newfn
    return val


def validatedForm(*simple_vals, **param_vals):
    """
    AJAX response validator for general form handling. In addition to
    validating simple_vals and param_vals in the same way as validate,
    a jquery object and a jquery form object are allocated and passed
    into the method which is decorated.
    """
    def val(fn):
        def newfn(self, *a, **env):
            # set the content type for the response
            c.render_style = api_type('html')
            c.response_content_type = 'application/json; charset=UTF-8'

            # generate a response object
            jquery = JQueryResponse()
            # generate a form object
            form = jquery(request.POST.get('id', "body"))
            # clear out the status line as a courtesy
            form.set_html(".status", "")

            try:

                kw = _make_validated_kw(fn, simple_vals, param_vals, env)
                val = fn(self, form, jquery, *a, **kw)

                # auto-refresh the captcha if there are errors.
                if (c.errors.errors and
                    any(isinstance(v, VCaptcha) for v in simple_vals)):
                    form.new_captcha()
                
                if val: return val
                return self.response_func(**dict(list(jquery)))

            except UserRequiredException:
                return  self.ajax_login_redirect("/")
        return newfn
    return val



#### validators ####
class nop(Validator):
    def run(self, x):
        return x

class VLang(Validator):
    def run(self, lang):
        if lang:
            lang = str(lang.split('[')[1].strip(']'))
            if lang in g.all_languages:
                return lang
        #else
        return 'en'

class VRequired(Validator):
    def __init__(self, param, error, *a, **kw):
        Validator.__init__(self, param, *a, **kw)
        self._error = error

    def error(self, e = None):
        if not e: e = self._error
        if e:
            self.set_error(e)
        
    def run(self, item):
        if not item:
            self.error()
        else:
            return item

class VLink(Validator):
    def __init__(self, param, redirect = True, *a, **kw):
        Validator.__init__(self, param, *a, **kw)
        self.redirect = redirect
    
    def run(self, link_id):
        if link_id:
            try:
                aid = int(link_id, 36)
                return Link._byID(aid, True)
            except (NotFound, ValueError):
                if self.redirect:
                    abort(404, 'page not found')
                else:
                    return None

class VMessage(Validator):
    def run(self, message_id):
        if message_id:
            try:
                aid = int(message_id, 36)
                return Message._byID(aid, True)
            except (NotFound, ValueError):
                abort(404, 'page not found')


class VCommentID(Validator):
    def run(self, cid):
        if cid:
            try:
                cid = int(cid, 36)
                return Comment._byID(cid, True)
            except (NotFound, ValueError):
                pass

class VCount(Validator):
    def run(self, count):
        if count is None:
            count = 0
        return max(int(count), 0)


class VLimit(Validator):
    def run(self, limit):
        if limit is None:
            return c.user.pref_numsites 
        return min(max(int(limit), 1), 100)

class VCssMeasure(Validator):
    measure = re.compile(r"^\s*[\d\.]+\w{0,3}\s*$")
    def run(self, value):
        return value if value and self.measure.match(value) else ''

subreddit_rx = re.compile(r"^[\w]{3,20}$", re.UNICODE)

def chksrname(x):
    #notice the space before reddit.com
    if x in ('friends', 'all', ' reddit.com'):
        return False

    try:
        return str(x) if x and subreddit_rx.match(x) else None
    except UnicodeEncodeError:
        return None


class VLinkFullnames(Validator):
    "A space- or comma-separated list of fullnames for Links"
    valid_re = re.compile(r'^(' + Link._type_prefix + str(Link._type_id) +
                          r'_[0-9a-z]+[ ,]?)+$')
    splitter = re.compile('[ ,]+')

    def __init__(self, item, *a, **kw):
        self.item = item
        Validator.__init__(self, item, *a, **kw)
    
    def run(self, val):
        if val and self.valid_re.match(val):
            return self.splitter.split(val)
    
class VLength(Validator):
    def __init__(self, item, length = 10000,
                 empty_error = errors.BAD_COMMENT,
                 length_error = errors.COMMENT_TOO_LONG, **kw):
        Validator.__init__(self, item, **kw)
        self.length = length
        self.len_error = length_error
        self.emp_error = empty_error

    def run(self, title):
        if not title:
            self.set_error(self.emp_error)
        elif len(title) > self.length:
            self.set_error(self.len_error)
        else:
            return title
        
class VTitle(VLength):
    only_whitespace = re.compile(r"^\s*$", re.UNICODE)
    
    def __init__(self, item, length = 300, **kw):
        VLength.__init__(self, item, length = length,
                         empty_error = errors.NO_TITLE,
                         length_error = errors.TITLE_TOO_LONG, **kw)

    def run(self, title):
        title = VLength.run(self, title)
        if title and self.only_whitespace.match(title):
            self.set_error(errors.NO_TITLE)
        else:
            return title
    
class VComment(VLength):
    def __init__(self, item, length = 10000, **kw):
        VLength.__init__(self, item, length = length, **kw)

        
class VMessage(VLength):
    def __init__(self, item, length = 10000, **kw):
        VLength.__init__(self, item, length = length, 
                         empty_error = errors.NO_MSG_BODY, **kw)


class VSubredditName(VRequired):
    def __init__(self, item, *a, **kw):
        VRequired.__init__(self, item, errors.BAD_SR_NAME, *a, **kw)

    def run(self, name):
        name = chksrname(name)
        if not name:
            return self.error()
        else:
            try:
                a = Subreddit._by_name(name)
                return self.error(errors.SUBREDDIT_EXISTS)
            except NotFound:
                return name

class VSubredditTitle(Validator):
    def run(self, title):
        if not title:
            self.set_error(errors.NO_TITLE)
        elif len(title) > 100:
            self.set_error(errors.TITLE_TOO_LONG)
        else:
            return title

class VSubredditDesc(Validator):
    def run(self, description):
        if description and len(description) > 500:
            self.set_error(errors.DESC_TOO_LONG)
        return unkeep_space(description or '')

class VAccountByName(VRequired):
    def __init__(self, param, error = errors.USER_DOESNT_EXIST, *a, **kw):
        VRequired.__init__(self, param, error, *a, **kw)
        
    def run(self, name):
        if name:
            try:
                return Account._by_name(name)
            except NotFound: pass
        return self.error()

class VByName(VRequired):
    def __init__(self, param, 
                 error = errors.NO_THING_ID, *a, **kw):
        VRequired.__init__(self, param, error, *a, **kw)

    def run(self, fullname):
        if fullname:
            try:
                return Thing._by_fullname(fullname, False, data=True)
            except NotFound:
                pass
        return self.error()

class VByNameIfAuthor(VByName):
    def run(self, fullname):
        thing = VByName.run(self, fullname)
        if thing:
            if not thing._loaded: thing._load()
            if c.user_is_loggedin and thing.author_id == c.user._id:
                return thing
        return self.error(errors.NOT_AUTHOR)

class VCaptcha(Validator):
    default_param = ('iden', 'captcha')
    
    def run(self, iden, solution):
        if (not c.user_is_loggedin or c.user.needs_captcha()):
            if not captcha.valid_solution(iden, solution):
                self.set_error(errors.BAD_CAPTCHA)

class VUser(Validator):
    def run(self, password = None):
        if not c.user_is_loggedin:
            raise UserRequiredException

        if (password is not None) and not valid_password(c.user, password):
            self.set_error(errors.WRONG_PASSWORD)
            
class VModhash(Validator):
    default_param = 'uh'
    def run(self, uh):
        pass

class VVotehash(Validator):
    def run(self, vh, thing_name):
        return True

class VAdmin(Validator):
    def run(self):
        if not c.user_is_admin:
            abort(404, "page not found")

class VSponsor(Validator):
    def run(self):
        if not c.user_is_sponsor:
            abort(403, 'forbidden')

class VSrModerator(Validator):
    def run(self):
        if not (c.user_is_loggedin and c.site.is_moderator(c.user) 
                or c.user_is_admin):
            abort(403, "forbidden")

class VSrCanBan(Validator):
    def run(self, thing_name):
        if c.user_is_admin:
            return True
        elif c.user_is_loggedin:
            item = Thing._by_fullname(thing_name,data=True)
            # will throw a legitimate 500 if this isn't a link or
            # comment, because this should only be used on links and
            # comments
            subreddit = item.subreddit_slow
            if subreddit.can_ban(c.user):
                return True
        abort(403,'forbidden')

class VSrSpecial(Validator):
    def run(self, thing_name):
        if c.user_is_admin:
            return True
        elif c.user_is_loggedin:
            item = Thing._by_fullname(thing_name,data=True)
            # will throw a legitimate 500 if this isn't a link or
            # comment, because this should only be used on links and
            # comments
            subreddit = item.subreddit_slow
            if subreddit.is_special(c.user):
                return True
        abort(403,'forbidden')

class VSRSubmitPage(Validator):
    def run(self):
        if not (c.default_sr or c.user_is_loggedin and 
                c.site.can_submit(c.user)):
            abort(403, "forbidden")

class VSubmitParent(Validator):
    def run(self, fullname):
        if fullname:
            parent = Thing._by_fullname(fullname, False, data=True)
            if parent and parent._deleted:
                self.set_error(errors.DELETED_COMMENT)
            if isinstance(parent, Message):
                return parent
            else:
                sr = parent.subreddit_slow
                if c.user_is_loggedin and sr.can_comment(c.user):
                    return parent
        #else
        abort(403, "forbidden")

class VSubmitSR(Validator):
    def run(self, sr_name):
        try:
            sr = Subreddit._by_name(sr_name)
        except (NotFound, AttributeError):
            self.set_error(errors.SUBREDDIT_NOEXIST)
            sr = None

        if sr and not (c.user_is_loggedin and sr.can_submit(c.user)):
            abort(403, "forbidden")
        else:
            return sr
        
pass_rx = re.compile(r".{3,20}")

def chkpass(x):
    return x if x and pass_rx.match(x) else None

class VPassword(VRequired):
    def __init__(self, item, *a, **kw):
        VRequired.__init__(self, item, errors.BAD_PASSWORD, *a, **kw)
    def run(self, password, verify):
        if not chkpass(password):
            return self.error()
        elif verify != password:
            return self.error(errors.BAD_PASSWORD_MATCH)
        else:
            return password

user_rx = re.compile(r"^[\w-]{3,20}$", re.UNICODE)

def chkuser(x):
    try:
        return str(x) if user_rx.match(x) else None
    except TypeError:
        return None
    except UnicodeEncodeError:
        return None

class VUname(VRequired):
    def __init__(self, item, *a, **kw):
        VRequired.__init__(self, item, errors.BAD_USERNAME, *a, **kw)
    def run(self, user_name):
        user_name = chkuser(user_name)
        if not user_name:
            return self.error(errors.BAD_USERNAME)
        else:
            try:
                a = Account._by_name(user_name, True)
                return self.error(errors.USERNAME_TAKEN)
            except NotFound:
                return user_name

class VLogin(VRequired):
    def __init__(self, item, *a, **kw):
        VRequired.__init__(self, item, errors.WRONG_PASSWORD, *a, **kw)
        
    def run(self, user_name, password):
        user_name = chkuser(user_name)
        user = None
        if user_name:
            user = valid_login(user_name, password)
        if not user:
            return self.error()
        return user


class VSanitizedUrl(Validator):
    def run(self, url):
        return utils.sanitize_url(url)

class VUrl(VRequired):
    def __init__(self, item, allow_self = True, *a, **kw):
        self.allow_self = allow_self
        VRequired.__init__(self, item, errors.NO_URL, *a, **kw)

    def run(self, url, sr = None):
        if sr is None and not isinstance(c.site, FakeSubreddit):
            sr = c.site
        elif sr:
            try:
                sr = Subreddit._by_name(sr)
            except NotFound:
                self.set_error(errors.SUBREDDIT_NOEXIST)
                sr = None
        else:
            sr = None
        
        if not url:
            return self.error(errors.NO_URL)
        url = utils.sanitize_url(url)
        if url == 'self':
            if self.allow_self:
                return url
        elif url:
            try:
                l = Link._by_url(url, sr)
                self.error(errors.ALREADY_SUB)
                return utils.tup(l)
            except NotFound:
                return url
        return self.error(errors.BAD_URL)

class VExistingUname(VRequired):
    def __init__(self, item, *a, **kw):
        VRequired.__init__(self, item, errors.NO_USER, *a, **kw)

    def run(self, name):
        if name:
            try:
                return Account._by_name(name)
            except NotFound:
                return self.error(errors.USER_DOESNT_EXIST)
        self.error()

class VUserWithEmail(VExistingUname):
    def run(self, name):
        user = VExistingUname.run(self, name)
        if not user or not hasattr(user, 'email') or not user.email:
            return self.error(errors.NO_EMAIL_FOR_USER)
        return user
            

class VBoolean(Validator):
    def run(self, val):
        return val != "off" and bool(val)

class VInt(Validator):
    def __init__(self, param, min=None, max=None, *a, **kw):
        self.min = min
        self.max = max
        Validator.__init__(self, param, *a, **kw)

    def run(self, val):
        if not val:
            return

        try:
            val = int(val)
            if self.min is not None and val < self.min:
                val = self.min
            elif self.max is not None and val > self.max:
                val = self.max
            return val
        except ValueError:
            self.set_error(errors.BAD_NUMBER)

class VCssName(Validator):
    """
    returns a name iff it consists of alphanumeric characters and
    possibly "-", and is below the length limit.
    """
    r_css_name = re.compile(r"^[a-zA-Z0-9\-]{1,100}$")
    def run(self, name):
        if name and self.r_css_name.match(name):
            return name
    
class VMenu(Validator):

    def __init__(self, param, menu_cls, remember = True, **kw):
        self.nav = menu_cls
        self.remember = remember
        param = (menu_cls.get_param, param)
        Validator.__init__(self, param, **kw)

    def run(self, sort, where):
        if self.remember:
            pref = "%s_%s" % (where, self.nav.get_param)
            user_prefs = copy(c.user.sort_options) if c.user else {}
            user_pref = user_prefs.get(pref)
    
            # check to see if a default param has been set
            if not sort:
                sort = user_pref
            
        # validate the sort
        if sort not in self.nav.options:
            sort = self.nav.default

        # commit the sort if changed
        if self.remember and c.user_is_loggedin and sort != user_pref:
            user_prefs[pref] = sort
            c.user.sort_options = user_prefs
            user = c.user
            utils.worker.do(lambda: user._commit())

        return sort
            

class VRatelimit(Validator):
    def __init__(self, rate_user = False, rate_ip = False,
                 prefix = 'rate_', *a, **kw):
        self.rate_user = rate_user
        self.rate_ip = rate_ip
        self.prefix = prefix
        Validator.__init__(self, *a, **kw)

    def run (self):
        to_check = []
        if self.rate_user and c.user_is_loggedin:
            to_check.append('user' + str(c.user._id36))
        if self.rate_ip:
            to_check.append('ip' + str(request.ip))

        r = g.cache.get_multi(to_check, self.prefix)
        if r:
            expire_time = max(r.values())
            time = utils.timeuntil(expire_time)
            self.set_error(errors.RATELIMIT, {'time': time})

    @classmethod
    def ratelimit(self, rate_user = False, rate_ip = False, prefix = "rate_"):
        to_set = {}
        seconds = g.RATELIMIT*60
        expire_time = datetime.now(g.tz) + timedelta(seconds = seconds)
        if rate_user and c.user_is_loggedin:
            to_set['user' + str(c.user._id36)] = expire_time
        if rate_ip:
            to_set['ip' + str(request.ip)] = expire_time

        g.cache.set_multi(to_set, prefix, time = seconds)

class VCommentIDs(Validator):
    #id_str is a comma separated list of id36's
    def run(self, id_str):
        cids = [int(i, 36) for i in id_str.split(',')]
        comments = Comment._byID(cids, data=True, return_dict = False)
        return comments

class VFullNames(Validator):
    #id_str is a comma separated list of id36's
    def run(self, id_str):
        tids = id_str.split(',')
        return Thing._by_fullname(tids, data=True, return_dict = False)

class VSubreddits(Validator):
    #the subreddits are just in the post, this is for the my.reddit pref page
    def run(self):
        subreddits = Subreddit._by_fullname(request.post.keys())
        return subreddits.values()

class VCacheKey(Validator):
    def __init__(self, cache_prefix, param, *a, **kw):
        self.cache_prefix = cache_prefix
        Validator.__init__(self, param, *a, **kw)

    def run(self, key, name):
        if key:
            uid = g.cache.get(str(self.cache_prefix + "_" + key))
            try:
                a = Account._byID(uid, data = True)
                g.cache.delete(str(self.cache_prefix + "_" + key))
            except NotFound:
                return None
            if name and a.name.lower() != name.lower():
                self.set_error(errors.BAD_USERNAME)
            if a:
                return a
            
        self.set_error(errors.EXPIRED)

class VOneOf(Validator):
    def __init__(self, param, options = (), *a, **kw):
        Validator.__init__(self, param, *a, **kw)
        self.options = options

    def run(self, val):
        if self.options and val not in self.options:
            self.set_error(errors.INVALID_OPTION)
            return self.default
        else:
            return val

class VReason(Validator):
    def run(self, reason):
        if not reason:
            return

        if reason.startswith('redirect_'):
            dest = reason[9:]
            if (not dest.startswith(c.site.path) and 
                not dest.startswith("http:")):
                dest = (c.site.path + dest).replace('//', '/')
            return ('redirect', dest)
        if reason.startswith('vote_'):
            fullname = reason[5:]
            t = Thing._by_fullname(fullname, data=True)
            return ('redirect', t.make_permalink_slow())
        elif reason.startswith('share_'):
            fullname = reason[6:]
            t = Thing._by_fullname(fullname, data=True)
            return ('redirect', t.make_permalink_slow())
        elif reason.startswith('reply_'):
            fullname = reason[6:]
            t = Thing._by_fullname(fullname, data=True)
            return ('redirect', t.make_permalink_slow())
        elif reason.startswith('sr_change_'):
            sr_list = reason[10:].split(',')
            fullnames = dict(i.split(':') for i in sr_list)
            srs = Subreddit._by_fullname(fullnames.keys(), data = True,
                                         return_dict = False)
            sr_onoff = dict((sr, fullnames[sr._fullname] == 1) for sr in srs)
            return ('subscribe', sr_onoff)


class ValidEmails(Validator):
    """Validates a list of email addresses passed in as a string and
    delineated by whitespace, ',' or ';'.  Also validates quantity of
    provided emails.  Returns a list of valid email addresses on
    success"""
    
    separator = re.compile(r'[^\s,;]+')
    email_re  = re.compile(r'.+@.+\..+')

    def __init__(self, param, num = 20, **kw):
        self.num = num
        Validator.__init__(self, param = param, **kw)
        
    def run(self, emails0):
        emails = set(self.separator.findall(emails0) if emails0 else [])
        failures = set(e for e in emails if not self.email_re.match(e))
        emails = emails - failures

        # make sure the number of addresses does not exceed the max
        if self.num > 0 and len(emails) + len(failures) > self.num:
            # special case for 1: there should be no delineators at all, so
            # send back original string to the user
            if self.num == 1:
                self.set_error(errors.BAD_EMAILS,
                             {'emails': '"%s"' % emails0})
            # else report the number expected
            else:
                self.set_error(errors.TOO_MANY_EMAILS,
                             {'num': self.num})
        # correct number, but invalid formatting
        elif failures:
            self.set_error(errors.BAD_EMAILS,
                         {'emails': ', '.join(failures)})
        # no emails
        elif not emails:
            self.set_error(errors.NO_EMAILS)
        else:
            # return single email if one is expected, list otherwise
            return list(emails)[0] if self.num == 1 else emails


class VCnameDomain(Validator):
    domain_re  = re.compile(r'^([\w\-_]+\.)+[\w]+$')

    def run(self, domain):
        if (domain
            and (not self.domain_re.match(domain)
                 or domain.endswith('.reddit.com')
                 or len(domain) > 300)):
            self.set_error(errors.BAD_CNAME)
        elif domain:
            try:
                return str(domain).lower()
            except UnicodeEncodeError:
                self.set_error(errors.BAD_CNAME)

class VTranslation(Validator):
    def run(self):
        from r2.lib.translation import Translator
        if Translator.exists(self.param):
            return Translator(locale = self.param)

# NOTE: make sure *never* to have res check these are present
# otherwise, the response could contain reference to these errors...!
class ValidIP(Validator):
    def run(self):
        if is_banned_IP(request.ip):
            self.set_error(errors.BANNED_IP)
        return request.ip

class ValidDomain(Validator):
    def run(self, url):
        if url and is_banned_domain(url):
            self.set_error(errors.BANNED_DOMAIN)

