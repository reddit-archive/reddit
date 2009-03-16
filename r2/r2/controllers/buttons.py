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
from reddit_base import RedditController
from r2.lib.pages import Button, ButtonNoBody, ButtonEmbed, ButtonLite, \
    ButtonDemoPanel, WidgetDemoPanel, Bookmarklets, BoringPage, Socialite
from r2.models import *
from r2.lib.strings import Score
from r2.lib.utils import tup, query_string
from pylons import c, request
from validator import *
from pylons.i18n import _
from r2.lib.filters import spaceCompress
from r2.controllers.listingcontroller import ListingController

class ButtonsController(RedditController):
    def buttontype(self):
        b = request.get.get('t') or 1
        try: 
            return int(b)
        except ValueError:
            return 1

    def get_wrapped_link(self, url, link = None):
        try:
            if link:
                links = [link]
            else:
                sr = None if isinstance(c.site, FakeSubreddit) else c.site
                try:
                    links = tup(Link._by_url(url, sr))
                except NotFound:
                    links = []

            if links:
                # cache the render style and reset it to html
                rs = c.render_style
                c.render_style = 'html'
                link_builder = IDBuilder([l._fullname for l in links],
                                         wrap=ListingController.builder_wrapper)
                
                # link_listing will be the one-element listing at the top
                link_listing = LinkListing(link_builder, 
                                           nextprev=False).listing()
                
                # reset the render style
                c.render_style = rs
                links = link_listing.things
            # note: even if _by_url successed or a link was passed in,
            # it is possible link_listing.things is empty if the
            # link(s) is/are members of a private reddit
            # return the link with the highest score (if more than 1)
            return max(links, key = lambda x: x._score) if links else None
        except:
            #we don't want to return 500s in other people's pages.
            import traceback
            g.log.debug("FULLPATH: get_link error in buttons code")
            g.log.debug(traceback.format_exc())


    @validate(url = VSanitizedUrl('url'),
              title = nop('title'),
              css = nop('css'),
              vote = VBoolean('vote', default=True),
              newwindow = VBoolean('newwindow'),
              width = VInt('width', 0, 800),
              link = VByName('id'))
    def GET_button_content(self, url, title, css, vote, newwindow, width, link):

        # no buttons on domain listings
        if isinstance(c.site, DomainSR):
            c.site = Default
            return self.redirect(request.path + query_string(request.GET))

        l = self.get_wrapped_link(url, link)
        if l: url = l.url

        #disable css hack 
        if (css != 'http://blog.wired.com/css/redditsocial.css' and
            css != 'http://www.wired.com/css/redditsocial.css'): 
            css = None 

        bt = self.buttontype()
        if bt == 1:
            score_fmt = Score.safepoints
        else:
            score_fmt = Score.number_only
            
        page_handler = Button
        if not vote:
            page_handler = ButtonNoBody

        if newwindow:
            target = "_new"
        else:
            target = "_parent"

        res = page_handler(button=bt, css=css,
                           score_fmt = score_fmt, link = l, 
                           url=url, title=title,
                           vote = vote, target = target,
                           bgcolor=c.bgcolor, width=width).render()
        c.response.content = spaceCompress(res)
        return c.response

    
    @validate(buttontype = VInt('t', 1, 5),
              url = VSanitizedUrl("url"),
              _height = VInt('height', 0, 300),
              _width = VInt('width', 0, 800))
    def GET_button_embed(self, buttontype, _height, _width, url):
        # no buttons on domain listings
        if isinstance(c.site, DomainSR):
            return self.abort404()
            
        c.render_style = 'js'
        c.response_content_type = 'text/javascript; charset=UTF-8'

        buttontype = buttontype or 1
        width, height = ((120, 22), (51, 69), (69, 52), (51, 52), (600, 52))[min(buttontype - 1, 4)]
        if _width: width = _width
        if _height: height = _height

        bjs = ButtonEmbed(button=buttontype,
                          width=width,
                          height=height,
                          url = url,
                          referer = request.referer).render()
        # we doing want the JS to be cached!
        c.used_cache = True
        return self.sendjs(bjs, callback='', escape=False)

    @validate(buttonimage = VInt('i', 0, 14),
              url = VSanitizedUrl('url'),
              newwindow = VBoolean('newwindow', default = False),
              styled = VBoolean('styled', default=True))
    def GET_button_lite(self, buttonimage, url, styled, newwindow):
        c.render_style = 'js'
        c.response_content_type = 'text/javascript; charset=UTF-8'
        if not url:
            url = request.referer
        if newwindow:
            target = "_new"
        else:
            target = "_parent"

        l = self.get_wrapped_link(url)
        image = 1 if buttonimage is None else buttonimage

        bjs = ButtonLite(image = image, link = l, url = l.url if l else url,
                         target = target, styled = styled).render()
        # we don't want the JS to be cached!
        c.used_cache = True
        return self.sendjs(bjs, callback='', escape=False)



    def GET_button_demo_page(self):
        # no buttons for domain listings -> redirect to top level
        if isinstance(c.site, DomainSR):
            return self.redirect('/buttons')
        return BoringPage(_("reddit buttons"),
                          show_sidebar = False, 
                          content=ButtonDemoPanel()).render()


    def GET_widget_demo_page(self):
        return BoringPage(_("reddit widget"),
                          show_sidebar = False, 
                          content=WidgetDemoPanel()).render()

    def GET_socialite_demo_page(self):
        return BoringPage(_("socialite toolbar"),
                          show_sidebar = False, 
                          content=Socialite()).render()

    
    def GET_bookmarklets(self):
        return BoringPage(_("bookmarklets"),
                          show_sidebar = False, 
                          content=Bookmarklets()).render()

        
