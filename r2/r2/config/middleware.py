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

"""Pylons middleware initialization"""
import importlib
import re
import urllib
import tempfile
import urlparse
from threading import Lock

from paste.cascade import Cascade
from paste.registry import RegistryManager
from paste.urlparser import StaticURLParser
from paste.deploy.converters import asbool
from pylons import config, response
from pylons.middleware import ErrorDocuments, ErrorHandler
from pylons.wsgiapp import PylonsApp
from routes.middleware import RoutesMiddleware

from r2.config.environment import load_environment
from r2.config.rewrites import rewrites
from r2.config.extensions import extension_mapping, set_extension
from r2.lib.utils import is_subdomain


# patch in WebOb support for HTTP 429 "Too Many Requests"
import webob.exc
import webob.util

class HTTPTooManyRequests(webob.exc.HTTPClientError):
    code = 429
    title = 'Too Many Requests'
    explanation = ('The server has received too many requests from the client.')

webob.exc.status_map[429] = HTTPTooManyRequests
webob.util.status_reasons[429] = HTTPTooManyRequests.title

#from pylons.middleware import error_mapper
def error_mapper(code, message, environ, global_conf=None, **kw):
    if environ.get('pylons.error_call'):
        return None
    else:
        environ['pylons.error_call'] = True

    from pylons import c

    # c is not always registered with the paste registry by the time we get to
    # this error_mapper. if it's not, we can safely assume that we didn't use
    # the pagecache. one such case where this happens is the
    # DomainMiddleware-based srname.reddit.com -> reddit.com/r/srname redirect.
    try:
        if c.used_cache:
            return
    except TypeError:
        pass

    if global_conf is None:
        global_conf = {}
    codes = [304, 400, 401, 403, 404, 409, 415, 429, 503]
    if not asbool(global_conf.get('debug')):
        codes.append(500)
    if code in codes:
        # StatusBasedForward expects a relative URL (no SCRIPT_NAME)
        d = dict(code = code, message = message)

        exception = environ.get('r2.controller.exception')
        if exception:
            d['explanation'] = exception.explanation
            error_data = getattr(exception, 'error_data', None)
            if error_data:
                environ['extra_error_data'] = error_data
        
        if environ.get('REDDIT_CNAME'):
            d['cnameframe'] = 1
        if environ.get('REDDIT_NAME'):
            d['srname'] = environ.get('REDDIT_NAME')
        if environ.get('REDDIT_TAKEDOWN'):
            d['takedown'] = environ.get('REDDIT_TAKEDOWN')

        #preserve x-sup-id when 304ing
        if code == 304:
            try:
                # make sure that we're in a context where we can use SOP
                # objects (error page statics appear to not be in this context)
                response.headers
            except TypeError:
                pass
            else:
                if response.headers.has_key('x-sup-id'):
                    d['x-sup-id'] = response.headers['x-sup-id']

        extension = environ.get("extension")
        if extension:
            url = '/error/document/.%s?%s' % (extension, urllib.urlencode(d))
        else:
            url = '/error/document/?%s' % (urllib.urlencode(d))
        return url


class ProfilingMiddleware(object):
    def __init__(self, app, directory):
        self.app = app
        self.directory = directory

    def __call__(self, environ, start_response):
        import cProfile

        try:
            tmpfile = tempfile.NamedTemporaryFile(prefix='profile',
                                                  dir=self.directory,
                                                  delete=False)

            profile = cProfile.Profile()
            result = profile.runcall(self.app, environ, start_response)
            profile.dump_stats(tmpfile.name)

            return result
        finally:
            tmpfile.close()


class DomainMiddleware(object):
    lang_re = re.compile(r"\A\w\w(-\w\w)?\Z")

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        g = config['pylons.g']
        http_host = environ.get('HTTP_HOST', 'localhost').lower()
        domain, s, port = http_host.partition(':')

        # remember the port
        try:
            environ['request_port'] = int(port)
        except ValueError:
            pass

        # localhost is exempt so paster run/shell will work
        # media_domain doesn't need special processing since it's just ads
        if domain == "localhost" or is_subdomain(domain, g.media_domain):
            return self.app(environ, start_response)

        # tell reddit_base to redirect to the appropriate subreddit for
        # a legacy CNAME
        if not is_subdomain(domain, g.domain):
            environ['legacy-cname'] = domain
            return self.app(environ, start_response)

        # figure out what subdomain we're on if any
        subdomains = domain[:-len(g.domain) - 1].split('.')
        extension_subdomains = dict(m="mobile",
                                    i="compact",
                                    api="api",
                                    rss="rss",
                                    xml="xml",
                                    json="json")

        sr_redirect = None
        for subdomain in subdomains[:]:
            if subdomain in g.reserved_subdomains:
                continue

            extension = extension_subdomains.get(subdomain)
            if extension:
                environ['reddit-domain-extension'] = extension
            elif self.lang_re.match(subdomain):
                environ['reddit-prefer-lang'] = subdomain
                environ['reddit-domain-prefix'] = subdomain
            else:
                sr_redirect = subdomain
                subdomains.remove(subdomain)

        # if there was a subreddit subdomain, redirect
        if sr_redirect and environ.get("FULLPATH"):
            if not subdomains and g.domain_prefix:
                subdomains.append(g.domain_prefix)
            subdomains.append(g.domain)
            redir = "%s/r/%s/%s" % ('.'.join(subdomains),
                                    sr_redirect, environ['FULLPATH'])
            redir = "http://" + redir.replace('//', '/')

            start_response("301 Moved Permanently", [("Location", redir)])
            return [""]

        return self.app(environ, start_response)


class SubredditMiddleware(object):
    sr_pattern = re.compile(r'^/r/([^/]{2,})')

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        path = environ['PATH_INFO']
        sr = self.sr_pattern.match(path)
        if sr:
            environ['subreddit'] = sr.groups()[0]
            environ['PATH_INFO'] = self.sr_pattern.sub('', path) or '/'
        elif path.startswith(('/subreddits', '/reddits')):
            environ['subreddit'] = 'r'
        return self.app(environ, start_response)

class DomainListingMiddleware(object):
    domain_pattern = re.compile(r'\A/domain/(([-\w]+\.)+[\w]+)')

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        if not environ.has_key('subreddit'):
            path = environ['PATH_INFO']
            domain = self.domain_pattern.match(path)
            if domain:
                environ['domain'] = domain.groups()[0]
                environ['PATH_INFO'] = self.domain_pattern.sub('', path) or '/'
        return self.app(environ, start_response)

class ExtensionMiddleware(object):
    ext_pattern = re.compile(r'\.([^/]+)\Z')
    
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        path = environ['PATH_INFO']
        fname, sep, path_ext = path.rpartition('.')
        domain_ext = environ.get('reddit-domain-extension')

        ext = None
        if path_ext in extension_mapping:
            ext = path_ext
            # Strip off the extension.
            environ['PATH_INFO'] = path[:-(len(ext) + 1)]
        elif domain_ext in extension_mapping:
            ext = domain_ext

        if ext:
            set_extension(environ, ext)
        else:
            environ['render_style'] = 'html'
            environ['content_type'] = 'text/html; charset=UTF-8'

        return self.app(environ, start_response)

class RewriteMiddleware(object):
    def __init__(self, app):
        self.app = app

    def rewrite(self, regex, out_template, input):
        m = regex.match(input)
        out = out_template
        if m:
            for num, group in enumerate(m.groups('')):
                out = out.replace('$%s' % (num + 1), group)
            return out

    def __call__(self, environ, start_response):
        path = environ['PATH_INFO']
        for r in rewrites:
            newpath = self.rewrite(r[0], r[1], path)
            if newpath:
                environ['PATH_INFO'] = newpath
                break

        environ['FULLPATH'] = environ.get('PATH_INFO')
        qs = environ.get('QUERY_STRING')
        if qs:
            environ['FULLPATH'] += '?' + qs

        return self.app(environ, start_response)

class StaticTestMiddleware(object):
    def __init__(self, app, static_path, domain):
        self.app = app
        self.static_path = static_path
        self.domain = domain

    def __call__(self, environ, start_response):
        if environ['HTTP_HOST'] == self.domain:
            environ['PATH_INFO'] = self.static_path.rstrip('/') + environ['PATH_INFO']
            return self.app(environ, start_response)
        raise webob.exc.HTTPNotFound()

class LimitUploadSize(object):
    """
    Middleware for restricting the size of uploaded files (such as
    image files for the CSS editing capability).
    """
    def __init__(self, app, max_size=1024*500):
        self.app = app
        self.max_size = max_size

    def __call__(self, environ, start_response):
        cl_key = 'CONTENT_LENGTH'
        is_error = environ.get("pylons.error_call", False)
        if not is_error and environ['REQUEST_METHOD'] == 'POST':
            if cl_key not in environ:
                start_response("411 Length Required", [])
                return ['<html><body>length required</body></html>']

            try:
                cl_int = int(environ[cl_key])
            except ValueError:
                start_response("400 Bad Request", [])
                return ['<html><body>bad request</body></html>']

            if cl_int > self.max_size:
                from r2.lib.strings import string_dict
                error_msg = string_dict['css_validator_messages']['max_size'] % dict(max_size = self.max_size/1024)
                start_response("413 Too Big", [])
                return ["<html>"
                        "<head>"
                        "<script type='text/javascript'>"
                        "parent.completedUploadImage('failed',"
                        "'',"
                        "'',"
                        "[['BAD_CSS_NAME', ''], ['IMAGE_ERROR', '", error_msg,"']],"
                        "'image-upload');"
                        "</script></head><body>you shouldn\'t be here</body></html>"]

        return self.app(environ, start_response)

# TODO CleanupMiddleware seems to exist because cookie headers are being duplicated
# somewhere in the response processing chain. It should be removed as soon as we
# find the underlying issue.
class CleanupMiddleware(object):
    """
    Put anything here that should be called after every other bit of
    middleware. This currently includes the code for removing
    duplicate headers (such as multiple cookie setting).  The behavior
    here is to disregard all but the last record.
    """
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        def custom_start_response(status, headers, exc_info = None):
            fixed = []
            seen = set()
            for head, val in reversed(headers):
                head = head.lower()
                key = (head, val.split("=", 1)[0])
                if key not in seen:
                    fixed.insert(0, (head, val))
                    seen.add(key)
            return start_response(status, fixed, exc_info)
        return self.app(environ, custom_start_response)


class RedditApp(PylonsApp):
    def __init__(self, *args, **kwargs):
        super(RedditApp, self).__init__(*args, **kwargs)
        self._loading_lock = Lock()
        self._controllers = None

    def setup_app_env(self, environ, start_response):
        PylonsApp.setup_app_env(self, environ, start_response)
        self.load_controllers()

    def load_controllers(self):
        if self._controllers:
            return

        with self._loading_lock:
            if self._controllers:
                return

            controllers = importlib.import_module(self.package_name +
                                                  '.controllers')
            controllers.load_controllers()
            config['r2.plugins'].load_controllers()
            self._controllers = controllers

    def find_controller(self, controller_name):
        if controller_name in self.controller_classes:
            return self.controller_classes[controller_name]

        controller_cls = self._controllers.get_controller(controller_name)
        self.controller_classes[controller_name] = controller_cls
        return controller_cls

def make_app(global_conf, full_stack=True, **app_conf):
    """Create a Pylons WSGI application and return it

    `global_conf`
        The inherited configuration for this application. Normally from the
        [DEFAULT] section of the Paste ini file.

    `full_stack`
        Whether or not this application provides a full WSGI stack (by default,
        meaning it handles its own exceptions and errors). Disable full_stack
        when this application is "managed" by another WSGI middleware.

    `app_conf`
        The application's local configuration. Normally specified in the
        [app:<name>] section of the Paste ini file (where <name> defaults to
        main).
    """

    # Configure the Pylons environment
    load_environment(global_conf, app_conf)
    g = config['pylons.g']

    # The Pylons WSGI app
    app = RedditApp()
    app = RoutesMiddleware(app, config["routes.map"])

    # CUSTOM MIDDLEWARE HERE (filtered by the error handling middlewares)

    # last thing first from here down
    app = CleanupMiddleware(app)

    app = LimitUploadSize(app)

    profile_directory = g.config.get('profile_directory')
    if profile_directory:
        app = ProfilingMiddleware(app, profile_directory)

    app = DomainListingMiddleware(app)
    app = SubredditMiddleware(app)
    app = ExtensionMiddleware(app)
    app = DomainMiddleware(app)

    if asbool(full_stack):
        # Handle Python exceptions
        app = ErrorHandler(app, global_conf, **config['pylons.errorware'])

        # Display error documents for 401, 403, 404 status codes (and 500 when
        # debug is disabled)
        app = ErrorDocuments(app, global_conf, mapper=error_mapper, **app_conf)

    # Establish the Registry for this application
    app = RegistryManager(app)

    # Static files
    static_app = StaticURLParser(config['pylons.paths']['static_files'])
    static_cascade = [static_app, app]

    if config['r2.plugins'] and g.config['uncompressedJS']:
        plugin_static_apps = Cascade([StaticURLParser(plugin.static_dir)
                                      for plugin in config['r2.plugins']])
        static_cascade.insert(0, plugin_static_apps)
    app = Cascade(static_cascade)

    #add the rewrite rules
    app = RewriteMiddleware(app)

    if not g.config['uncompressedJS'] and g.config['debug']:
        static_fallback = StaticTestMiddleware(static_app, g.config['static_path'], g.config['static_domain'])
        app = Cascade([static_fallback, app])

    return app
