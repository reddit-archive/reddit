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
import os.path

import paste.fileapp
from pylons.middleware import error_document_template, media_path
from pylons import c, request, g
from pylons.i18n import _
import random as rand

try:
    # place all r2 specific imports in here.  If there is a code error, it'll get caught and
    # the stack trace won't be presented to the user in production
    from reddit_base import RedditController
    from r2.models.subreddit import Default
    from r2.lib import pages
    from r2.lib.strings import rand_strings
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
    
redditbroke =  \
'''<html>
  <head>
    <title>Reddit broke!</title>
  </head>
  <body>
    <div style="margin: auto; text-align: center">
      <p>
        <a href="/">
          <img border="0" src="/static/youbrokeit.png" alt="you broke reddit" />
        </a>
      </p>
      <p>
        %s
      </p>
  </body>
</html>
'''            

toofast =  \
'''<html>
  <head><title>service temporarily unavailable</title></head>
  <body>
    the service you request is temporarily unavailable. please try again later.
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
    def __before__(self):
        try:
            RedditController.__before__(self)
        except:
            pass

    def __after__(self): 
        try:
            RedditController.__after__(self)
        except:
            pass

    def __call__(self, environ, start_response):
        try:
            return RedditController.__call__(self, environ, start_response)
        except:
            c.response.content = "something really awful just happened"
            return c.response


    def send403(self):
        c.response.status_code = 403
        c.site = Default
        title = _("forbidden (%(domain)s)") % dict(domain=c.domain)
        return pages.BoringPage(title,  loginbox=False,
                                show_sidebar = False, 
                                content=pages.ErrorPage()).render()

    def send404(self):
        c.response.status_code = 404

        if c.site._spam and not c.user_is_admin:
            msg = _("this reddit has been banned.")
            res =  pages.BoringPage(msg, loginbox = False,
                                    show_sidebar = False, 
                                    content = pages.ErrorPage(message = msg))
            return res.render()
        else:
            c.site = Default
            ch=rand.choice(['a','b','c','d','e'])
            res = pages.BoringPage(_("page not found"),
                                   loginbox=False,
                                   show_sidebar = False, 
                                   content=pages.UnfoundPage(choice=ch))
            return res.render()

    def send503(self):
        c.response.status_code = 503
        c.response.headers['Retry-After'] = 1
        c.response.content = toofast
        return c.response

    def GET_document(self):
        try:
            code =  request.GET.get('code', '')
            if code == '500':
                return redditbroke % rand_strings.sadmessages
            elif code == '503':
                return self.send503()
            elif code == '403':
                return self.send403()
            elif c.site:
                return self.send404()
            else:
                return "page not found"
        except:
            return "something really bad just happened"

