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
# the specific language governing rig and limitations under the License.
#
# The Original Code is Reddit.
#
# The Original Developer is the Initial Developer.  The Initial Developer of the
# Original Code is CondeNet, Inc.
#
# All portions of the code written by CondeNet are Copyright (c) 2006-2010
# CondeNet, Inc. All Rights Reserved.
################################################################################
"""Pylons middleware initialization"""
from paste.cascade import Cascade
from paste.registry import RegistryManager
from paste.urlparser import URLParser, StaticURLParser
from paste.deploy.converters import asbool

from pylons import config, request, Response
from pylons.error import error_template
from pylons.middleware import ErrorDocuments, ErrorHandler, StaticJavascripts
from pylons.wsgiapp import PylonsApp, PylonsBaseWSGIApp

from r2.config.environment import load_environment
from r2.config.rewrites import rewrites
from r2.lib.utils import rstrips, is_authorized_cname
from r2.lib.jsontemplates import api_type

#middleware stuff
from r2.lib.html_source import HTMLValidationParser
from cStringIO import StringIO
import sys, tempfile, urllib, re, os, sha, subprocess
from httplib import HTTPConnection

#from pylons.middleware import error_mapper
def error_mapper(code, message, environ, global_conf=None, **kw):
    from pylons import c
    if environ.get('pylons.error_call'):
        return None
    else:
        environ['pylons.error_call'] = True

    if global_conf is None:
        global_conf = {}
    codes = [304, 401, 403, 404, 503]
    if not asbool(global_conf.get('debug')):
        codes.append(500)
    if code in codes:
        # StatusBasedForward expects a relative URL (no SCRIPT_NAME)
        d = dict(code = code, message = message)
        if environ.get('REDDIT_CNAME'):
            d['cnameframe'] = 1
        if environ.get('REDDIT_NAME'):
            d['srname'] = environ.get('REDDIT_NAME')
        if environ.get('REDDIT_TAKEDOWN'):
            d['takedown'] = environ.get('REDDIT_TAKEDOWN')

        #preserve x-sup-id when 304ing
        if code == 304:
            #check to see if c is useable
            try:
                c.test
            except TypeError:
                pass
            else:
                if c.response.headers.has_key('x-sup-id'):
                    d['x-sup-id'] = c.response.headers['x-sup-id']

        extension = environ.get("extension")
        if extension:
            url = '/error/document/.%s?%s' % (extension, urllib.urlencode(d))
        else:
            url = '/error/document/?%s' % (urllib.urlencode(d))
        return url

class DebugMiddleware(object):
    def __init__(self, app, keyword):
        self.app = app
        self.keyword = keyword

    def __call__(self, environ, start_response):
        def foo(*a, **kw):
            self.res = self.app(environ, start_response)
            return self.res
        debug = config['global_conf']['debug'].lower() == 'true'
        args = {}
        for x in environ['QUERY_STRING'].split('&'):
            x = x.split('=')
            args[x[0]] = x[1] if x[1:] else None
        if debug and self.keyword in args.keys():
            prof_arg = args.get(self.keyword)
            prof_arg = urllib.unquote(prof_arg) if prof_arg else None
            r = self.filter(foo, prof_arg = prof_arg)
            if isinstance(r, Response):
                return r(environ, start_response)
            return r
        return self.app(environ, start_response)

    def filter(self, execution_func, prof_arg = None):
        pass


class ProfileGraphMiddleware(DebugMiddleware):
    def __init__(self, app):
        DebugMiddleware.__init__(self, app, 'profile-graph')
        
    def filter(self, execution_func, prof_arg = None):
        # put thie imports here so the app doesn't choke if profiling
        # is not present (this is a debug-only feature anyway)
        import cProfile as profile
        from pstats import Stats
        from r2.lib.contrib import gprof2dot
        # profiling needs an actual file to dump to.  Everything else
        # can be mitigated with streams
        tmpfile = tempfile.NamedTemporaryFile()
        dotfile = StringIO()
        # simple cutoff validation
        try:
            cutoff = .01 if prof_arg is None else float(prof_arg)/100
        except ValueError:
            cutoff = .01
        try:
            # profile the code in the current context
            profile.runctx('execution_func()',
                           globals(), locals(), tmpfile.name)
            # parse the data
            parser = gprof2dot.PstatsParser(tmpfile.name)
            prof = parser.parse()
            # remove nodes and edges with less than cutoff work
            prof.prune(cutoff, cutoff)
            # make the dotfile
            dot = gprof2dot.DotWriter(dotfile)
            dot.graph(prof, gprof2dot.TEMPERATURE_COLORMAP)
            # convert the dotfile to PNG in local stdout
            proc = subprocess.Popen("dot -Tpng",
                                    shell = True,
                                    stdin =subprocess.PIPE,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            out, error =  proc.communicate(input = dotfile.getvalue())
            # generate the response
            r = Response()
            r.status_code = 200
            r.headers['content-type'] = "image/png"
            r.content = out
            return r
        finally:
            tmpfile.close()

class ProfilingMiddleware(DebugMiddleware):
    def __init__(self, app):
        DebugMiddleware.__init__(self, app, 'profile')

    def filter(self, execution_func, prof_arg = None):
        # put thie imports here so the app doesn't choke if profiling
        # is not present (this is a debug-only feature anyway)
        import cProfile as profile
        from pstats import Stats

        tmpfile = tempfile.NamedTemporaryFile()
        file = line = func = None
        sort_order = 'time'
        if prof_arg:
            tokens = prof_arg.split(',')
        else:
            tokens = ()

        for token in tokens:
            if token == "cum":
                sort_order = "cumulative"
            elif token == "name":
                sort_order = "name"
            else:
                try:
                    file, line = prof_arg.split(':')
                    line, func = line.split('(')
                    func = func.strip(')')
                except:
                    file = line = func = None

        try:
            profile.runctx('execution_func()',
                           globals(), locals(), tmpfile.name)
            out = StringIO()
            stats = Stats(tmpfile.name, stream=out)
            stats.sort_stats(sort_order, 'calls')

            def parse_table(t, ncol):
                table = []
                for s in t:
                    t = [x for x in s.split(' ') if x]
                    if len(t) > 1:
                        table += [t[:ncol-1] + [' '.join(t[ncol-1:])]]
                return table

            def cmp(n):
                def _cmp(x, y):
                    return 0 if x[n] == y[n] else 1 if x[n] < y[n] else -1
                return _cmp

            if not file:
                stats.print_stats()
                stats_str = out.getvalue()
                statdata = stats_str.split('\n')
                headers = '\n'.join(statdata[:6])
                table = parse_table(statdata[6:], 6)
                from r2.lib.pages import Profiling
                res = Profiling(header = headers, table = table,
                                path = request.path).render()
                return [unicode(res)]
            else:
                query = "%s:%s" % (file, line)
                stats.print_callees(query)
                stats.print_callers(query)
                statdata = out.getvalue()

                data =  statdata.split(query)
                callee = data[2].split('->')[1].split('Ordered by')[0]
                callee = parse_table(callee.split('\n'), 4)
                callee.sort(cmp(1))
                callee = [['ncalls', 'tottime', 'cputime']] + callee
                i = 4
                while '<-' not in data[i] and i < len(data): i+= 1
                caller = data[i].split('<-')[1]
                caller = parse_table(caller.split('\n'), 4)
                caller.sort(cmp(1))
                caller = [['ncalls', 'tottime', 'cputime']] + caller
                from r2.lib.pages import Profiling
                res = Profiling(header = prof_arg,
                                caller = caller, callee = callee,
                                path = request.path).render()
                return [unicode(res)]
        finally:
            tmpfile.close()

class SourceViewMiddleware(DebugMiddleware):
    def __init__(self, app):
        DebugMiddleware.__init__(self, app, 'chk_source')

    def filter(self, execution_func, prof_arg = None):
        output = execution_func()
        output = [x for x in output]
        parser = HTMLValidationParser()
        res = parser.feed(output[-1])
        return [res]

class DomainMiddleware(object):
    lang_re = re.compile(r"\A\w\w(-\w\w)?\Z")

    def __init__(self, app):
        self.app = app
        auth_cnames = config['global_conf'].get('authorized_cnames', '')
        auth_cnames = [x.strip() for x in auth_cnames.split(',')]
        # we are going to be matching with endswith, so make sure there
        # are no empty strings that have snuck in
        self.auth_cnames = filter(None, auth_cnames)

    def is_auth_cname(self, domain):
        return is_authorized_cname(domain, self.auth_cnames)

    def __call__(self, environ, start_response):
        # get base domain as defined in INI file
        base_domain = config['global_conf']['domain']
        try:
            sub_domains, request_port  = environ['HTTP_HOST'].split(':')
            environ['request_port'] = int(request_port)
        except ValueError:
            sub_domains = environ['HTTP_HOST'].split(':')[0]
        except KeyError:
            sub_domains = "localhost"

        #If the domain doesn't end with base_domain, assume
        #this is a cname, and redirect to the frame controller.
        #Ignore localhost so paster shell still works.
        #If this is an error, don't redirect
        if (not sub_domains.endswith(base_domain)
            and (not sub_domains == 'localhost')):
            environ['sub_domain'] = sub_domains
            if not environ.get('extension'):
                if environ['PATH_INFO'].startswith('/frame'):
                    return self.app(environ, start_response)
                elif self.is_auth_cname(sub_domains):
                    environ['frameless_cname'] = True
                    environ['authorized_cname'] = True
                elif ("redditSession=cname" in environ.get('HTTP_COOKIE', '')
                      and environ['REQUEST_METHOD'] != 'POST'
                      and not environ['PATH_INFO'].startswith('/error')):
                    environ['original_path'] = environ['PATH_INFO']
                    environ['FULLPATH'] = environ['PATH_INFO'] = '/frame'
                else:
                    environ['frameless_cname'] = True
            return self.app(environ, start_response)

        sub_domains = sub_domains[:-len(base_domain)].strip('.')
        sub_domains = sub_domains.split('.')

        sr_redirect = None
        for sd in list(sub_domains):
            # subdomains to disregard completely
            if sd in ('www', 'origin', 'beta', 'lab', 'pay', 'buttons', 'ssl'):
                continue
            # subdomains which change the extension
            elif sd == 'm':
                environ['reddit-domain-extension'] = 'mobile'
            elif sd == 'I':
                environ['reddit-domain-extension'] = 'compact'
            elif sd == 'i':
                environ['reddit-domain-extension'] = 'compact'
            elif sd in ('api', 'rss', 'xml', 'json'):
                environ['reddit-domain-extension'] = sd
            elif (len(sd) == 2 or (len(sd) == 5 and sd[2] == '-')) and self.lang_re.match(sd):
                environ['reddit-prefer-lang'] = sd
                environ['reddit-domain-prefix'] = sd
            else:
                sr_redirect = sd
                sub_domains.remove(sd)

        if sr_redirect and environ.get("FULLPATH"):
            r = Response()
            sub_domains.append(base_domain)
            redir = "%s/r/%s/%s" % ('.'.join(sub_domains),
                                    sr_redirect, environ['FULLPATH'])
            redir = "http://" + redir.replace('//', '/')
            r.status_code = 301
            r.headers['location'] = redir
            r.content = ""
            return r(environ, start_response)

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
        elif path.startswith("/reddits"):
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

    extensions = (('rss' , ('xml', 'text/xml; charset=UTF-8')),
                  ('xml' , ('xml', 'text/xml; charset=UTF-8')),
                  ('js' , ('js', 'text/javascript; charset=UTF-8')),
                  ('wired' , ('wired', 'text/javascript; charset=UTF-8')),
                  ('embed' , ('htmllite', 'text/javascript; charset=UTF-8')),
                  ('mobile' , ('mobile', 'text/html; charset=UTF-8')),
                  ('png' , ('png', 'image/png')),
                  ('css' , ('css', 'text/css')),
                  ('csv' , ('csv', 'text/csv; charset=UTF-8')),
                  ('api' , (api_type(), 'application/json; charset=UTF-8')),
                  ('json-html' , (api_type('html'), 'application/json; charset=UTF-8')),
                  ('json-compact' , (api_type('compact'), 'application/json; charset=UTF-8')),
                  ('compact' , ('compact', 'text/html; charset=UTF-8')),
                  ('json' , (api_type(), 'application/json; charset=UTF-8')),
                  ('i' , ('compact', 'text/html; charset=UTF-8')),
                  )

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        path = environ['PATH_INFO']
        domain_ext = environ.get('reddit-domain-extension')
        for ext, val in self.extensions:
            if ext == domain_ext or path.endswith('.' + ext):
                environ['extension'] = ext
                environ['render_style'] = val[0]
                environ['content_type'] = val[1]
                #strip off the extension
                if path.endswith('.' + ext):
                    environ['PATH_INFO'] = path[:-(len(ext) + 1)]
                break
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
        if environ['REQUEST_METHOD'] == 'POST':
            if ((cl_key not in environ)
                or int(environ[cl_key]) > self.max_size):
                r = Response()
                r.status_code = 500
                r.content = '<html><head></head><body><script type="text/javascript">parent.too_big();</script>request too big</body></html>'
                return r(environ, start_response)

        return self.app(environ, start_response)


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
                if head not in seen:
                    fixed.insert(0, (head, val))
                    seen.add(head)
            return start_response(status, fixed, exc_info)
        return self.app(environ, custom_start_response)

#god this shit is disorganized and confusing
class RedditApp(PylonsBaseWSGIApp):
    def find_controller(self, controller):
        if controller in self.controller_classes:
            return self.controller_classes[controller]

        full_module_name = self.package_name + '.controllers'
        class_name = controller.capitalize() + 'Controller'

        __import__(self.package_name + '.controllers')
        mycontroller = getattr(sys.modules[full_module_name], class_name)
        self.controller_classes[controller] = mycontroller
        return mycontroller

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

    # The Pylons WSGI app
    app = PylonsApp(base_wsgi_app=RedditApp)

    # CUSTOM MIDDLEWARE HERE (filtered by the error handling middlewares)

    # last thing first from here down
    app = CleanupMiddleware(app)

    app = LimitUploadSize(app)
    app = ProfileGraphMiddleware(app)
    app = ProfilingMiddleware(app)
    app = SourceViewMiddleware(app)

    app = DomainListingMiddleware(app)
    app = SubredditMiddleware(app)
    app = ExtensionMiddleware(app)
    app = DomainMiddleware(app)

    if asbool(full_stack):
        # Handle Python exceptions
        app = ErrorHandler(app, global_conf, error_template=error_template,
                           **config['pylons.errorware'])

        # Display error documents for 401, 403, 404 status codes (and 500 when
        # debug is disabled)
        app = ErrorDocuments(app, global_conf, mapper=error_mapper, **app_conf)

    # Establish the Registry for this application
    app = RegistryManager(app)

    # Static files
    javascripts_app = StaticJavascripts()
    static_app = StaticURLParser(config['pylons.paths']['static_files'])
    app = Cascade([static_app, javascripts_app, app])

    #add the rewrite rules
    app = RewriteMiddleware(app)

    return app
