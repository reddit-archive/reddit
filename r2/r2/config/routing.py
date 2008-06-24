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
"""
Setup your Routes options here
"""
import os
from routes import Mapper
import admin_routes

def make_map(global_conf={}, app_conf={}):
    map = Mapper()
    mc = map.connect

    admin_routes.add(mc)
    
    mc('/login',    controller='front', action='login')
    mc('/logout',   controller='front', action='logout')
    mc('/adminon',  controller='front', action='adminon')
    mc('/adminoff', controller='front', action='adminoff')
    mc('/submit',   controller='front', action='submit')
    mc('/validuser',   controller='front', action='validuser')

    mc('/over18',   controller='post', action='over18')
    
    mc('/search', controller='front', action='search')
    
    mc('/about/:location', controller='front', 
       action='editreddit', location = 'about')
    
    mc('/reddits/create', controller='front', action='newreddit')
    mc('/reddits/search', controller='front', action='search_reddits')
    mc('/reddits/:where', controller='reddits', action='listing',
       where = 'popular',
       requirements=dict(where="popular|new|banned"))
    
    mc('/reddits/mine/:where', controller='myreddits', action='listing',
       where='subscriber',
       requirements=dict(where='subscriber|contributor|moderator'))
    
    mc('/buttons', controller='buttons', action='button_demo_page')
    #the frame
    mc('/button_content', controller='buttons', action='button_content')
    #/button.js - the embed
    mc('/button', controller='buttons', action='button_embed')
    
    mc('/widget', controller='buttons', action='widget_demo_page')
    mc('/bookmarklets', controller='buttons', action='bookmarklets')
    
    mc('/stats', controller='front', action='stats')
    
    mc('/feedback', controller='feedback', action='feedback')
    mc('/ad_inq',   controller='feedback', action='ad_inq')
    
    mc('/admin/i18n', controller='i18n', action='list')
    mc('/admin/i18n/:action', controller='i18n')
    mc('/admin/i18n/:action/:lang', controller='i18n')
    
    mc('/user/:username/:location', controller='front', action='user',
       location='overview')
    
    mc('/prefs/:location', controller='front',
       action='prefs', location='options')
    
    mc('/info/0:name/*rest', controller = 'front', action='oldinfo')
    
    mc('/info/:article/comments/:comment',
       controller='front', action='comments',
       comment = None)
    mc('/info/:article/related', controller='front',
       action = 'related')
    mc('/info/:article/details', controller='front',
       action = 'details')
    
    mc('/', controller='hot', action='listing')
    
    listing_controllers = "hot|saved|toplinks|new|recommended|normalized|randomrising"
    
    mc('/:controller', action='listing',
       requirements=dict(controller=listing_controllers))

    mc('/:sort', controller='browse', sort='top', action = 'listing',
       requirements = dict(sort = 'top|controversial'))
    
    mc('/message/compose', controller='message', action='compose')
    mc('/message/:where', controller='message', action='listing')
    
    mc('/:action', controller='front',
       requirements=dict(action="password|random"))
    mc('/:action', controller='embed',
       requirements=dict(action="help|blog"))
    mc('/help/:anything', controller='embed', action='help')
    
    mc('/:action', controller='toolbar',
       requirements=dict(action="goto|toolbar"))
    
    mc('/resetpassword/:key', controller='front',
       action='resetpassword')
    mc('/resetpassword', controller='front',
       action='resetpassword')
    
    mc('/post/:action', controller='post',
       requirements=dict(action="options|over18"))
    
    mc('/api/:action', controller='api')
    mc('/d/:what', controller='api', action='bookmarklet')
    
    mc('/captcha/:iden', controller='captcha', action='captchaimg')

    mc('/store', controller='redirect', action='redirect',
       dest='http://store.reddit.com/index.html')
    
    # This route handles displaying the error page and 
    # graphics used in the 404/500
    # error pages. It should likely stay at the top 
    # to ensure that the error page is
    # displayed properly.
    mc('error/:action/:id', controller='error')
    
    return map

