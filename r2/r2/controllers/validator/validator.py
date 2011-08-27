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
from pylons import c, request, g
from pylons.i18n import _
from pylons.controllers.util import abort
from r2.lib import utils, captcha, promote
from r2.lib.filters import unkeep_space, websafe, _force_unicode
from r2.lib.filters import markdown_souptest
from r2.lib.db.operators import asc, desc
from r2.lib.template_helpers import add_sr
from r2.lib.jsonresponse import json_respond, JQueryResponse, JsonResponse
from r2.lib.jsontemplates import api_type
from r2.lib.log import log_text
from r2.models import *
from r2.lib.authorize import Address, CreditCard
from r2.lib.utils import constant_time_compare

from r2.controllers.errors import errors, UserRequiredException
from r2.controllers.errors import VerifiedUserRequiredException
from r2.controllers.errors import GoldRequiredException

from copy import copy
from datetime import datetime, timedelta
from curses.ascii import isprint
import re, inspect
import pycountry

def visible_promo(article):
    is_promo = getattr(article, "promoted", None) is not None
    is_author = (c.user_is_loggedin and
                 c.user._id == article.author_id)
    # promos are visible only if comments are not disabled and the
    # user is either the author or the link is live/previously live.
    if is_promo:
        return (is_author or (not article.disable_comments and
                 article.promote_status >= promote.STATUS.promoted))
    # not a promo, therefore it is visible
    return True

def can_view_link_comments(article):
    return (article.subreddit_slow.can_view(c.user) and
            visible_promo(article))

def can_comment_link(article):
    return (article.subreddit_slow.can_comment(c.user) and
            visible_promo(article))

class Validator(object):
    default_param = None
    def __init__(self, param=None, default=None, post=True, get=True, url=True):
        if param:
            self.param = param
        else:
            self.param = self.default_param

        self.default = default
        self.post, self.get, self.url = post, get, url

    def set_error(self, error, msg_params = {}, field = False):
        """
        Adds the provided error to c.errors and flags that it is come
        from the validator's param
        """
        if field is False:
            field = self.param

        c.errors.add(error, msg_params = msg_params, field = field)

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
            except VerifiedUserRequiredException:
                return self.intermediate_redirect('/verify')
        return newfn
    return val


def api_validate(response_type=None):
    """
    Factory for making validators for API calls, since API calls come
    in two flavors: responsive and unresponsive.  The machinary
    associated with both is similar, and the error handling identical,
    so this function abstracts away the kw validation and creation of
    a Json-y responder object.
    """
    def wrap(response_function):
        def _api_validate(*simple_vals, **param_vals):
            def val(fn):
                def newfn(self, *a, **env):
                    c.render_style = api_type(request.params.get("renderstyle",
                                                                 response_type))
                    c.response_content_type = 'application/json; charset=UTF-8'
                    # generate a response object
                    if response_type is None or request.params.get('api_type') == "json":
                        responder = JsonResponse()
                    else:
                        responder = JQueryResponse()
                    try:
                        kw = _make_validated_kw(fn, simple_vals, param_vals, env)
                        return response_function(self, fn, responder,
                                                 simple_vals, param_vals, *a, **kw)
                    except UserRequiredException:
                        responder.send_failure(errors.USER_REQUIRED)
                        return self.api_wrapper(responder.make_response())
                    except VerifiedUserRequiredException:
                        responder.send_failure(errors.VERIFIED_USER_REQUIRED)
                        return self.api_wrapper(responder.make_response())
                return newfn
            return val
        return _api_validate
    return wrap
    

@api_validate("html")
def noresponse(self, self_method, responder, simple_vals, param_vals, *a, **kw):
    self_method(self, *a, **kw)
    return self.api_wrapper({})

@api_validate("html")
def textresponse(self, self_method, responder, simple_vals, param_vals, *a, **kw):
    return self_method(self, *a, **kw)

@api_validate()
def json_validate(self, self_method, responder, simple_vals, param_vals, *a, **kw):
    if c.extension != 'json':
        abort(404)
    r = self_method(self, *a, **kw)
    return self.api_wrapper(r)

@api_validate("html")
def validatedForm(self, self_method, responder, simple_vals, param_vals,
                  *a, **kw):
    # generate a form object
    form = responder(request.POST.get('id', "body"))

    # clear out the status line as a courtesy
    form.set_html(".status", "")

    # auto-refresh the captcha if there are errors.
    if (c.errors.errors and
        any(isinstance(v, VCaptcha) for v in simple_vals)):
        form.has_errors('captcha', errors.BAD_CAPTCHA)
        form.new_captcha()
    
    # do the actual work
    val = self_method(self, form, responder, *a, **kw)

    if val:
        return val
    else:
        return self.api_wrapper(responder.make_response())



#### validators ####
class nop(Validator):
    def run(self, x):
        return x

class VLang(Validator):
    def run(self, lang):
        if lang in g.all_languages:
            return lang
        return g.lang

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

class VThing(Validator):
    def __init__(self, param, thingclass, redirect = True, *a, **kw):
        Validator.__init__(self, param, *a, **kw)
        self.thingclass = thingclass
        self.redirect = redirect

    def run(self, thing_id):
        if thing_id:
            try:
                tid = int(thing_id, 36)
                thing = self.thingclass._byID(tid, True)
                if thing.__class__ != self.thingclass:
                    raise TypeError("Expected %s, got %s" %
                                    (self.thingclass, thing.__class__))
                return thing
            except (NotFound, ValueError):
                if self.redirect:
                    abort(404, 'page not found')
                else:
                    return None

class VLink(VThing):
    def __init__(self, param, redirect = True, *a, **kw):
        VThing.__init__(self, param, Link, redirect=redirect, *a, **kw)

class VCommentByID(VThing):
    def __init__(self, param, redirect = True, *a, **kw):
        VThing.__init__(self, param, Comment, redirect=redirect, *a, **kw)

class VAd(VThing):
    def __init__(self, param, redirect = True, *a, **kw):
        VThing.__init__(self, param, Ad, redirect=redirect, *a, **kw)

class VAdByCodename(Validator):
    def run(self, codename, required_fullname=None):
        if not codename:
            return self.set_error(errors.NO_TEXT)

        try:
            a = Ad._by_codename(codename)
        except NotFound:
            a = None

        if a and required_fullname and a._fullname != required_fullname:
            return self.set_error(errors.INVALID_OPTION)
        else:
            return a

class VAward(VThing):
    def __init__(self, param, redirect = True, *a, **kw):
        VThing.__init__(self, param, Award, redirect=redirect, *a, **kw)

class VAwardByCodename(Validator):
    def run(self, codename, required_fullname=None):
        if not codename:
            return self.set_error(errors.NO_TEXT)

        try:
            a = Award._by_codename(codename)
        except NotFound:
            a = None

        if a and required_fullname and a._fullname != required_fullname:
            return self.set_error(errors.INVALID_OPTION)
        else:
            return a

class VTrophy(VThing):
    def __init__(self, param, redirect = True, *a, **kw):
        VThing.__init__(self, param, Trophy, redirect=redirect, *a, **kw)

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

class VMessageID(Validator):
    def run(self, cid):
        if cid:
            try:
                cid = int(cid, 36)
                m = Message._byID(cid, True)
                if not m.can_view_slow():
                    abort(403, 'forbidden')
                return m
            except (NotFound, ValueError):
                pass

class VCount(Validator):
    def run(self, count):
        if count is None:
            count = 0
        try:
            return max(int(count), 0)
        except ValueError:
            return 0


class VLimit(Validator):
    def __init__(self, param, default=25, max_limit=100, **kw):
        self.default_limit = default
        self.max_limit = max_limit
        Validator.__init__(self, param, **kw)

    def run(self, limit):
        default = c.user.pref_numsites
        if c.render_style in ("compact", api_type("compact")):
            default = self.default_limit  # TODO: ini param?

        if limit is None:
            return default

        try:
            i = int(limit)
        except ValueError:
            return default

        return min(max(i, 1), self.max_limit)

class VCssMeasure(Validator):
    measure = re.compile(r"\A\s*[\d\.]+\w{0,3}\s*\Z")
    def run(self, value):
        return value if value and self.measure.match(value) else ''

subreddit_rx = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_]{2,20}\Z")

def chksrname(x):
    #notice the space before reddit.com
    if x in ('friends', 'all', ' reddit.com'):
        return False

    try:
        return str(x) if x and subreddit_rx.match(x) else None
    except UnicodeEncodeError:
        return None


class VLength(Validator):
    only_whitespace = re.compile(r"\A\s*\Z", re.UNICODE)

    def __init__(self, param, max_length,
                 empty_error = errors.NO_TEXT,
                 length_error = errors.TOO_LONG,
                 **kw):
        Validator.__init__(self, param, **kw)
        self.max_length = max_length
        self.length_error = length_error
        self.empty_error = empty_error

    def run(self, text, text2 = ''):
        text = text or text2
        if self.empty_error and (not text or self.only_whitespace.match(text)):
            self.set_error(self.empty_error)
        elif len(text) > self.max_length:
            self.set_error(self.length_error, {'max_length': self.max_length})
        else:
            return text

class VPrintable(VLength):
    def run(self, text, text2 = ''):
        text = VLength.run(self, text, text2)

        if text is None:
            return None

        try:
            if all(isprint(str(x)) for x in text):
                return str(text)
        except UnicodeEncodeError:
            pass

        self.set_error(errors.BAD_STRING)
        return None


class VTitle(VLength):
    def __init__(self, param, max_length = 300, **kw):
        VLength.__init__(self, param, max_length, **kw)

class VMarkdown(VLength):
    def __init__(self, param, max_length = 10000, **kw):
        VLength.__init__(self, param, max_length, **kw)

    def run(self, text, text2 = ''):
        text = text or text2
        VLength.run(self, text)
        try:
            markdown_souptest(text)
            return text
        except ValueError:
            import sys
            user = "???"
            if c.user_is_loggedin:
                user = c.user.name
            g.log.error("HAX by %s: %s" % (user, text))
            s = sys.exc_info()
            # reraise the original error with the original stack trace
            raise s[1], None, s[2]

class VSelfText(VMarkdown):

    def set_max_length(self, val):
        self._max_length = val

    def get_max_length(self):
        if c.site.link_type == "self":
            return self._max_length * 3
        return self._max_length

    max_length = property(get_max_length, set_max_length)

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

def fullname_regex(thing_cls = None, multiple = False):
    pattern = "[%s%s]" % (Relation._type_prefix, Thing._type_prefix)
    if thing_cls:
        pattern += utils.to36(thing_cls._type_id)
    else:
        pattern += r"[0-9a-z]+"
    pattern += r"_[0-9a-z]+"
    if multiple:
        pattern = r"(%s *,? *)+" % pattern
    return re.compile(r"\A" + pattern + r"\Z")

class VByName(Validator):
    splitter = re.compile('[ ,]+')
    def __init__(self, param, thing_cls = None, multiple = False,
                 error = errors.NO_THING_ID, **kw):
        self.re = fullname_regex(thing_cls)
        self.multiple = multiple
        self._error = error
        
        Validator.__init__(self, param, **kw)
    
    def run(self, items):
        if items and self.multiple:
            items = [item for item in self.splitter.split(items)
                     if item and self.re.match(item)]
        if items and (self.multiple or self.re.match(items)):
            try:
                return Thing._by_fullname(items, return_dict = False,
                                          data=True)
            except NotFound:
                pass
        return self.set_error(self._error)

class VByNameIfAuthor(VByName):
    def run(self, fullname):
        thing = VByName.run(self, fullname)
        if thing:
            if not thing._loaded: thing._load()
            if c.user_is_loggedin and thing.author_id == c.user._id:
                return thing
        return self.set_error(errors.NOT_AUTHOR)

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

class VAdminOrAdminSecret(VAdmin):
    def run(self, secret):
        if secret and constant_time_compare(secret, g.ADMINSECRET):
            return
        super(VAdminOrAdminSecret, self).run()

class VVerifiedUser(VUser):
    def run(self):
        VUser.run(self)
        if not c.user.email_verified:
            raise VerifiedUserRequiredException

class VGold(VUser):
    def run(self):
        VUser.run(self)
        if not c.user.gold:
            raise GoldRequiredException

class VSponsorAdmin(VVerifiedUser):
    """
    Validator which checks c.user_is_sponsor
    """
    def user_test(self, thing):
        return (thing.author_id == c.user._id)

    def run(self, link_id = None):
        VVerifiedUser.run(self)
        if c.user_is_sponsor:
            return
        abort(403, 'forbidden')

class VSponsor(VVerifiedUser):
    """
    Not intended to be used as a check for c.user_is_sponsor, but
    rather is the user allowed to use the sponsored link system and,
    if there is a link passed in, is the user allowed to edit the link
    in question.
    """
    def user_test(self, thing):
        return (thing.author_id == c.user._id)

    def run(self, link_id = None):
        VVerifiedUser.run(self)
        if c.user_is_sponsor:
            return
        elif link_id:
            try:
                if '_' in link_id:
                    t = Link._by_fullname(link_id, True)
                else:
                    aid = int(link_id, 36)
                    t = Link._byID(aid, True)
                if self.user_test(t):
                    return
            except (NotFound, ValueError):
                pass
            abort(403, 'forbidden')

class VTrafficViewer(VSponsor):
    def user_test(self, thing):
        return (VSponsor.user_test(self, thing) or
                promote.is_traffic_viewer(thing, c.user))

class VSrModerator(Validator):
    def run(self):
        if not (c.user_is_loggedin and c.site.is_moderator(c.user) 
                or c.user_is_admin):
            abort(403, "forbidden")

class VFlairManager(VSrModerator):
    """Validates that a user is permitted to manage flair for a subreddit.
       
    Currently this is the same as VSrModerator. It's a separate class to act as
    a placeholder if we ever need to give mods a way to delegate this aspect of
    subreddit administration."""
    pass

class VCanDistinguish(VByName):
    def run(self, thing_name, how):
        if c.user_is_admin:
            return True
        elif c.user_is_loggedin:
            item = VByName.run(self, thing_name)
            if item.author_id == c.user._id:
                # will throw a legitimate 500 if this isn't a link or
                # comment, because this should only be used on links and
                # comments
                subreddit = item.subreddit_slow
                if how in ("yes", "no") and subreddit.can_distinguish(c.user):
                    return True
                elif how in ("special", "no") and c.user_special_distinguish:
                    return True

        abort(403,'forbidden')

class VSrCanAlter(VByName):
    def run(self, thing_name):
        if c.user_is_admin:
            return True
        elif c.user_is_loggedin:
            item = VByName.run(self, thing_name)
            if item.author_id == c.user._id:
                return True
            else:
                # will throw a legitimate 500 if this isn't a link or
                # comment, because this should only be used on links and
                # comments
                subreddit = item.subreddit_slow
                if subreddit.can_distinguish(c.user):
                    return True
        abort(403,'forbidden')

class VSrCanBan(VByName):
    def run(self, thing_name):
        if c.user_is_admin:
            return 'admin'
        elif c.user_is_loggedin:
            item = VByName.run(self, thing_name)
            # will throw a legitimate 500 if this isn't a link or
            # comment, because this should only be used on links and
            # comments
            subreddit = item.subreddit_slow
            if subreddit.is_moderator(c.user):
                return 'mod'
            # elif subreddit.is_contributor(c.user):
            #     return 'contributor'
        abort(403,'forbidden')

class VSrSpecial(VByName):
    def run(self, thing_name):
        if c.user_is_admin:
            return True
        elif c.user_is_loggedin:
            item = VByName.run(self, thing_name)
            # will throw a legitimate 500 if this isn't a link or
            # comment, because this should only be used on links and
            # comments
            subreddit = item.subreddit_slow
            if subreddit.is_special(c.user):
                return True
        abort(403,'forbidden')


class VSubmitParent(VByName):
    def run(self, fullname, fullname2):
        #for backwards compatability (with iphone app)
        fullname = fullname or fullname2
        if fullname:
            parent = VByName.run(self, fullname)
            if parent:
                if c.user_is_loggedin and parent.author_id in c.user.enemies:
                    self.set_error(errors.USER_BLOCKED)
                if parent._deleted:
                    if isinstance(parent, Link):
                        self.set_error(errors.DELETED_LINK)
                    else:
                        self.set_error(errors.DELETED_COMMENT)
            if isinstance(parent, Message):
                return parent
            else:
                link = parent
                if isinstance(parent, Comment):
                    link = Link._byID(parent.link_id, data=True)
                if c.user_is_loggedin and can_comment_link(link):
                    return parent
        #else
        abort(403, "forbidden")

class VSubmitSR(Validator):
    def __init__(self, srname_param, linktype_param = None):
        self.require_linktype = False

        if linktype_param:
            self.require_linktype = True
            Validator.__init__(self, (srname_param, linktype_param))
        else:
            Validator.__init__(self, srname_param)

    def run(self, sr_name, link_type = None):
        if not sr_name:
            self.set_error(errors.SUBREDDIT_REQUIRED)
            return None

        try:
            sr = Subreddit._by_name(str(sr_name).strip())
        except (NotFound, AttributeError, UnicodeEncodeError):
            self.set_error(errors.SUBREDDIT_NOEXIST)
            return

        if not c.user_is_loggedin or not sr.can_submit(c.user):
            self.set_error(errors.SUBREDDIT_NOTALLOWED)
            return

        if self.require_linktype:
            if link_type not in ('link', 'self'):
                self.set_error(errors.INVALID_OPTION)
                return
            elif link_type == 'link' and sr.link_type == 'self':
                self.set_error(errors.NO_LINKS)
                return
            elif link_type == 'self' and sr.link_type == 'link':
                self.set_error(errors.NO_SELFS)
                return

        return sr

pass_rx = re.compile(r"\A.{3,20}\Z")

def chkpass(x):
    return x if x and pass_rx.match(x) else None

class VPassword(Validator):
    def run(self, password, verify):
        if not chkpass(password):
            self.set_error(errors.BAD_PASSWORD)
        elif verify != password:
            self.set_error(errors.BAD_PASSWORD_MATCH)
        else:
            return password.encode('utf8')

user_rx = re.compile(r"\A[\w-]{3,20}\Z", re.UNICODE)

def chkuser(x):
    if x is None:
        return None
    try:
        if any(ch.isspace() for ch in x):
            return None
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
                if a._deleted:
                   return self.error(errors.USERNAME_TAKEN_DEL)
                else:
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
            try:
                str(password)
            except UnicodeEncodeError:
                password = password.encode('utf8')
            user = valid_login(user_name, password)
        if not user:
            return self.error()
        return user


class VSanitizedUrl(Validator):
    def run(self, url):
        return utils.sanitize_url(url)

class VUrl(VRequired):
    def __init__(self, item, allow_self = True, lookup = True, *a, **kw):
        self.allow_self = allow_self
        self.lookup = lookup
        VRequired.__init__(self, item, errors.NO_URL, *a, **kw)

    def run(self, url, sr = None):
        if sr is None and not isinstance(c.site, FakeSubreddit):
            sr = c.site
        elif sr:
            try:
                sr = Subreddit._by_name(str(sr))
            except (NotFound, UnicodeEncodeError):
                self.set_error(errors.SUBREDDIT_NOEXIST)
                sr = None
        else:
            sr = None

        if not url:
            return self.error(errors.NO_URL)
        url = utils.sanitize_url(url)
        if not url:
            return self.error(errors.BAD_URL)

        if url == 'self':
            if self.allow_self:
                return url
        elif not self.lookup:
            return url
        elif url:
            try:
                l = Link._by_url(url, sr)
                self.error(errors.ALREADY_SUB)
                return utils.tup(l)
            except NotFound:
                return url
        return self.error(errors.BAD_URL)

class VOptionalExistingUname(VRequired):
    def __init__(self, item, allow_deleted=False, *a, **kw):
        self.allow_deleted = allow_deleted
        VRequired.__init__(self, item, errors.NO_USER, *a, **kw)

    def run(self, name):
        if name and name.startswith('~') and c.user_is_admin:
            try:
                user_id = int(name[1:])
                return Account._byID(user_id, True)
            except (NotFound, ValueError):
                return self.error(errors.USER_DOESNT_EXIST)

        # make sure the name satisfies our user name regexp before
        # bothering to look it up.
        name = chkuser(name)
        if name:
            try:
                return Account._by_name(name, allow_deleted=self.allow_deleted)
            except NotFound:
                return self.error(errors.USER_DOESNT_EXIST)

class VExistingUname(VOptionalExistingUname):
    def run(self, name):
        user = VOptionalExistingUname.run(self, name)
        if not user:
            self.error()
        return user

class VMessageRecipient(VExistingUname):
    def run(self, name):
        if not name:
            return self.error()
        if name.startswith('#'):
            try:
                s = Subreddit._by_name(name.strip('#'))
                if isinstance(s, FakeSubreddit):
                    raise NotFound, "fake subreddit"
                if s._spam:
                    raise NotFound, "banned community"
                return s
            except NotFound:
                self.set_error(errors.SUBREDDIT_NOEXIST)
        else:
            account = VExistingUname.run(self, name)
            if account and account._id in c.user.enemies:
                self.set_error(errors.USER_BLOCKED)
            else:
                return account

class VUserWithEmail(VExistingUname):
    def run(self, name):
        user = VExistingUname.run(self, name)
        if not user or not hasattr(user, 'email') or not user.email:
            return self.error(errors.NO_EMAIL_FOR_USER)
        return user


class VBoolean(Validator):
    def run(self, val):
        lv = str(val).lower()
        if lv == 'off' or lv == '' or lv[0] in ("f", "n"):
            return False
        return bool(val)

class VNumber(Validator):
    def __init__(self, param, min=None, max=None, coerce = True,
                 error = errors.BAD_NUMBER, *a, **kw):
        self.min = self.cast(min) if min is not None else None
        self.max = self.cast(max) if max is not None else None
        self.coerce = coerce
        self.error = error
        Validator.__init__(self, param, *a, **kw)

    def cast(self, val):
        raise NotImplementedError

    def run(self, val):
        if not val:
            return
        try:
            val = self.cast(val)
            if self.min is not None and val < self.min:
                if self.coerce:
                    val = self.min
                else:
                    raise ValueError, ""
            elif self.max is not None and val > self.max:
                if self.coerce:
                    val = self.max
                else:
                    raise ValueError, ""
            return val
        except ValueError:
            self.set_error(self.error, msg_params = dict(min=self.min,
                                                         max=self.max))

class VInt(VNumber):
    def cast(self, val):
        return int(val)

class VFloat(VNumber):
    def cast(self, val):
        return float(val)

class VBid(VNumber):
    def __init__(self, bid, link_id, sr):
        self.duration = 1
        VNumber.__init__(self, (bid, link_id, sr),
                         # targeting is a little more expensive
                         min = g.min_promote_bid,
                         max = g.max_promote_bid, coerce = False,
                         error = errors.BAD_BID)

    def cast(self, val):
        return float(val)/self.duration

    def run(self, bid, link_id, sr = None):
        if link_id:
            try:
                link = Thing._by_fullname(link_id, return_dict = False,
                                          data=True)
                self.duration = max((link.promote_until - link._date).days, 1)
            except NotFound:
                pass
        if VNumber.run(self, bid):
            if sr:
                if self.cast(bid) >= self.min * 1.5:
                    return float(bid)
                else:
                    self.set_error(self.error, msg_params = dict(min=self.min * 1.5,
                                                                 max=self.max))
            else:
                return float(bid)


class VCssName(Validator):
    """
    returns a name iff it consists of alphanumeric characters and
    possibly "-", and is below the length limit.
    """

    r_css_name = re.compile(r"\A[a-zA-Z0-9\-]{1,100}\Z")

    def run(self, name):
        if name:
            if self.r_css_name.match(name):
                return name
            else:
                self.set_error(errors.BAD_CSS_NAME)
        return ''


class VMenu(Validator):

    def __init__(self, param, menu_cls, remember = True, **kw):
        self.nav = menu_cls
        self.remember = remember
        param = (menu_cls.name, param)
        Validator.__init__(self, param, **kw)

    def run(self, sort, where):
        if self.remember:
            pref = "%s_%s" % (where, self.nav.name)
            user_prefs = copy(c.user.sort_options) if c.user else {}
            user_pref = user_prefs.get(pref)

            # check to see if a default param has been set
            if not sort:
                sort = user_pref

        # validate the sort
        if sort not in self.nav.options:
            sort = self.nav.default

        # commit the sort if changed and if this is a POST request
        if (self.remember and c.user_is_loggedin and sort != user_pref
            and request.method.upper() == 'POST'):
            user_prefs[pref] = sort
            c.user.sort_options = user_prefs
            user = c.user
            user._commit()

        return sort


class VRatelimit(Validator):
    def __init__(self, rate_user = False, rate_ip = False,
                 prefix = 'rate_', error = errors.RATELIMIT, *a, **kw):
        self.rate_user = rate_user
        self.rate_ip = rate_ip
        self.prefix = prefix
        self.error = error
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

            g.log.debug("rate-limiting %s from %s" % (self.prefix, r.keys()))

            # when errors have associated field parameters, we'll need
            # to add that here
            if self.error == errors.RATELIMIT:
                self.set_error(errors.RATELIMIT, {'time': time},
                               field = 'ratelimit')
            else:
                self.set_error(self.error)

    @classmethod
    def ratelimit(self, rate_user = False, rate_ip = False, prefix = "rate_",
                  seconds = None):
        to_set = {}
        if seconds is None:
            seconds = g.RATELIMIT*60
        expire_time = datetime.now(g.tz) + timedelta(seconds = seconds)
        if rate_user and c.user_is_loggedin:
            to_set['user' + str(c.user._id36)] = expire_time
        if rate_ip:
            to_set['ip' + str(request.ip)] = expire_time
        g.cache.set_multi(to_set, prefix = prefix, time = seconds)

class VDelay(Validator):
    def __init__(self, category, *a, **kw):
        self.category = category
        Validator.__init__(self, *a, **kw)

    def run (self):
        key = "VDelay-%s-%s" % (self.category, request.ip)
        prev_violations = g.cache.get(key)
        if prev_violations:
            time = utils.timeuntil(prev_violations["expire_time"])
            if prev_violations["expire_time"] > datetime.now(g.tz):
                self.set_error(errors.RATELIMIT, {'time': time},
                               field='vdelay')

    @classmethod
    def record_violation(self, category, seconds = None, growfast=False):
        if seconds is None:
            seconds = g.RATELIMIT*60

        key = "VDelay-%s-%s" % (category, request.ip)
        prev_violations = g.memcache.get(key)
        if prev_violations is None:
            prev_violations = dict(count=0)

        num_violations = prev_violations["count"]

        if growfast:
            multiplier = 3 ** num_violations
        else:
            multiplier = 1

        max_duration = 8 * 3600
        duration = min(seconds * multiplier, max_duration)

        expire_time = (datetime.now(g.tz) +
                       timedelta(seconds = duration))

        prev_violations["expire_time"] = expire_time
        prev_violations["duration"] = duration
        prev_violations["count"] += 1

        with g.make_lock("lock-" + key, timeout=5, verbose=False):
            existing = g.memcache.get(key)
            if existing and existing["count"] > prev_violations["count"]:
                g.log.warning("Tried to set %s to count=%d, but found existing=%d"
                             % (key, prev_violations["count"], existing["count"]))
            else:
                g.cache.set(key, prev_violations, max_duration)

class VCommentIDs(Validator):
    #id_str is a comma separated list of id36's
    def run(self, id_str):
        if id_str:
            cids = [int(i, 36) for i in id_str.split(',')]
            comments = Comment._byID(cids, data=True, return_dict = False)
            return comments
        return []


class CachedUser(object):
    def __init__(self, cache_prefix, user, key):
        self.cache_prefix = cache_prefix
        self.user = user
        self.key = key

    def clear(self):
        if self.key and self.cache_prefix:
            g.cache.delete(str(self.cache_prefix + "_" + self.key))


class VCacheKey(Validator):
    def __init__(self, cache_prefix, param, *a, **kw):
        self.cache = g.cache
        self.cache_prefix = cache_prefix
        Validator.__init__(self, param, *a, **kw)

    def run(self, key):
        c_user = CachedUser(self.cache_prefix, None, key)
        if key:
            uid = self.cache.get(str(self.cache_prefix + "_" + key))
            if uid:
                try:
                    c_user.user = Account._byID(uid, data = True)
                except NotFound:
                    return
            return c_user
        self.set_error(errors.EXPIRED)

class VHardCacheKey(VCacheKey):
    def __init__(self, cache_prefix, param, *a, **kw):
        VCacheKey.__init__(self, cache_prefix, param, *a, **kw)
        self.cache = g.hardcache

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
    domain_re  = re.compile(r'\A([\w\-_]+\.)+[\w]+\Z')

    def run(self, domain):
        if (domain
            and (not self.domain_re.match(domain)
                 or domain.endswith('.' + g.domain)
                 or domain.endswith('.' + g.media_domain)
                 or len(domain) > 300)):
            self.set_error(errors.BAD_CNAME)
        elif domain:
            try:
                return str(domain).lower()
            except UnicodeEncodeError:
                self.set_error(errors.BAD_CNAME)

class VTranslation(Validator):
    def run(self, param):
        from r2.lib.translation import Translator
        if Translator.exists(param):
            return Translator(locale = param)

# NOTE: make sure *never* to have res check these are present
# otherwise, the response could contain reference to these errors...!
class ValidIP(Validator):
    def run(self):
        if is_banned_IP(request.ip):
            self.set_error(errors.BANNED_IP)
        return request.ip

class VDate(Validator):
    """
    Date checker that accepts string inputs in %m/%d/%Y format.

    Optional parameters include 'past' and 'future' which specify how
    far (in days) into the past or future the date must be to be
    acceptable.

    NOTE: the 'future' param will have precidence during evaluation.

    Error conditions:
       * BAD_DATE on mal-formed date strings (strptime parse failure)
       * BAD_FUTURE_DATE and BAD_PAST_DATE on respective range errors.
    
    """
    def __init__(self, param, future=None, past = None,
                 admin_override = False,
                 reference_date = lambda : datetime.now(g.tz), 
                 business_days = False):
        self.future = future
        self.past   = past

        # are weekends to be exluded from the interval?
        self.business_days = business_days

        # function for generating "now"
        self.reference_date = reference_date

        # do we let admins override date range checking?
        self.override = admin_override
        Validator.__init__(self, param)

    def run(self, date):
        now = self.reference_date()
        override = c.user_is_sponsor and self.override
        try:
            date = datetime.strptime(date, "%m/%d/%Y")
            if not override:
                # can't put in __init__ since we need the date on the fly
                future = utils.make_offset_date(now, self.future,
                                          business_days = self.business_days)
                past = utils.make_offset_date(now, self.past, future = False,
                                          business_days = self.business_days)
                if self.future is not None and date.date() < future.date():
                    self.set_error(errors.BAD_FUTURE_DATE,
                               {"day": self.future})
                elif self.past is not None and date.date() > past.date():
                    self.set_error(errors.BAD_PAST_DATE,
                                   {"day": self.past})
            return date.replace(tzinfo=g.tz)
        except (ValueError, TypeError):
            self.set_error(errors.BAD_DATE)

class VDateRange(VDate):
    """
    Adds range validation to VDate.  In addition to satisfying
    future/past requirements in VDate, two date fields must be
    provided and they must be in order.

    Additional Error conditions:
      * BAD_DATE_RANGE if start_date is not less than end_date
    """
    def run(self, *a):
        try:
            start_date, end_date = [VDate.run(self, x) for x in a]
            if not start_date or not end_date or end_date < start_date:
                self.set_error(errors.BAD_DATE_RANGE)
            return (start_date, end_date)
        except ValueError:
            # insufficient number of arguments provided (expect 2)
            self.set_error(errors.BAD_DATE_RANGE)


class VDestination(Validator):
    def __init__(self, param = 'dest', default = "", **kw):
        self.default = default
        Validator.__init__(self, param, **kw)

    def run(self, dest):
        if not dest:
            dest = request.referer or self.default or "/"

        ld = dest.lower()
        if (ld.startswith("/") or
            ld.startswith("http://") or
            ld.startswith("https://")):

            u = UrlParser(dest)

            if u.is_reddit_url():
                return dest

        ip = getattr(request, "ip", "[unknown]")
        fp = getattr(request, "fullpath", "[unknown]")
        dm = c.domain or "[unknown]"
        cn = c.cname or "[unknown]"

        log_text("invalid redirect",
                 "%s attempted to redirect from %s to %s with domain %s and cname %s"
                      % (ip, fp, dest, dm, cn),
                 "info")

        return "/"

class ValidAddress(Validator):
    def __init__(self, param, allowed_countries = ["United States"]):
        self.allowed_countries = allowed_countries
        Validator.__init__(self, param)

    def set_error(self, msg, field):
        Validator.set_error(self, errors.BAD_ADDRESS,
                            dict(message=msg), field = field)

    def run(self, firstName, lastName, company, address,
            city, state, zipCode, country, phoneNumber):
        if not firstName:
            self.set_error(_("please provide a first name"), "firstName")
        elif not lastName:
            self.set_error(_("please provide a last name"), "lastName")
        elif not address:
            self.set_error(_("please provide an address"), "address")
        elif not city: 
            self.set_error(_("please provide your city"), "city")
        elif not state: 
            self.set_error(_("please provide your state"), "state")
        elif not zipCode:
            self.set_error(_("please provide your zip or post code"), "zip")
        elif not country:
            self.set_error(_("please pick a country"), "country")
        else:
            country = pycountry.countries.get(alpha2=country)
            if country.name not in self.allowed_countries:
                self.set_error(_("Our ToS don't cover your country (yet). Sorry."), "country")
            return Address(firstName = firstName,
                           lastName = lastName,
                           company = company or "",
                           address = address,
                           city = city, state = state,
                           zip = zipCode, country = country.name,
                           phoneNumber = phoneNumber or "")

class ValidCard(Validator):
    valid_ccn  = re.compile(r"\d{13,16}")
    valid_date = re.compile(r"\d\d\d\d-\d\d")
    valid_ccv  = re.compile(r"\d{3,4}")
    def set_error(self, msg, field):
        Validator.set_error(self, errors.BAD_CARD,
                            dict(message=msg), field = field)

    def run(self, cardNumber, expirationDate, cardCode):
        if not self.valid_ccn.match(cardNumber or ""):
            self.set_error(_("credit card numbers should be 13 to 16 digits"),
                           "cardNumber")
        elif not self.valid_date.match(expirationDate or ""):
            self.set_error(_("dates should be YYYY-MM"), "expirationDate")
        elif not self.valid_ccv.match(cardCode or ""):
            self.set_error(_("card verification codes should be 3 or 4 digits"),
                           "cardCode")
        else:
            return CreditCard(cardNumber = cardNumber,
                              expirationDate = expirationDate,
                              cardCode = cardCode)

class VTarget(Validator):
    target_re = re.compile("\A[\w_-]{3,20}\Z")
    def run(self, name):
        if name and self.target_re.match(name):
            return name

class VFlairCss(VCssName):
    def __init__(self, param, max_css_classes=10, **kw):
        self.max_css_classes = max_css_classes
        VCssName.__init__(self, param, **kw)

    def run(self, css):
        if not css:
            return css

        names = css.split()
        if len(names) > self.max_css_classes:
            self.set_error(errors.TOO_MUCH_FLAIR_CSS)
            return ''

        for name in names:
            if not self.r_css_name.match(name):
                self.set_error(errors.BAD_CSS_NAME)
                return ''

        return css


class VFlairText(VLength):
    def __init__(self, param, max_length=64, **kw):
        VLength.__init__(self, param, max_length, **kw)

