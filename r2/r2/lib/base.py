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

from pylons import c, g, request, session, config, response
from pylons.controllers import WSGIController
from pylons.i18n import N_, _, ungettext, get_lang
from webob.exc import HTTPException, status_map
from r2.lib.filters import spaceCompress, _force_unicode
from r2.lib.template_helpers import get_domain
from utils import storify, string2js, read_http_date

import re, hashlib
from urllib import quote
import urllib2
import sys


#TODO hack
import logging
from r2.lib.utils import UrlParser, query_string
logging.getLogger('scgi-wsgi').setLevel(logging.CRITICAL)


def is_local_address(ip):
    # TODO: support the /20 and /24 private networks? make this configurable?
    return ip.startswith('10.')

def abort(code_or_exception=None, detail="", headers=None, comment=None,
          **kwargs):
    """Raise an HTTPException and save it in environ for use by error pages."""
    # Pylons 0.9.6 makes it really hard to get your raised HTTPException,
    # so this helper implements it manually using a familiar syntax.
    # FIXME: when we upgrade Pylons, we can replace this with raise
    #        and access environ['pylons.controller.exception']
    # NOTE: when we say "upgrade Pylons" we mean to 0.10+
    if isinstance(code_or_exception, HTTPException):
        exc = code_or_exception
    else:
        if type(code_or_exception) is type and issubclass(code_or_exception,
                                                          HTTPException):
            exc_cls = code_or_exception
        else:
            exc_cls = status_map[code_or_exception]
        exc = exc_cls(detail, headers, comment, **kwargs)
    request.environ['r2.controller.exception'] = exc
    raise exc

class BaseController(WSGIController):
    def try_pagecache(self):
        pass

    def __before__(self):
        self.pre()
        self.try_pagecache()

    def __after__(self):
        self.post()

    def __call__(self, environ, start_response):
        true_client_ip = environ.get('HTTP_TRUE_CLIENT_IP')
        ip_hash = environ.get('HTTP_TRUE_CLIENT_IP_HASH')
        forwarded_for = environ.get('HTTP_X_FORWARDED_FOR', ())
        remote_addr = environ.get('REMOTE_ADDR')

        if (g.ip_hash
            and true_client_ip
            and ip_hash
            and hashlib.md5(true_client_ip + g.ip_hash).hexdigest() \
            == ip_hash.lower()):
            request.ip = true_client_ip
        elif g.trust_local_proxies and forwarded_for and is_local_address(remote_addr):
            request.ip = forwarded_for.split(',')[-1]
        else:
            request.ip = environ['REMOTE_ADDR']

        #if x-dont-decode is set, pylons won't unicode all the paramters
        if environ.get('HTTP_X_DONT_DECODE'):
            request.charset = None

        request.get = storify(request.GET)
        request.post = storify(request.POST)
        request.referer = environ.get('HTTP_REFERER')
        request.user_agent = environ.get('HTTP_USER_AGENT')
        request.fullpath = environ.get('FULLPATH', request.path)
        request.port = environ.get('request_port')
        
        if_modified_since = environ.get('HTTP_IF_MODIFIED_SINCE')
        if if_modified_since:
            request.if_modified_since = read_http_date(if_modified_since)
        else:
            request.if_modified_since = None

        #set the function to be called
        action = request.environ['pylons.routes_dict'].get('action')
        if action:
            meth = request.method.upper()
            if meth == 'HEAD':
                meth = 'GET'

            if meth != 'OPTIONS':
                handler_name = meth + '_' + action
            else:
                handler_name = meth

            request.environ['pylons.routes_dict']['action_name'] = action
            request.environ['pylons.routes_dict']['action'] = handler_name

        return WSGIController.__call__(self, environ, start_response)

    def pre(self): pass
    def post(self): pass

    def _get_action_handler(self, name=None, method=None):
        name = name or request.environ["pylons.routes_dict"]["action_name"]
        method = method or request.method
        action = method + "_" + name
        return getattr(self, action, None)

    @classmethod
    def format_output_url(cls, url, **kw):
        """
        Helper method used during redirect to ensure that the redirect
        url (assisted by frame busting code or javasctipt) will point
        to the correct domain and not have any extra dangling get
        parameters.  The extensions are also made to match and the
        resulting url is utf8 encoded.

        Node: for development purposes, also checks that the port
        matches the request port
        """
        u = UrlParser(url)

        if u.is_reddit_url():
            # make sure to pass the port along if not 80
            if not kw.has_key('port'):
                kw['port'] = request.port

            # disentagle the cname (for urls that would have
            # cnameframe=1 in them)
            u.mk_cname(**kw)

            # make sure the extensions agree with the current page
            if c.extension:
                u.set_extension(c.extension)

        # unparse and encode it un utf8
        rv = _force_unicode(u.unparse()).encode('utf8')
        if "\n" in rv or "\r" in rv:
            abort(400)
        return rv


    @classmethod
    def intermediate_redirect(cls, form_path):
        """
        Generates a /login or /over18 redirect from the current
        fullpath, after having properly reformated the path via
        format_output_url.  The reformatted original url is encoded
        and added as the "dest" parameter of the new url.
        """
        from r2.lib.template_helpers import add_sr
        params = dict(dest=cls.format_output_url(request.url))
        if c.extension == "widget" and request.GET.get("callback"):
            params['callback'] = request.GET.get("callback")

        path = add_sr(cls.format_output_url(form_path) +
                      query_string(params))
        abort(302, location=path)

    @classmethod
    def redirect(cls, dest, code = 302):
        """
        Reformats the new Location (dest) using format_output_url and
        sends the user to that location with the provided HTTP code.
        """
        dest = cls.format_output_url(dest or "/")
        response.status_int = code
        response.headers['Location'] = dest

class EmbedHandler(urllib2.BaseHandler, urllib2.HTTPHandler,
                   urllib2.HTTPErrorProcessor, urllib2.HTTPDefaultErrorHandler):

    def http_redirect(self, req, fp, code, msg, hdrs):
        to = hdrs['Location']
        h = urllib2.HTTPRedirectHandler()
        r = h.redirect_request(req, fp, code, msg, hdrs, to)
        return embedopen.open(r)

    http_error_301 = http_redirect
    http_error_302 = http_redirect
    http_error_303 = http_redirect
    http_error_307 = http_redirect

embedopen = urllib2.OpenerDirector()
embedopen.add_handler(EmbedHandler())

def proxyurl(url):
    r = urllib2.Request(url, None, {})
    content = embedopen.open(r).read()
    return content

