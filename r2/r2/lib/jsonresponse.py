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
from r2.lib.utils import tup
from r2.lib.captcha import get_iden
from r2.lib.wrapped import Wrapped
from r2.lib.filters import websafe_json
from r2.lib.template_helpers import replace_render
from r2.lib.jsontemplates import get_api_subtype
import simplejson

def json_respond(x):
    from pylons import c
    if get_api_subtype():
        res = JsonResponse()
        res.object = tup(x)
        res = dict(res)
    else:
        res = x or ''
    return websafe_json(simplejson.dumps(res))


class JsonListingStub(object):
    """used in JsonResponse._thing to set default listing behavior on
    things that are pre-wrapped"""
    _js_cls = "Listing"

class JsonResponse():
    # handled entried in the response object
    __slots__ = ['update', 'blur', 'focus', 'object', 'hide', 'show',
                 'captcha', 'success']

    def __init__(self):
        self.update = []
        self.hide = []
        self.show = []
        self.focus = None
        self.blur = None
        self.object = {}
        self.captcha = None
        self.error = None
        self.success = None
        self.redirect = None

    def _success(self):
        self.success = 1

    def _hide(self, name):
        self.hide.append(dict(name=name))

    def _show(self, name):
        self.show.append(dict(name=name))


    def _focus(self, f): 
        self.focus = f

    def _blur(self, f): 
        self.blur = f

    def _redirect(self, red):
        self.redirect = red


    def _update(self, name, **kw):
        k = kw.copy()
        k['id'] = name
        self.update.append(k)

    def _clear_error(self, error_name, err_on_thing = ''):
        errid = error_name + (('_' + err_on_thing) if err_on_thing else '')
        self._update(errid, innerHTML='')
        self._hide(errid)
        if self.error and self.error.name == error_name:
            self.error_thing_id = '';
            self.error = None

    def _set_error(self, error, err_on_thing = ''):
        if not self.error:
            self.error = error
            self.error_thing_id = err_on_thing;

    def _chk_error(self, error_name, err_on_thing = ''):
        from pylons import c
        if error_name in c.errors:
            error = c.errors[error_name]
            self._set_error(error, err_on_thing)
            return True
        else:
            self._clear_error(error_name, err_on_thing)
            return False

    def _chk_errors(self, errors):
        if errors:
           return reduce(lambda x, y: x or y,
                          [self._chk_error(e) for e in errors])
        return False

    def _chk_captcha(self, err):
        if self._chk_error(err):
            self.captcha = {'iden' : get_iden(), 'refresh' : True}
            self._focus('captcha')

    @property
    def response(self): 
        res = {}
        for k in self.__slots__:
            v = getattr(self, k)
            if v: res[k] = v
        return res

    def _thing(self, thing, action = None):
        d = replace_render(JsonListingStub(), thing)
        if action:
            d['action'] = action
        return d

    def _send_things(self, things, action=None):
        from r2.models import IDBuilder
        things = tup(things)
        if not all(isinstance(t, Wrapped) for t in things):
            b = IDBuilder([t._fullname for t in things])
            things = b.get_items()[0]
        self.object = [self._thing(thing, action=action) for thing in things]

    def __iter__(self):
        if self.error:
            e = dict(self.error)
            if self.error_thing_id:
                e['id'] = self.error_thing_id
            yield 'error', e
        if self.response:
            yield 'response', self.response
        if self.redirect:
            yield 'redirect', self.redirect
        
def Json(func):
    def _Json(self, *a, **kw):
        from pylons import c
        from jsontemplates import api_type
        c.render_style = api_type('html')
        c.response_content_type = 'application/json; charset=UTF-8'
        res = JsonResponse()
        val = func(self, res, *a, **kw)
        if val: return val
        return self.response_func(**dict(res))
    return _Json

