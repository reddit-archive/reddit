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

from pylons import Response, c, g, cache, request, session, config
from pylons.controllers import WSGIController, Controller
from pylons.i18n import N_, _, ungettext, get_lang
import r2.lib.helpers as h
from r2.lib.utils import to_js
from r2.lib.filters import spaceCompress
from utils import storify, string2js

import re, md5
from urllib import quote 

#TODO hack
import logging
logging.getLogger('scgi-wsgi').setLevel(logging.CRITICAL)

class BaseController(WSGIController):
    def __after__(self):
        self.post()

    def __before__(self):
        self.pre()

    def __call__(self, environ, start_response):
        true_client_ip = environ.get('HTTP_TRUE_CLIENT_IP')
        ip_hash = environ.get('HTTP_TRUE_CLIENT_IP_HASH')
        forwarded_for = environ.get('HTTP_X_FORWARDED_FOR', ())
        remote_addr = environ.get('REMOTE_ADDR')
                
        if (g.ip_hash
            and true_client_ip
            and ip_hash
            and md5.new(true_client_ip + g.ip_hash).hexdigest() \
            == ip_hash.lower()):
            request.ip = true_client_ip
        elif remote_addr == g.proxy_addr and forwarded_for:
            request.ip = forwarded_for.split(',')[0]
        else:
            request.ip = environ['REMOTE_ADDR']

        request.get = storify(request.GET)
        request.post = storify(request.POST)
        request.referer = environ.get('HTTP_REFERER')
        request.path = environ.get('PATH_INFO')
        request.user_agent = environ.get('HTTP_USER_AGENT')
        request.fullpath = environ.get('FULLPATH', request.path)

        #set the function to be called
        action = request.environ['pylons.routes_dict'].get('action')
        if action:
            meth = request.method.upper()
            if meth == 'HEAD':
                meth = 'GET'
            request.environ['pylons.routes_dict']['action'] = \
                    meth + '_' + action

        c.response = Response()
        res = WSGIController.__call__(self, environ, start_response)
        return res
            
    def pre(self): pass
    def post(self): pass

    @staticmethod
    def redirect(dest, code = 302):
        c.response.headers['Location'] = dest
        c.response.status_code = code
        return c.response

    def sendjs(self,js, callback="document.write", escape=True):
        c.response.headers['Content-Type'] = 'text/javascript'
        c.response.content = to_js(js, callback, escape)
        return c.response

import urllib2
class EmbedHandler(urllib2.BaseHandler, urllib2.HTTPHandler, 
                   urllib2.HTTPErrorProcessor, urllib2.HTTPDefaultErrorHandler):
    @staticmethod
    def redirect(_status):
        def _redirect(url, status = None):
            MethodController.redirect(url, code = _status)
        return _redirect
    
    def http_redirect(self, req, fp, code, msg, hdrs):
        codes = [301, 302, 303, 307]
        map = dict((x, self.redirect(x)) for x in codes)
        to = hdrs['Location'].replace('reddit.infogami.com', c.domain)
        map[code](to)
        raise StopIteration

    http_error_301 = http_redirect
    http_error_302 = http_redirect
    http_error_303 = http_redirect
    http_error_307 = http_redirect

embedopen = urllib2.OpenerDirector()
embedopen.add_handler(EmbedHandler())

def proxyurl(url):
    cstrs = ['%s="%s"' % (k, v) for k, v in request.cookies.iteritems()]
    cookiestr = "; ".join(cstrs)
    headers = {"Cookie":cookiestr}

    # TODO make this work on POST
    data = None
    r = urllib2.Request(url, data, headers)
    content = embedopen.open(r).read()
    return content
    
__all__ = [__name for __name in locals().keys() if not __name.startswith('_') \
           or __name == '_']


