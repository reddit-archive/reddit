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
from reddit_base import RedditController
from r2.lib.pages import Button, ButtonEmbed, ButtonDemoPanel, WidgetDemoPanel, \
    Bookmarklets, BoringPage
from r2.models import *
from r2.lib.strings import Score
from pylons import c, request
from validator import *
from pylons.i18n import _

class ButtonsController(RedditController):
    def buttontype(self):
        b = request.get.get('t') or 1
        try: 
            return int(b)
        except ValueError:
            return 1

    @validate(url = nop('url'),
              title = nop('title'),
              css = nop('css'))
    def GET_button_content(self, url, title, css):
        try:
            links = Link._by_url(url)
            #find the one with the highest score
            l = max(links, key = lambda x: x._score)
        
            likes = Vote.likes(c.user, l) if c.user_is_loggedin else {}
            likes = likes.get((c.user, l))
            if likes:
                likes = (True if likes._name == '1'
                         else False if likes._name == '-1'
                         else None)
        except:
            #the only time we're gonna have an empty except. we don't
            #want to return 500s in other people's pages.
            l = likes = None
            
        #disable css hack 
        if (css != 'http://blog.wired.com/css/redditsocial.css' and
            css != 'http://www.wired.com/css/redditsocial.css'): 
            css = None 

        bt = self.buttontype()
        if bt == 1:
            score_fmt = Score.points
        else:
            score_fmt = Score.number_only
            
        c.response.content = Button(button=self.buttontype(), css=css,
                                    score_fmt = score_fmt, link = l, likes = likes,
                                    url=url, title=title).render()
        return c.response

    
    @validate(buttontype = VInt('t', 1, 3),
              _height = VInt('height', 0, 300),
              _width = VInt('width', 0, 300))
    def GET_button_embed(self, buttontype, _height, _width):
        c.render_style = 'js'
        c.response_content_type = 'text/javascript; charset=UTF-8'

        buttontype = buttontype or 1
        width, height = ((130, 22), (52, 80), (70, 60))[buttontype - 1]
        if _width: width = _width
        if _height: height = _height

        bjs = ButtonEmbed(button=buttontype,
                          width=width,
                          height=height,
                          referer = request.referer).render()
        # we doing want the JS to be cached!
        c.used_cache = True
        return self.sendjs(bjs, callback='', escape=False)

    def GET_button_demo_page(self):
        return BoringPage(_("reddit buttons"),
                          show_sidebar = False, 
                          content=ButtonDemoPanel()).render()


    def GET_widget_demo_page(self):
        return BoringPage(_("reddit widget"),
                          show_sidebar = False, 
                          content=WidgetDemoPanel()).render()

    
    def GET_bookmarklets(self):
        return BoringPage(_("bookmarklets"),
                          show_sidebar = False, 
                          content=Bookmarklets()).render()

        
