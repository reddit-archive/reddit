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
# All portions of the code written by reddit are Copyright (c) 2006-2012 reddit
# Inc. All Rights Reserved.
###############################################################################

import os.path

import pylons
import paste.fileapp
from paste.httpexceptions import HTTPFound, HTTPMovedPermanently
from pylons.middleware import error_document_template, media_path
from pylons import c, request, g
from pylons.i18n import _
import random as rand
from r2.lib.filters import safemarkdown, unsafe

try:
    # place all r2 specific imports in here.  If there is a code error, it'll get caught and
    # the stack trace won't be presented to the user in production
    from reddit_base import RedditController, Cookies
    from r2.models.subreddit import DefaultSR, Subreddit
    from r2.models.link import Link
    from r2.lib import pages
    from r2.lib.strings import strings, rand_strings
    from r2.lib.template_helpers import static
except Exception, e:
    if g.debug:
        # if debug mode, let the error filter up to pylons to be handled
        raise e
    else:
        # production environment: protect the code integrity!
        print "HuffmanEncodingError: make sure your python compiles before deploying, stupid!"
        # kill this app
        import os
        os._exit(1)

NUM_FAILIENS = 3

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
        except:
            handle_awful_failure("Error occurred in ErrorController.__before__")

    def __after__(self): 
        try:
            RedditController.__after__(self)
        except:
            handle_awful_failure("Error occurred in ErrorController.__after__")

    def __call__(self, environ, start_response):
        try:
            return RedditController.__call__(self, environ, start_response)
        except:
            return handle_awful_failure("something really awful just happened.")


    def send403(self):
        c.response.status_code = 403
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
        c.response.status_code = 404
        if 'usable_error_content' in request.environ:
            return request.environ['usable_error_content']
        return pages.RedditError(_("page not found"),
                                 _("the page you requested does not exist")).render()

    def send429(self):
        c.response.status_code = 429

        if 'retry_after' in request.environ:
            c.response.headers['Retry-After'] = str(request.environ['retry_after'])
            template_name = '/ratelimit_toofast.html'
        else:
            template_name = '/ratelimit_throttled.html'

        loader = pylons.buffet.engines['mako']['engine']
        template = loader.load_template(template_name)
        return template.render(logo_url=static(g.default_header_url))

    def send503(self):
        c.response.status_code = 503
        c.response.headers['Retry-After'] = request.environ['retry_after']
        return request.environ['usable_error_content']

    def GET_document(self):
        try:
            # clear cookies the old fashioned way 
            c.cookies = Cookies()

            code =  request.GET.get('code', '')
            try:
                code = int(code)
            except ValueError:
                code = 404
            srname = request.GET.get('srname', '')
            takedown = request.GET.get('takedown', "")
            
            if srname:
                c.site = Subreddit._by_name(srname)
            if c.render_style not in self.allowed_render_styles:
                if code not in (204, 304):
                     c.response.content = str(code)
                return c.response
            elif c.render_style == "api":
                c.response.content = "{\"error\": %s}" % code
                return c.response
            elif takedown and code == 404:
                link = Link._by_fullname(takedown)
                return pages.TakedownPage(link).render()
            elif code == 403:
                return self.send403()
            elif code == 429:
                return self.send429()
            elif code == 500:
                randmin = {'admin': rand.choice(self.admins)}
                failien_name = 'youbrokeit%d.png' % rand.randint(1, NUM_FAILIENS)
                failien_url = static(failien_name)
                return redditbroke % (failien_url, rand_strings.sadmessages % randmin)
            elif code == 503:
                return self.send503()
            elif code == 304:
                if request.GET.has_key('x-sup-id'):
                    x_sup_id = request.GET.get('x-sup-id')
                    if '\r\n' not in x_sup_id:
                        c.response.headers['x-sup-id'] = x_sup_id
                return c.response
            elif c.site:
                return self.send404()
            else:
                return "page not found"
        except:
            return handle_awful_failure("something really bad just happened.")

    POST_document = GET_document

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
        g.log.error("FULLPATH: %s" % fail_text)
        g.log.error(traceback.format_exc())
        return redditbroke % (rand.randint(1,NUM_FAILIENS), fail_text)
    except:
        # we are doomed.  Admit defeat
        return "This is an error that should never occur.  You win."
