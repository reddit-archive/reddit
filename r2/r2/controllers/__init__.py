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

_reddit_controllers = {}
_plugin_controllers = {}

def get_controller(name):
    name = name.lower() + 'controller'
    if name in _reddit_controllers:
        return _reddit_controllers[name]
    elif name in _plugin_controllers:
        return _plugin_controllers[name]
    else:
        raise KeyError(name)

def add_controller(controller):
    name = controller.__name__.lower()
    assert name not in _plugin_controllers
    _plugin_controllers[name] = controller
    return controller

def load_controllers():
    from listingcontroller import ListingController
    from listingcontroller import HotController
    from listingcontroller import NewController
    from listingcontroller import RisingController
    from listingcontroller import BrowseController
    from listingcontroller import MessageController
    from listingcontroller import RedditsController
    from listingcontroller import ByIDController
    from listingcontroller import RandomrisingController
    from listingcontroller import UserController
    from listingcontroller import CommentsController
    from listingcontroller import GildedController

    from listingcontroller import MyredditsController

    from feedback import FeedbackController
    from front import FormsController
    from front import FrontController
    from health import HealthController
    from buttons import ButtonsController
    from captcha import CaptchaController
    from embed import EmbedController
    from error import ErrorController
    from post import PostController
    from toolbar import ToolbarController
    from awards import AwardsController
    from errorlog import ErrorlogController
    from promotecontroller import PromoteController
    from mediaembed import MediaembedController
    from mediaembed import AdController
    from policies import PoliciesController
    
    from wiki import WikiController
    from wiki import WikiApiController

    from api import ApiController
    from api import ApiminimalController
    from api_docs import ApidocsController
    from apiv1 import APIv1Controller
    from multi import MultiApiController
    from oauth2 import OAuth2FrontendController
    from oauth2 import OAuth2AccessController
    from redirect import RedirectController
    from ipn import IpnController
    from ipn import StripeController
    from ipn import CoinbaseController
    from ipn import RedditGiftsController

    _reddit_controllers.update((name.lower(), obj) for name, obj in locals().iteritems())
