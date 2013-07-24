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

import json

from pylons import c, g, request, response
from pylons.i18n import _
from pylons.controllers.util import abort
from r2.config.extensions import api_type
from r2.lib import utils, captcha, promote, totp
from r2.lib.filters import unkeep_space, websafe, _force_unicode
from r2.lib.filters import markdown_souptest
from r2.lib.db import tdb_cassandra
from r2.lib.db.operators import asc, desc
from r2.lib.template_helpers import add_sr
from r2.lib.jsonresponse import JQueryResponse, JsonResponse
from r2.lib.log import log_text
from r2.lib.permissions import ModeratorPermissionSet
from r2.models import *
from r2.lib.authorize import Address, CreditCard
from r2.lib.utils import constant_time_compare
from r2.lib.require import require, require_split, RequirementException

from r2.lib.errors import errors, RedditError, UserRequiredException
from r2.lib.errors import VerifiedUserRequiredException

from copy import copy
from datetime import datetime, timedelta
from curses.ascii import isprint
import re, inspect
from itertools import chain
from functools import wraps

def visible_promo(article):
    is_promo = getattr(article, "promoted", None) is not None
    is_author = (c.user_is_loggedin and
                 c.user._id == article.author_id)

    # subreddit discovery links are visible even without a live campaign
    if article._fullname in g.live_config['sr_discovery_links']:
        return True

    # promos are visible only if comments are not disabled and the
    # user is either the author or the link is live/previously live.
    if is_promo:
        return (c.user_is_sponsor or
                is_author or
                (not article.disable_comments and
                 article.promote_status >= PROMOTE_STATUS.promoted))
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
    def __init__(self, param=None, default=None, post=True, get=True, url=True,
                 docs=None):
        if param:
            self.param = param
        else:
            self.param = self.default_param

        self.default = default
        self.post, self.get, self.url, self.docs = post, get, url, docs
        self.has_errors = False

    def set_error(self, error, msg_params={}, field=False, code=None):
        """
        Adds the provided error to c.errors and flags that it is come
        from the validator's param
        """
        if field is False:
            field = self.param

        c.errors.add(error, msg_params=msg_params, field=field, code=code)
        self.has_errors = True

    def param_docs(self):
        param_info = {}
        for param in filter(None, tup(self.param)):
            param_info[param] = None
        return param_info

    def __call__(self, url):
        self.has_errors = False
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
        try:
            return self.run(*a)
        except TypeError, e:
            if str(e).startswith('run() takes'):
                # Prepend our class name so we know *which* run()
                raise TypeError('%s.%s' % (type(self).__name__, str(e)))
            else:
                raise


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

def set_api_docs(fn, simple_vals, param_vals, extra_vals=None):
    doc = fn._api_doc = getattr(fn, '_api_doc', {})
    param_info = doc.get('parameters', {})
    for validator in chain(simple_vals, param_vals.itervalues()):
        param_docs = validator.param_docs()
        if validator.docs:
            param_docs.update(validator.docs)
        param_info.update(param_docs)
    if extra_vals:
        param_info.update(extra_vals)
    doc['parameters'] = param_info


def validate(*simple_vals, **param_vals):
    """Validation decorator that delegates error handling to the controller.

    Runs the validators specified and calls self.on_validation_error to
    process each error. This allows controllers to define their own fatal
    error processing logic.
    """
    def val(fn):
        @wraps(fn)
        def newfn(self, *a, **env):
            try:
                kw = _make_validated_kw(fn, simple_vals, param_vals, env)
            except RedditError as err:
                self.on_validation_error(err)

            for err in c.errors:
                self.on_validation_error(c.errors[err])

            try:
                return fn(self, *a, **kw)
            except RedditError as err:
                self.on_validation_error(err)

        set_api_docs(newfn, simple_vals, param_vals)
        return newfn
    return val


def api_validate(response_type=None, add_api_type_doc=False):
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
                @wraps(fn)
                def newfn(self, *a, **env):
                    renderstyle = request.params.get("renderstyle")
                    if renderstyle:
                        c.render_style = api_type(renderstyle)
                    elif not c.extension:
                        # if the request URL included an extension, don't
                        # touch the render_style, since it was already set by
                        # set_extension. if no extension was provided, default
                        # to response_type.
                        c.render_style = api_type(response_type)

                    # generate a response object
                    if response_type == "html" and not request.params.get('api_type') == "json":
                        responder = JQueryResponse()
                    else:
                        responder = JsonResponse()

                    response.content_type = responder.content_type

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

                extra_param_vals = {}
                if add_api_type_doc:
                    extra_param_vals = {
                        "api_type": "the string `json`",
                    }

                set_api_docs(newfn, simple_vals, param_vals, extra_param_vals)
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

    val = self_method(self, responder, *a, **kw)
    if val is None:
        val = responder.make_response()
    return self.api_wrapper(val)

def _validatedForm(self, self_method, responder, simple_vals, param_vals,
                  *a, **kw):
    # generate a form object
    form = responder(request.POST.get('id', "body"))

    # clear out the status line as a courtesy
    form.set_html(".status", "")

    # do the actual work
    val = self_method(self, form, responder, *a, **kw)

    # add data to the output on some errors
    for validator in simple_vals:
        if (isinstance(validator, VCaptcha) and
            (form.has_errors('captcha', errors.BAD_CAPTCHA) or
             (form.has_error() and c.user.needs_captcha()))):
            form.new_captcha()
        elif (isinstance(validator, VRatelimit) and
              form.has_errors('ratelimit', errors.RATELIMIT)):
            form.ratelimit(validator.seconds)

    if val:
        return val
    else:
        return self.api_wrapper(responder.make_response())

@api_validate("html", add_api_type_doc=True)
def validatedForm(self, self_method, responder, simple_vals, param_vals,
                  *a, **kw):
    return _validatedForm(self, self_method, responder, simple_vals, param_vals,
                          *a, **kw)

@api_validate("html", add_api_type_doc=True)
def validatedMultipartForm(self, self_method, responder, simple_vals,
                           param_vals, *a, **kw):
    def wrapped_self_method(*a, **kw):
        val = self_method(*a, **kw)
        if val:
            return val
        else:
            data = json.dumps(responder.make_response())
            response.content_type = "text/html"
            return ('<html><head><script type="text/javascript">\n'
                    'parent.$.handleResponse().call('
                    'parent.$("#" + window.frameElement.id).parent(), %s)\n'
                    '</script></head></html>') % filters.websafe_json(data)
    return _validatedForm(self, wrapped_self_method, responder, simple_vals,
                          param_vals, *a, **kw)


jsonp_callback_rx = re.compile(r"""\A[\w$\."'[\]]+\Z""")
def valid_jsonp_callback(callback):
    return jsonp_callback_rx.match(callback)


#### validators ####
class nop(Validator):
    def run(self, x):
        return x

class VLang(Validator):
    @staticmethod
    def validate_lang(lang, strict=False):
        if lang in g.all_languages:
            return lang
        else:
            if not strict:
                return g.lang
            else:
                raise ValueError("invalid language %r" % lang)

    @staticmethod
    def validate_content_langs(langs):
        if langs == "all":
            return langs

        validated = []
        for lang in langs:
            try:
                validated.append(VLang.validate_lang(lang, strict=True))
            except ValueError:
                pass

        if not validated:
            raise ValueError("no valid languages")

        return validated

    def run(self, lang):
        return VLang.validate_lang(lang)

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

class VPromoCampaign(VThing):
    def __init__(self, param, redirect = True, *a, **kw):
        VThing.__init__(self, param, PromoCampaign, *a, **kw)

class VCommentByID(VThing):
    def __init__(self, param, redirect = True, *a, **kw):
        VThing.__init__(self, param, Comment, redirect=redirect, *a, **kw)


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

    def param_docs(self):
        return {
            self.param: "the maximum number of items desired "
                        "(default: %d, maximum: %d)" % (self.default_limit,
                                                        self.max_limit),
        }

class VCssMeasure(Validator):
    measure = re.compile(r"\A\s*[\d\.]+\w{0,3}\s*\Z")
    def run(self, value):
        return value if value and self.measure.match(value) else ''

subreddit_rx = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_]{2,20}\Z")
language_subreddit_rx = re.compile(r"\A[a-z]{2}\Z")

def chksrname(x, allow_language_srs=False):
    if not x:
        return None

    #notice the space before reddit.com
    if x in ('friends', 'all', ' reddit.com'):
        return False

    try:
        valid = subreddit_rx.match(x)
        if allow_language_srs:
            valid = valid or language_subreddit_rx.match(x)

        return str(x) if valid else None
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
            self.set_error(self.empty_error, code=400)
        elif len(text) > self.max_length:
            self.set_error(self.length_error, {'max_length': self.max_length}, code=400)
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

    def param_docs(self):
        return {
            self.param: "title of the submission. "
                        "up to %d characters long" % self.max_length,
        }

class VMarkdown(VLength):
    def __init__(self, param, max_length = 10000, renderer='reddit', **kw):
        VLength.__init__(self, param, max_length, **kw)
        self.renderer = renderer

    def run(self, text, text2 = ''):
        text = text or text2
        VLength.run(self, text)
        try:
            markdown_souptest(text, renderer=self.renderer)
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

    def param_docs(self):
        return {
            tup(self.param)[0]: "raw markdown text",
        }

class VSelfText(VMarkdown):

    def set_max_length(self, val):
        self._max_length = val

    def get_max_length(self):
        if c.site.link_type == "self":
            return self._max_length * 4
        return self._max_length * 1.5

    max_length = property(get_max_length, set_max_length)

class VSubredditName(VRequired):
    def __init__(self, item, allow_language_srs=False, *a, **kw):
        VRequired.__init__(self, item, errors.BAD_SR_NAME, *a, **kw)
        self.allow_language_srs = allow_language_srs

    def run(self, name):
        name = chksrname(name, self.allow_language_srs)
        if not name:
            self.set_error(self._error, code=400)
        return name

    def param_docs(self):
        return {
            self.param: "subreddit name",
        }


class VAvailableSubredditName(VSubredditName):
    def run(self, name):
        name = VSubredditName.run(self, name)
        if name:
            try:
                a = Subreddit._by_name(name)
                return self.error(errors.SUBREDDIT_EXISTS)
            except NotFound:
                return name


class VSRByName(Validator):
    def run(self, sr_name):
        if not sr_name:
            self.set_error(errors.BAD_SR_NAME, code=400)
        else:
            try:
                sr = Subreddit._by_name(sr_name)
                return sr
            except NotFound:
                self.set_error(errors.SUBREDDIT_NOEXIST, code=400)

    def param_docs(self):
        return {
            self.param: "subreddit name",
        }


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
    # Lookup tdb_sql.Thing or tdb_cassandra.Thing objects by fullname.
    splitter = re.compile('[ ,]+')
    def __init__(self, param, thing_cls=None, multiple=False, limit=None,
                 error=errors.NO_THING_ID, ignore_missing=False,
                 backend='sql', **kw):
        # Limit param only applies when multiple is True
        if not multiple and limit is not None:
            raise TypeError('multiple must be True when limit is set')
        self.thing_cls = thing_cls
        self.re = fullname_regex(thing_cls)
        self.multiple = multiple
        self.limit = limit
        self._error = error
        self.ignore_missing = ignore_missing
        self.backend = backend

        Validator.__init__(self, param, **kw)

    def run(self, items):
        if self.backend == 'cassandra':
            # tdb_cassandra.Thing objects can't use the regex
            if items and self.multiple:
                items = [item for item in self.splitter.split(items)]
                if self.limit and len(items) > self.limit:
                    return self.set_error(errors.TOO_MANY_THING_IDS)
            if items:
                try:
                    return tdb_cassandra.Thing._by_fullname(
                        items,
                        ignore_missing=self.ignore_missing,
                        return_dict=False,
                    )
                except NotFound:
                    pass
        else:
            if items and self.multiple:
                items = [item for item in self.splitter.split(items)
                         if item and self.re.match(item)]
                if self.limit and len(items) > self.limit:
                    return self.set_error(errors.TOO_MANY_THING_IDS)
            if items and (self.multiple or self.re.match(items)):
                try:
                    return Thing._by_fullname(
                        items,
                        return_dict=False,
                        ignore_missing=self.ignore_missing,
                        data=True,
                    )
                except NotFound:
                    pass

        return self.set_error(self._error)

    def param_docs(self):
        thingtype = (self.thing_cls or Thing).__name__.lower()
        return {
            self.param: "[fullname](#fullnames) of a %s" % thingtype,
        }

class VByNameIfAuthor(VByName):
    def run(self, fullname):
        thing = VByName.run(self, fullname)
        if thing:
            if not thing._loaded: thing._load()
            if c.user_is_loggedin and thing.author_id == c.user._id:
                return thing
        return self.set_error(errors.NOT_AUTHOR)

    def param_docs(self):
        return {
            self.param: "[fullname](#fullnames) of a thing created by the user",
        }

class VCaptcha(Validator):
    default_param = ('iden', 'captcha')

    def run(self, iden, solution):
        if c.user.needs_captcha():
            valid_captcha = captcha.valid_solution(iden, solution)
            if not valid_captcha:
                self.set_error(errors.BAD_CAPTCHA)
            g.stats.action_event_count("captcha", valid_captcha)

    def param_docs(self):
        return {
            self.param[0]: "the identifier of the CAPTCHA challenge",
            self.param[1]: "the user's response to the CAPTCHA challenge",
        }

class VUser(Validator):
    def run(self, password = None):
        if not c.user_is_loggedin:
            raise UserRequiredException

        if (password is not None) and not valid_password(c.user, password):
            self.set_error(errors.WRONG_PASSWORD)

class VModhash(Validator):
    default_param = 'uh'
    def __init__(self, param=None, fatal=True, *a, **kw):
        Validator.__init__(self, param, *a, **kw)
        self.fatal = fatal

    def run(self, uh):
        if uh is None:
            uh = request.headers.get('X-Modhash')

        if not c.user_is_loggedin or uh != c.user.name:
            if self.fatal:
                abort(403)
            self.set_error('INVALID_MODHASH')

    def param_docs(self):
        return {
            self.param: 'a [modhash](#modhashes)',
        }

class VVotehash(Validator):
    def run(self, vh, thing_name):
        return True

    def param_docs(self):
        return {
            self.param[0]: "ignored",
        }

class VAdmin(Validator):
    def run(self):
        if not c.user_is_admin:
            abort(404, "page not found")

def make_or_admin_secret_cls(base_cls):
    class VOrAdminSecret(base_cls):
        def run(self, secret=None):
            '''If validation succeeds, return True if the secret was used,
            False otherwise'''
            if secret and constant_time_compare(secret, g.ADMINSECRET):
                return True
            super(VOrAdminSecret, self).run()
            return False
    return VOrAdminSecret

VAdminOrAdminSecret = make_or_admin_secret_cls(VAdmin)

class VVerifiedUser(VUser):
    def run(self):
        VUser.run(self)
        if not c.user.email_verified:
            raise VerifiedUserRequiredException

class VGold(VUser):
    def run(self):
        VUser.run(self)
        if not c.user.gold:
            abort(403, 'forbidden')

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

VSponsorAdminOrAdminSecret = make_or_admin_secret_cls(VSponsorAdmin)

class VSponsor(VVerifiedUser):
    """
    Not intended to be used as a check for c.user_is_sponsor, but
    rather is the user allowed to use the sponsored link system.
    If a link or campaign is passed in, it also checks whether the user is
    allowed to edit that particular sponsored link.
    """
    def user_test(self, thing):
        return (thing.author_id == c.user._id)

    def run(self, link_id=None, campaign_id=None):
        assert not (link_id and campaign_id), 'Pass link or campaign, not both'

        VVerifiedUser.run(self)
        if c.user_is_sponsor:
            return
        elif campaign_id:
            pc = None
            try:
                if '_' in campaign_id:
                    pc = PromoCampaign._by_fullname(campaign_id, data=True)
                else:
                    pc = PromoCampaign._byID36(campaign_id, data=True)
            except (NotFound, ValueError):
                pass
            if pc:
                link_id = pc.link_id
        if link_id:
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
    def __init__(self, fatal=True, perms=(), *a, **kw):
        # If True, abort rather than setting an error
        self.fatal = fatal
        self.perms = utils.tup(perms)
        super(VSrModerator, self).__init__(*a, **kw)

    def run(self):
        if not (c.user_is_loggedin
                and c.site.is_moderator_with_perms(c.user, *self.perms)
                or c.user_is_admin):
            if self.fatal:
                abort(403, "forbidden")
            return self.set_error('MODERATOR_REQUIRED', code=403)

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
            return True
        elif c.user_is_loggedin:
            item = VByName.run(self, thing_name)
            # will throw a legitimate 500 if this isn't a link or
            # comment, because this should only be used on links and
            # comments
            subreddit = item.subreddit_slow
            if subreddit.is_moderator_with_perms(c.user, 'posts'):
                return True
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
                if parent._spam and isinstance(parent, Comment):
                    # Only author, mod or admin can reply to removed comments
                    can_reply = (c.user_is_loggedin and
                                 (parent.author_id == c.user._id or
                                  c.user_is_admin or
                                  parent.subreddit_slow.is_moderator(c.user)))
                    if not can_reply:
                        self.set_error(errors.DELETED_COMMENT)
            if isinstance(parent, Message):
                return parent
            else:
                link = parent
                if isinstance(parent, Comment):
                    link = Link._byID(parent.link_id, data=True)
                if link and c.user_is_loggedin and can_comment_link(link):
                    return parent
        #else
        abort(403, "forbidden")

    def param_docs(self):
        return {
            self.param[0]: "[fullname](#fullnames) of parent thing",
        }

class VSubmitSR(Validator):
    def __init__(self, srname_param, linktype_param=None, promotion=False):
        self.require_linktype = False
        self.promotion = promotion

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

        if not c.user_is_loggedin or not sr.can_submit(c.user, self.promotion):
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

    def param_docs(self):
        return {
            self.param[0]: "name of a subreddit",
        }

class VSubscribeSR(VByName):
    def __init__(self, srid_param, srname_param):
        VByName.__init__(self, (srid_param, srname_param))

    def run(self, sr_id, sr_name):
        if sr_id:
            return VByName.run(self, sr_id)
        elif not sr_name:
            return

        try:
            sr = Subreddit._by_name(str(sr_name).strip())
        except (NotFound, AttributeError, UnicodeEncodeError):
            self.set_error(errors.SUBREDDIT_NOEXIST)
            return

        return sr

MIN_PASSWORD_LENGTH = 3

class VPassword(Validator):
    def run(self, password, verify):
        if not (password and len(password) >= MIN_PASSWORD_LENGTH):
            self.set_error(errors.BAD_PASSWORD)
        elif verify != password:
            self.set_error(errors.BAD_PASSWORD_MATCH)
        else:
            return password.encode('utf8')

    def param_docs(self):
        return {
            self.param[0]: "the new password",
            self.param[1]: "the password again (for verification)",
        }

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

    def param_docs(self):
        return {
            self.param[0]: "a valid, unused, username",
        }

class VLoggedOut(Validator):
    def run(self):
        if c.user_is_loggedin:
            self.set_error(errors.LOGGED_IN)

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
            self.error()
            return False
        return user

class VThrottledLogin(VLogin):
    def __init__(self, *args, **kwargs):
        VLogin.__init__(self, *args, **kwargs)
        self.vdelay = VDelay("login")
        self.vlength = VLength("user", max_length=100)

    def run(self, username, password):
        if username:
            username = username.strip()
        username = self.vlength.run(username)

        self.vdelay.run()
        if (errors.RATELIMIT, "vdelay") in c.errors:
            return False

        user = VLogin.run(self, username, password)
        if login_throttle(username, wrong_password=not user):
            VDelay.record_violation("login", seconds=1, growfast=True)
            c.errors.add(errors.WRONG_PASSWORD, field=self.param[1])
        else:
            return user

    def param_docs(self):
        return {
            self.param[0]: "a username",
            self.param[1]: "the user's password",
        }

class VSanitizedUrl(Validator):
    def run(self, url):
        return utils.sanitize_url(url)

    def param_docs(self):
        return {self.param: "a valid URL"}

class VUrl(VRequired):
    def __init__(self, item, allow_self = True, lookup = True, *a, **kw):
        self.allow_self = allow_self
        self.lookup = lookup
        VRequired.__init__(self, item, errors.NO_URL, *a, **kw)

    def run(self, url, sr = None, resubmit=False):
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
        elif not self.lookup or resubmit:
            return url
        elif url:
            try:
                l = Link._by_url(url, sr)
                self.error(errors.ALREADY_SUB)
                return utils.tup(l)
            except NotFound:
                return url
        return self.error(errors.BAD_URL)

    def param_docs(self):
        if isinstance(self.param, (list, tuple)):
            param_names = self.param
        else:
            param_names = [self.param]
        params = {}
        try:
            params[param_names[0]] = 'a valid URL'
            params[param_names[1]] = 'a subreddit'
            params[param_names[2]] = 'boolean value'
        except IndexError:
            pass
        return params

class VShamedDomain(Validator):
    def run(self, url):
        if not url:
            return

        is_shamed, domain, reason = is_shamed_domain(url)

        if is_shamed:
            self.set_error(errors.DOMAIN_BANNED, dict(domain=domain,
                                                      reason=reason))

class VExistingUname(VRequired):
    def __init__(self, item, *a, **kw):
        VRequired.__init__(self, item, errors.NO_USER, *a, **kw)

    def run(self, name):
        if name and name.startswith('~') and c.user_is_admin:
            try:
                user_id = int(name[1:])
                return Account._byID(user_id, True)
            except (NotFound, ValueError):
                self.error(errors.USER_DOESNT_EXIST)

        # make sure the name satisfies our user name regexp before
        # bothering to look it up.
        name = chkuser(name)
        if name:
            try:
                return Account._by_name(name)
            except NotFound:
                self.error(errors.USER_DOESNT_EXIST)
        else:
            self.error()

    def param_docs(self):
        return {
            self.param: 'the name of an existing user'
        }

class VMessageRecipient(VExistingUname):
    def run(self, name):
        if not name:
            return self.error()
        is_subreddit = False
        if name.startswith('/r/'):
            name = name[3:]
            is_subreddit = True
        elif name.startswith('#'):
            name = name[1:]
            is_subreddit = True
        if is_subreddit:
            try:
                s = Subreddit._by_name(name)
                if isinstance(s, FakeSubreddit):
                    raise NotFound, "fake subreddit"
                if s._spam:
                    raise NotFound, "banned subreddit"
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

    def param_docs(self):
        return {
            self.param: 'boolean value',
        }

class VNumber(Validator):
    def __init__(self, param, min=None, max=None, coerce = True,
                 error=errors.BAD_NUMBER, num_default=None,
                 *a, **kw):
        self.min = self.cast(min) if min is not None else None
        self.max = self.cast(max) if max is not None else None
        self.coerce = coerce
        self.error = error
        self.num_default = num_default
        Validator.__init__(self, param, *a, **kw)

    def cast(self, val):
        raise NotImplementedError

    def run(self, val):
        if not val:
            return self.num_default
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
            if self.max is None and self.min is None:
                range = ""
            elif self.max is None:
                range = _("%(min)d to any") % dict(min=self.min)
            elif self.min is None:
                range = _("any to %(max)d") % dict(max=self.max)
            else:
                range = _("%(min)d to %(max)d") % dict(min=self.min, max=self.max)
            self.set_error(self.error, msg_params=dict(range=range))

class VInt(VNumber):
    def cast(self, val):
        return int(val)

class VFloat(VNumber):
    def cast(self, val):
        return float(val)


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

    def param_docs(self):
        return {
            self.param[0]: 'one of (%s)' % ', '.join(self.nav.options),
        }


class VRatelimit(Validator):
    def __init__(self, rate_user = False, rate_ip = False,
                 prefix = 'rate_', error = errors.RATELIMIT, *a, **kw):
        self.rate_user = rate_user
        self.rate_ip = rate_ip
        self.prefix = prefix
        self.error = error
        self.seconds = None
        Validator.__init__(self, *a, **kw)

    def run (self):
        from r2.models.admintools import admin_ratelimit

        if g.disable_ratelimit:
            return

        if c.user_is_loggedin and not admin_ratelimit(c.user):
            return

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
                from datetime import datetime
                delta = expire_time - datetime.now(g.tz)
                self.seconds = delta.total_seconds()
                if self.seconds < 3:  # Don't ratelimit within three seconds
                    return
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
        if g.disable_ratelimit:
            return
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

        with g.make_lock("record_violation", "lock-" + key, timeout=5, verbose=False):
            existing = g.memcache.get(key)
            if existing and existing["count"] > prev_violations["count"]:
                g.log.warning("Tried to set %s to count=%d, but found existing=%d"
                             % (key, prev_violations["count"], existing["count"]))
            else:
                g.cache.set(key, prev_violations, max_duration)

class VCommentIDs(Validator):
    def run(self, id_str):
        if id_str:
            cids = [int(i, 36) for i in id_str.split(',')]
            comments = Comment._byID(cids, data=True, return_dict = False)
            return comments
        return []

    def param_docs(self):
        return {
            self.param: "a comma-delimited list of comment ID36s",
        }


class CachedUser(object):
    def __init__(self, cache_prefix, user, key):
        self.cache_prefix = cache_prefix
        self.user = user
        self.key = key

    def clear(self):
        if self.key and self.cache_prefix:
            g.cache.delete(str(self.cache_prefix + "_" + self.key))

class VOneTimeToken(Validator):
    def __init__(self, model, param, *args, **kwargs):
        self.model = model
        Validator.__init__(self, param, *args, **kwargs)

    def run(self, key):
        token = self.model.get_token(key)

        if token:
            return token
        else:
            self.set_error(errors.EXPIRED)
            return None

class VOneOf(Validator):
    def __init__(self, param, options = (), *a, **kw):
        Validator.__init__(self, param, *a, **kw)
        self.options = options

    def run(self, val):
        if self.options and val not in self.options:
            self.set_error(errors.INVALID_OPTION, code=400)
            return self.default
        else:
            return val

    def param_docs(self):
        return {
            self.param: 'one of (%s)' % ', '.join(self.options)
        }

class VImageType(Validator):
    def run(self, img_type):
        if not img_type in ('png', 'jpg'):
            return 'png'
        return img_type


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

class ValidEmailsOrExistingUnames(Validator):
    """Validates a list of mixed email addresses and usernames passed in
    as a string, delineated by whitespace, ',' or ';'.  Validates total
    quantity too while we're at it.  Returns a tuple of the form
    (e-mail addresses, user account objects)"""

    def __init__(self, param, num=20, **kw):
        self.num = num
        Validator.__init__(self, param=param, **kw)

    def run(self, items):
        # Use ValidEmails separator to break the list up
        everything = set(ValidEmails.separator.findall(items) if items else [])

        # Use ValidEmails regex to divide the list into e-mail and other
        emails = set(e for e in everything if ValidEmails.email_re.match(e))
        failures = everything - emails

        # Run the rest of the validator against the e-mails list
        ve = ValidEmails(self.param, self.num)
        if len(emails) > 0:
            ve.run(", ".join(emails))

        # ValidEmails will add to c.errors for us, so do nothing if that fails
        # Elsewise, on with the users
        if not ve.has_errors:
            users = set()  # set of accounts
            validusers = set()  # set of usernames to subtract from failures

            # Now steal from VExistingUname:
            for uname in failures:
                check = uname
                if re.match('/u/', uname):
                    check = check[3:]
                veu = VExistingUname(check)
                account = veu.run(check)
                if account:
                    validusers.add(uname)
                    users.add(account)

            # We're fine if all our failures turned out to be valid users
            if len(users) == len(failures):
                # ValidEmails checked to see if there were too many addresses,
                # check to see if there's enough left-over space for users
                remaining = self.num - len(emails)
                if len(users) > remaining:
                    if self.num == 1:
                        # We only wanted one, and we got it as an e-mail,
                        # so complain.
                        self.set_error(errors.BAD_EMAILS,
                                       {"emails": '"%s"' % items})
                    else:
                        # Too many total
                        self.set_error(errors.TOO_MANY_EMAILS,
                                       {"num": self.num})
                elif len(users) + len(emails) == 0:
                    self.set_error(errors.NO_EMAILS)
                else:
                    # It's all good!
                    return (emails, users)
            else:
                failures = failures - validusers
                self.set_error(errors.BAD_EMAILS,
                               {'emails': ', '.join(failures)})

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


# NOTE: make sure *never* to have res check these are present
# otherwise, the response could contain reference to these errors...!
class ValidIP(Validator):
    def run(self):
        if is_banned_IP(request.ip):
            self.set_error(errors.BANNED_IP)
        return request.ip

class VDate(Validator):
    """
    Date checker that accepts string inputs.

    Optional parameters include 'past' and 'future' which specify how
    far (in days) into the past or future the date must be to be
    acceptable.

    NOTE: the 'future' param will have precidence during evaluation.

    Error conditions:
       * BAD_DATE on mal-formed date strings (strptime parse failure)
       * BAD_FUTURE_DATE and BAD_PAST_DATE on respective range errors.

    """
    def __init__(self, param, future=None, past = None,
                 sponsor_override = False,
                 reference_date = lambda : datetime.now(g.tz),
                 business_days = False,
                 format = "%m/%d/%Y"):
        self.future = future
        self.past   = past

        # are weekends to be exluded from the interval?
        self.business_days = business_days

        self.format = format

        # function for generating "now"
        self.reference_date = reference_date

        # do we let admins and sponsors override date range checking?
        self.override = sponsor_override
        Validator.__init__(self, param)

    def run(self, date):
        now = self.reference_date()
        override = c.user_is_sponsor and self.override
        try:
            date = datetime.strptime(date, self.format)
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

    If required is False, then the dates may be omitted without
    causing an error (but if a start date is provided, an end
    date MUST be provided as well).

    Additional Error conditions:
      * BAD_DATE_RANGE if start_date is not less than end_date
    """
    def __init__(self, param, max_range=None, required=True, **kw):
        self.max_range = max_range
        self.required = required
        VDate.__init__(self, param, **kw)


    def run(self, *a):
        try:
            start_date, end_date = [VDate.run(self, x) for x in a]
            # If either date is missing and dates are "required",
            # it's a bad range. Additionally, if one date is missing,
            # but the other is provided, it's always an error.
            if not start_date or not end_date:
                if self.required or (not start_date and not end_date):
                    self.set_error(errors.BAD_DATE_RANGE)
                return (start_date, end_date)
            elif end_date < start_date:
                self.set_error(errors.BAD_DATE_RANGE)
            elif self.max_range and end_date - start_date > self.max_range:
                self.set_error(errors.DATE_RANGE_TOO_LARGE,
                               {'days': self.max_range})
            return (start_date, end_date)
        except ValueError:
            # insufficient number of arguments provided (expect 2)
            self.set_error(errors.BAD_DATE_RANGE)


class VDestination(Validator):
    def __init__(self, param = 'dest', default = "", **kw):
        Validator.__init__(self, param, default, **kw)

    def run(self, dest):
        if not dest:
            dest = self.default or "/"

        ld = dest.lower()
        if ld.startswith(('/', 'http://', 'https://')):
            u = UrlParser(dest)

            if u.is_reddit_url(c.site):
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

    def param_docs(self):
        return {
            self.param: 'destination url (must be same-domain)',
        }

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
            country_name = g.countries.get(country)
            if country_name not in self.allowed_countries:
                self.set_error(_("Our ToS don't cover your country (yet). Sorry."), "country")

        # Make sure values don't exceed max length defined in the authorize.net
        # xml schema: https://api.authorize.net/xml/v1/schema/AnetApiSchema.xsd
        max_lengths = [
            (firstName, 50, 'firstName'), # (argument, max len, form field name)
            (lastName, 50, 'lastName'),
            (company, 50, 'company'),
            (address, 60, 'address'),
            (city, 40, 'city'),
            (state, 40, 'state'),
            (zipCode, 20, 'zip'),
            (phoneNumber, 255, 'phoneNumber')
        ]
        for (arg, max_length, form_field_name) in max_lengths:
            if arg and len(arg) > max_length:
                self.set_error(_("max length %d characters" % max_length), form_field_name)

        if not self.has_errors:
            return Address(firstName = firstName,
                           lastName = lastName,
                           company = company or "",
                           address = address,
                           city = city, state = state,
                           zip = zipCode, country = country_name,
                           phoneNumber = phoneNumber or "")

class ValidCard(Validator):
    valid_ccn  = re.compile(r"\d{13,16}")
    valid_date = re.compile(r"\d\d\d\d-\d\d")
    valid_ccv  = re.compile(r"\d{3,4}")
    def set_error(self, msg, field):
        Validator.set_error(self, errors.BAD_CARD,
                            dict(message=msg), field = field)

    def run(self, cardNumber, expirationDate, cardCode):
        has_errors = False

        if not self.valid_ccn.match(cardNumber or ""):
            self.set_error(_("credit card numbers should be 13 to 16 digits"),
                           "cardNumber")
            has_errors = True

        if not self.valid_date.match(expirationDate or ""):
            self.set_error(_("dates should be YYYY-MM"), "expirationDate")
            has_errors = True
        else:
            now = datetime.now(g.tz)
            yyyy, mm = expirationDate.split("-")
            year = int(yyyy)
            month = int(mm)
            if month < 1 or month > 12:
                self.set_error(_("month must be in the range 01..12"), "expirationDate")
                has_errors = True
            elif datetime(year, month, 1) < datetime(now.year, now.month, 1):
                self.set_error(_("expiration date must be in the future"), "expirationDate")
                has_errors = True

        if not self.valid_ccv.match(cardCode or ""):
            self.set_error(_("card verification codes should be 3 or 4 digits"),
                           "cardCode")
            has_errors = True

        if not has_errors:
            return CreditCard(cardNumber = cardNumber,
                              expirationDate = expirationDate,
                              cardCode = cardCode)

class VTarget(Validator):
    target_re = re.compile("\A[\w_-]{3,20}\Z")
    def run(self, name):
        if name and self.target_re.match(name):
            return name

class VFlairAccount(VRequired):
    def __init__(self, item, *a, **kw):
        VRequired.__init__(self, item, errors.BAD_FLAIR_TARGET, *a, **kw)

    def _lookup(self, name, allow_deleted):
        try:
            return Account._by_name(name, allow_deleted=allow_deleted)
        except NotFound:
            return None

    def run(self, name):
        if not name:
            return self.error()
        return (
            self._lookup(name, False)
            or self._lookup(name, True)
            or self.error())

class VFlairLink(VRequired):
    def __init__(self, item, *a, **kw):
        VRequired.__init__(self, item, errors.BAD_FLAIR_TARGET, *a, **kw)

    def run(self, name):
        if not name:
            return self.error()
        try:
            return Link._by_fullname(name, data=True)
        except NotFound:
            return self.error()

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

class VFlairTemplateByID(VRequired):
    def __init__(self, param, **kw):
        VRequired.__init__(self, param, None, **kw)

    def run(self, flair_template_id):
        try:
            return FlairTemplateBySubredditIndex.get_template(
                c.site._id, flair_template_id)
        except tdb_cassandra.NotFound:
            return None

class VOneTimePassword(Validator):
    max_skew = 2  # check two periods to allow for some clock skew
    ratelimit = 3  # maximum number of tries per period

    def __init__(self, param, required):
        self.required = required
        Validator.__init__(self, param)

    @classmethod
    def validate_otp(cls, secret, password):
        # is the password a valid format and has it been used?
        try:
            key = "otp-%s-%d" % (c.user._id36, int(password))
        except (TypeError, ValueError):
            valid_and_unused = False
        else:
            # leave this key around for one more time period than the maximum
            # number of time periods we'll check for valid passwords
            key_ttl = totp.PERIOD * (cls.max_skew + 1)
            valid_and_unused = g.cache.add(key, True, time=key_ttl)

        # check the password (allowing for some clock-skew as 2FA-users
        # frequently travel at relativistic velocities)
        if valid_and_unused:
            for skew in range(cls.max_skew):
                expected_otp = totp.make_totp(secret, skew=skew)
                if constant_time_compare(password, expected_otp):
                    return True

        return False

    def run(self, password):
        # does the user have 2FA configured?
        secret = c.user.otp_secret
        if not secret:
            if self.required:
                self.set_error(errors.NO_OTP_SECRET)
            return

        # do they have the otp cookie instead?
        if c.otp_cached:
            return

        # make sure they're not trying this too much
        if not g.disable_ratelimit:
            current_password = totp.make_totp(secret)
            key = "otp-tries-" + current_password
            g.cache.add(key, 0)
            recent_attempts = g.cache.incr(key)
            if recent_attempts > self.ratelimit:
                self.set_error(errors.RATELIMIT, dict(time="30 seconds"))
                return

        # check the password
        if self.validate_otp(secret, password):
            return

        # if we got this far, their password was wrong, invalid or already used
        self.set_error(errors.WRONG_PASSWORD)

class VOAuth2ClientID(VRequired):
    default_param = "client_id"
    default_param_doc = _("an app")
    def __init__(self, param=None, *a, **kw):
        VRequired.__init__(self, param, errors.OAUTH2_INVALID_CLIENT, *a, **kw)

    def run(self, client_id):
        client_id = VRequired.run(self, client_id)
        if client_id:
            client = OAuth2Client.get_token(client_id)
            if client and not getattr(client, 'deleted', False):
                return client
            else:
                self.error()

    def param_docs(self):
        return {self.default_param: self.default_param_doc}

class VOAuth2ClientDeveloper(VOAuth2ClientID):
    default_param_doc = _("an app developed by the user")

    def run(self, client_id):
        client = super(VOAuth2ClientDeveloper, self).run(client_id)
        if not client or not client.has_developer(c.user):
            return self.error()
        return client

class VOAuth2Scope(VRequired):
    default_param = "scope"
    def __init__(self, param=None, *a, **kw):
        VRequired.__init__(self, param, errors.OAUTH2_INVALID_SCOPE, *a, **kw)

    def run(self, scope):
        scope = VRequired.run(self, scope)
        if scope:
            parsed_scope = OAuth2Scope(scope)
            if parsed_scope.is_valid():
                return parsed_scope
            else:
                self.error()

class VOAuth2RefreshToken(Validator):
    def __init__(self, param, *a, **kw):
        Validator.__init__(self, param, None, *a, **kw)

    def run(self, refresh_token_id):
        if refresh_token_id:
            try:
                token = OAuth2RefreshToken._byID(refresh_token_id)
            except tdb_cassandra.NotFound:
                self.set_error(errors.OAUTH2_INVALID_REFRESH_TOKEN)
                return None
            if not token.check_valid():
                self.set_error(errors.OAUTH2_INVALID_REFRESH_TOKEN)
                return None
            return token
        else:
            return None

class VPermissions(Validator):
    types = dict(
        moderator=ModeratorPermissionSet,
        moderator_invite=ModeratorPermissionSet,
    )

    def __init__(self, type_param, permissions_param, *a, **kw):
        Validator.__init__(self, (type_param, permissions_param), *a, **kw)

    def run(self, type, permissions):
        permission_class = self.types.get(type)
        if not permission_class:
            self.set_error(errors.INVALID_PERMISSION_TYPE, field=self.param[0])
            return (None, None)
        try:
            perm_set = permission_class.loads(permissions, validate=True)
        except ValueError:
            self.set_error(errors.INVALID_PERMISSIONS, field=self.param[1])
            return (None, None)
        return type, perm_set


class VJSON(Validator):
    def run(self, json_str):
        if not json_str:
            return self.set_error('JSON_PARSE_ERROR', code=400)
        else:
            try:
                return json.loads(json_str)
            except ValueError:
                return self.set_error('JSON_PARSE_ERROR', code=400)

    def param_docs(self):
        return {
            self.param: "JSON data",
        }


class VValidatedJSON(VJSON):
    """Apply validators to the values of JSON formatted data."""
    class ArrayOf(object):
        """A JSON array of objects with the specified schema."""
        def __init__(self, spec):
            self.spec = spec

        def run(self, data):
            if not isinstance(data, list):
                raise RedditError('JSON_INVALID', code=400)

            validated_data = []
            for item in data:
                validated_data.append(self.spec.run(item))
            return validated_data

        def spec_docs(self):
            spec_lines = []
            spec_lines.append('[')
            for line in self.spec.spec_docs().split('\n'):
                spec_lines.append('  ' + line)
            spec_lines[-1] += ','
            spec_lines.append('  ...')
            spec_lines.append(']')
            return '\n'.join(spec_lines)


    class Object(object):
        """A JSON object with validators for specified fields."""
        def __init__(self, spec):
            self.spec = spec

        def run(self, data):
            if not isinstance(data, dict):
                raise RedditError('JSON_INVALID', code=400)

            validated_data = {}
            for key, validator in self.spec.iteritems():
                try:
                    validated_data[key] = validator.run(data[key])
                except KeyError:
                    raise RedditError('JSON_MISSING_KEY', code=400,
                                      msg_params={'key': key})
            return validated_data

        def spec_docs(self):
            spec_docs = {}
            for key, validator in self.spec.iteritems():
                if hasattr(validator, 'spec_docs'):
                    spec_docs[key] = validator.spec_docs()
                elif hasattr(validator, 'param_docs'):
                    spec_docs.update(validator.param_docs())
                    if validator.docs:
                        spec_docs.update(validator.docs)

            # generate markdown json schema docs
            spec_lines = []
            spec_lines.append('{')
            for key in sorted(spec_docs.keys()):
                key_docs = spec_docs[key]
                # indent any new lines
                key_docs = key_docs.replace('\n', '\n  ')
                spec_lines.append('  "%s": %s,' % (key, key_docs))
            spec_lines.append('}')
            return '\n'.join(spec_lines)


    def __init__(self, param, spec, **kw):
        VJSON.__init__(self, param, **kw)
        self.spec = spec

    def run(self, json_str):
        data = VJSON.run(self, json_str)
        if self.has_errors:
            return

        # Note: this relies on the fact that all validator errors are dumped
        # into a global (c.errors) and then checked by @validate.
        return self.spec.run(data)

    def param_docs(self):
        spec_md = self.spec.spec_docs()

        # indent for code formatting
        spec_md = '\n'.join(
            '    ' + line for line in spec_md.split('\n')
        )

        return {
            self.param: 'json data:\n\n' + spec_md,
        }


multi_name_rx = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_]{1,20}\Z")
multi_name_chars_rx = re.compile(r"[^A-Za-z0-9_]")

class VMultiPath(Validator):
    @classmethod
    def normalize(self, path):
        if path[0] != '/':
            path = '/' + path
        path = path.lower().rstrip('/')
        return path

    def run(self, path):
        try:
            require(path)
            path = self.normalize(path)
            require(path.startswith('/user/'))
            user, username, m, name = require_split(path, 5, sep='/')[1:]
            require(m == 'm')
            username = chkuser(username)
            require(username)
        except RequirementException:
            self.set_error('BAD_MULTI_PATH', code=400)
            return

        try:
            require(multi_name_rx.match(name))
        except RequirementException:
            invalid_char = multi_name_chars_rx.search(name)
            if invalid_char:
                char = invalid_char.group()
                if char == ' ':
                    reason = _('no spaces allowed')
                else:
                    reason = _("invalid character: '%s'") % char
            elif name[0] == '_':
                reason = _("can't start with a '_'")
            elif len(name) < 2:
                reason = _('that name is too short')
            elif len(name) > 21:
                reason = _('that name is too long')
            else:
                reason = _("that name isn't going to work")

            self.set_error('BAD_MULTI_NAME', {'reason': reason}, code=400)
            return

        return {'path': path, 'username': username, 'name': name}

    def param_docs(self):
        return {
            self.param: "multireddit url path",
        }


class VMultiByPath(Validator):
    def __init__(self, param, require_view=True, require_edit=False):
        Validator.__init__(self, param)
        self.require_view = require_view
        self.require_edit = require_edit

    def run(self, path):
        path = VMultiPath.normalize(path)
        try:
            multi = LabeledMulti._byID(path)
        except tdb_cassandra.NotFound:
            return self.set_error('MULTI_NOT_FOUND', code=404)

        if not multi or (self.require_view and not multi.can_view(c.user)):
            return self.set_error('MULTI_NOT_FOUND', code=404)
        if self.require_edit and not multi.can_edit(c.user):
            return self.set_error('MULTI_CANNOT_EDIT', code=403)

        return multi

    def param_docs(self):
        return {
            self.param: "multireddit url path",
        }
