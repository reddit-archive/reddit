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
# All portions of the code written by CondeNet are Copyright (c) 2006-2009
# CondeNet, Inc. All Rights Reserved.
################################################################################
from r2.lib.utils import tup
from r2.lib.captcha import get_iden
from r2.lib.wrapped import Wrapped
from r2.lib.filters import websafe_json
from r2.lib.template_helpers import replace_render
from r2.lib.jsontemplates import get_api_subtype
from r2.lib.base import BaseController
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

class JQueryResponse(object):
    """
    class which mimics the jQuery in javascript for allowing Dom
    manipulations on the client side.
    
    An instantiated JQueryResponse acts just like the "$" function on
    the JS layer with the exception of the ability to run arbitrary
    code on the client.  Selectors and method functions evaluate to
    new JQueryResponse objects, and the transformations are cataloged
    by the original object which can be iterated and sent across the
    wire.
    """
    def __init__(self, factory = None):
        self._has_errors = set([])
        self._new_captcha = False
        if factory:
            self.factory = factory
            self.ops = None
            self.objs = None
        else:
            self.factory = self
            self.objs = {self: 0}
            self.ops = []
        
    def __call__(self, *a):
        return self.factory.transform(self, "call", a)

    def __getattr__(self, key):
        if not key.startswith("__"):
            return self.factory.transform(self, "attr", key)

    def transform(self, obj, op, args):
        new = self.__class__(self)
        newi = self.objs[new] = len(self.objs)
        self.ops.append([self.objs[obj], newi, op, args])
        return new

    def __iter__(self):
        yield ("jquery", self.ops)

    def has_error(self):
        return bool(self._has_errors)

    # thing methods
    #--------------
    
    def _things(self, things, action, *a, **kw):
        """
        function for inserting/replacing things in listings.
        """
        from r2.models import IDBuilder, Listing
        listing = None
        if isinstance(things, Listing):
            listing = things.listing()
            things = listing.things
        things = tup(things)
        if not all(isinstance(t, Wrapped) for t in things):
            b = IDBuilder([t._fullname for t in things])
            things = b.get_items()[0]
        data = [replace_render(listing, t) for t in things]

        if kw:
            for d in data:
                if d.has_key('data'):
                    d['data'].update(kw)

        new = self.__getattr__(action)
        return new(data, *a)

    def insert_things(self, things, append = False, **kw):
        return self._things(things, "insert_things", append, **kw)

    def replace_things(self, things, keep_children = False,
                       reveal = False, stubs = False, **kw):
        return self._things(things, "replace_things",
                            keep_children, reveal, stubs, **kw)

    def insert_table_rows(self, rows, index = -1):
        new = self.__getattr__("insert_table_rows")
        return new([row.render() for row in tup(rows)], index)


    # convenience methods:
    # --------------------
    def has_errors(self, input, *errors, **kw):
        from pylons import c
        rval = False
        for e in errors:
            if e in c.errors:
                # get list of params checked to generate this error
                # if they exist, make sure they match input checked
                fields = c.errors[e].fields
                if input and fields and input not in fields:
                    continue
                self._has_errors.add(e)
                rval = True
                self.find("." + e).show().html(c.errors[e].message).end()
            else:
                self.find("." + e).html("").end()
        if rval and input:
            self.focus_input(input)
        return rval

    def clear_errors(self, *errors):
        from pylons import c
        for e in errors:
            if e in self._has_errors:
                self._has_errors.remove(e)
                self.find("." + e).hide().html("").end()

    def new_captcha(self):
        if not self._new_captcha:
            self.captcha(get_iden())
            self._new_captcha = True
        
    def chk_captcha(self, *errors):
        if self.has_errors(None, *errors):
            self.new_captcha()
            return True

    def get_input(self, name):
        return self.find("*[name=%s]" % name)

    def set_inputs(self, **kw):
        for k, v in kw.iteritems():
            self.get_input(k).set(value = v).end()
        return self

    def focus_input(self, name):
        return self.get_input(name).focus().end()

    def set_html(self, selector, value):
        if value:
            return self.find(selector).show().html(value).end()
        return self.find(selector).hide().html("").end()


    def set(self, **kw):
        obj = self
        for k, v in kw.iteritems():
            obj = obj.attr(k, v)
        return obj


