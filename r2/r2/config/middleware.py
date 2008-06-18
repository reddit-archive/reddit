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
"""Pylons middleware initialization"""
from paste.cascade import Cascade
from paste.registry import RegistryManager
from paste.urlparser import StaticURLParser
from paste.deploy.converters import asbool
from paste.gzipper import make_gzip_middleware

from pylons import config, request, Response
from pylons.error import error_template
from pylons.middleware import ErrorDocuments, ErrorHandler, StaticJavascripts
from pylons.wsgiapp import PylonsApp, PylonsBaseWSGIApp

from r2.config.environment import load_environment
from r2.config.rewrites import rewrites
from r2.lib.utils import rstrips

#middleware stuff
from r2.lib.html_source import HTMLValidationParser
from cStringIO import StringIO
import sys, tempfile, urllib, re, os, sha


#from pylons.middleware import error_mapper
def error_mapper(code, message, environ, global_conf=None, **kw):                              
    if environ.get('pylons.error_call'):                                                       
        return None                                                                            
    else:                                                                                      
        environ['pylons.error_call'] = True                                                    
                                                                                               
    if global_conf is None:                                                                    
        global_conf = {}                                                                       
    codes = [401, 403, 404, 503]                                                                    
    if not asbool(global_conf.get('debug')):                                                   
        codes.append(500)                                                                      
    if code in codes:                                                                          
        # StatusBasedForward expects a relative URL (no SCRIPT_NAME)                           
        url = '/error/document/?%s' % (urllib.urlencode({'message': message,                   
                                                         'code': code}))                       
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
            return self.filter(foo, prof_arg = prof_arg)
        return self.app(environ, start_response)

    def filter(self, execution_func, prof_arg = None):
        pass

class ProfilingMiddleware(DebugMiddleware):
    def __init__(self, app):
        DebugMiddleware.__init__(self, app, 'profile')

    def filter(self, execution_func, prof_arg = None):
        import cProfile as profile
        from pstats import Stats

        tmpfile = tempfile.NamedTemporaryFile()
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
            stats.sort_stats('time', 'calls')
            
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
    lang_re = re.compile(r"^\w\w(-\w\w)?$")
    
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        # get base domain as defined in INI file
        base_domain = config['global_conf']['domain']

        sub_domains = environ['HTTP_HOST']
        if not sub_domains.endswith(base_domain):
            #if the domain doesn't end with base_domain, don't do anything
            return self.app(environ, start_response)

        sub_domains = sub_domains[:-len(base_domain)].strip('.')
        sub_domains = sub_domains.split('.')

        sr_redirect = None
        for sd in list(sub_domains):
            # subdomains to disregard completely
            if sd in ('www', 'origin', 'beta'):
                continue
            # subdomains which change the extension
            elif sd == 'm':
                environ['reddit-domain-extension'] = 'mobile'
            elif sd in ('api', 'rss', 'xml', 'json'):
                environ['reddit-domain-extension'] = sd
            elif (len(sd) == 2 or (len(sd) == 5 and sd[2] == '-')) and self.lang_re.match(sd):
                environ['reddit-prefer-lang'] = sd
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
    sr_pattern = re.compile(r'^/r/([^/]+)')
    
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

class ExtensionMiddleware(object):  
    ext_pattern = re.compile(r'\.([^/]+)$')

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        path = environ['PATH_INFO']
        ext = self.ext_pattern.findall(path)
        if ext:
            environ['extension'] = ext[0]
            environ['PATH_INFO'] = self.ext_pattern.sub('', path) or '/'
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
        
class RequestLogMiddleware(object):
    def __init__(self, log_path, process_iden, app):
        self.log_path = log_path
        self.app = app
        self.process_iden = str(process_iden)

    def __call__(self, environ, start_response):
        request = '\n'.join('%s: %s' % (k,v) for k,v in environ.iteritems()
                           if k.isupper())
        iden = self.process_iden + '-' + sha.new(request).hexdigest()

        fname = os.path.join(self.log_path, iden)
        f = open(fname, 'w')
        f.write(request)
        f.close()

        r = self.app(environ, start_response)

        if os.path.exists(fname):
            try:
                os.remove(fname)
            except OSError:
                pass
        return r


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

    app = ProfilingMiddleware(app)
    app = SourceViewMiddleware(app)

    app = DomainMiddleware(app)
    app = SubredditMiddleware(app)
    app = ExtensionMiddleware(app)

    log_path = global_conf.get('log_path')
    if log_path:
        process_iden = global_conf.get('scgi_port', 'default')
        app = RequestLogMiddleware(log_path, process_iden, app)

    #TODO: breaks on 404
    #app = make_gzip_middleware(app, app_conf)

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

    app = make_gzip_middleware(app, app_conf)

    #add the rewrite rules
    app = RewriteMiddleware(app)

    return app
