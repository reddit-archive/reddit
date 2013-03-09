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
import os
import random

import pylons

from webob.exc import HTTPFound, HTTPMovedPermanently
from pylons.i18n import _
from pylons import c, g, request, response

try:
    # place all r2 specific imports in here.  If there is a code error, it'll
    # get caught and the stack trace won't be presented to the user in
    # production
    from r2.config import extensions
    from r2.controllers.reddit_base import RedditController, Cookies
    from r2.lib.errors import ErrorSet
    from r2.lib.filters import websafe_json
    from r2.lib import log, pages
    from r2.lib.strings import rand_strings
    from r2.lib.template_helpers import static
    from r2.models.link import Link
    from r2.models.subreddit import DefaultSR, Subreddit
except Exception, e:
    if g.debug:
        # if debug mode, let the error filter up to pylons to be handled
        raise e
    else:
        # production environment: protect the code integrity!
        print "HuffmanEncodingError: make sure your python compiles before deploying, stupid!"
        # kill this app
        os._exit(1)


redditbroke =  \
'''<html>
  <head>
    <title>reddit broke!</title>
  </head>
  <body>
    <div style="margin: auto; text-align: center">
      <p>
        <a href="/">
          <img border="0" src="%s" alt="you broke reddit" />
        </a>
      </p>
      <p>
        %s
      </p>
  </body>
</html>
'''


FAILIEN_COUNT = 3
def make_failien_url():
    failien_number = random.randint(1, FAILIEN_COUNT)
    failien_name = "youbrokeit%d.png" % failien_number
    return static(failien_name)


class ErrorController(RedditController):
    """Generates error documents as and when they are required.

    The ErrorDocuments middleware forwards to ErrorController when error
    related status codes are returned from the application.

    This behaviour can be altered by changing the parameters to the
    ErrorDocuments middleware in your config/middleware.py file.
    """
    allowed_render_styles = ('html', 'xml', 'js', 'embed', '', "compact", 'api')
    # List of admins to blame (skip the first admin, "reddit")
    # If list is empty, just blame "an admin"
    admins = g.admins[1:] or ["an admin"]
    def __before__(self):
        try:
            c.error_page = True
            RedditController.__before__(self)
        except (HTTPMovedPermanently, HTTPFound):
            # ignore an attempt to redirect from an error page
            pass
        except Exception as e:
            handle_awful_failure("ErrorController.__before__: %r" % e)

    def __after__(self): 
        try:
            RedditController.__after__(self)
        except Exception as e:
            handle_awful_failure("ErrorController.__after__: %r" % e)

    def __call__(self, environ, start_response):
        try:
            return RedditController.__call__(self, environ, start_response)
        except Exception as e:
            return handle_awful_failure("ErrorController.__call__: %r" % e)


    def send403(self):
        c.site = DefaultSR()
        if 'usable_error_content' in request.environ:
            return request.environ['usable_error_content']
        else:
            res = pages.RedditError(
                title=_("forbidden (%(domain)s)") % dict(domain=g.domain),
                message=_("you are not allowed to do that"),
                explanation=request.GET.get('explanation'))
            return res.render()

    def send404(self):
        if 'usable_error_content' in request.environ:
            return request.environ['usable_error_content']
        return pages.RedditError(_("page not found"),
                                 _("the page you requested does not exist")).render()

    def send429(self):
        retry_after = request.environ.get("retry_after")
        if retry_after:
            response.headers["Retry-After"] = str(retry_after)
            template_name = '/ratelimit_toofast.html'
        else:
            template_name = '/ratelimit_throttled.html'

        template = g.mako_lookup.get_template(template_name)
        return template.render(logo_url=static(g.default_header_url))

    def send503(self):
        retry_after = request.environ.get("retry_after")
        if retry_after:
            response.headers["Retry-After"] = str(retry_after)
        return request.environ['usable_error_content']

    def GET_document(self):
        try:
            c.errors = c.errors or ErrorSet()
            # clear cookies the old fashioned way 
            c.cookies = Cookies()

            code =  request.GET.get('code', '')
            try:
                code = int(code)
            except ValueError:
                code = 404
            srname = request.GET.get('srname', '')
            takedown = request.GET.get('takedown', "")

            # StatusBasedRedirect will override this anyway, but we need this
            # here for pagecache to see.
            response.status_int = code

            if srname:
                c.site = Subreddit._by_name(srname)

            if code in (204, 304):
                # NEVER return a content body on 204/304 or downstream
                # caches may become very confused.
                if request.GET.has_key('x-sup-id'):
                    x_sup_id = request.GET.get('x-sup-id')
                    if '\r\n' not in x_sup_id:
                        response.headers['x-sup-id'] = x_sup_id
                return ""
            elif c.render_style not in self.allowed_render_styles:
                return str(code)
            elif c.render_style in extensions.API_TYPES:
                data = request.environ.get('extra_error_data', {'error': code})
                return websafe_json(json.dumps(data))
            elif takedown and code == 404:
                link = Link._by_fullname(takedown)
                return pages.TakedownPage(link).render()
            elif code == 403:
                return self.send403()
            elif code == 429:
                return self.send429()
            elif code == 500:
                randmin = {'admin': random.choice(self.admins)}
                failien_url = make_failien_url()
                return redditbroke % (failien_url, rand_strings.sadmessages % randmin)
            elif code == 503:
                return self.send503()
            elif c.site:
                return self.send404()
            else:
                return "page not found"
        except Exception as e:
            return handle_awful_failure("ErrorController.GET_document: %r" % e)

    POST_document = PUT_document = DELETE_document = GET_document

def handle_awful_failure(fail_text):
    """
    Makes sure that no errors generated in the error handler percolate
    up to the user unless debug is enabled.
    """
    if g.debug:
        import sys
        s = sys.exc_info()
        # reraise the original error with the original stack trace
        raise s[1], None, s[2]
    try:
        # log the traceback, and flag the "path" as the error location
        import traceback
        log.write_error_summary(fail_text)
        for line in traceback.format_exc().splitlines():
            g.log.error(line)
        return redditbroke % (make_failien_url(), fail_text)
    except:
        # we are doomed.  Admit defeat
        return "This is an error that should never occur.  You win."
