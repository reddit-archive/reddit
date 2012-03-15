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
# All portions of the code written by CondeNet are Copyright (c) 2006-2010
# CondeNet, Inc. All Rights Reserved.
################################################################################
from listingcontroller import ListingController
from listingcontroller import HotController
from listingcontroller import SavedController
from listingcontroller import NewController
from listingcontroller import BrowseController
from listingcontroller import MessageController
from listingcontroller import RedditsController
from listingcontroller import ByIDController as ByidController
from listingcontroller import RandomrisingController
from listingcontroller import UserController
from listingcontroller import CommentsController

from listingcontroller import MyredditsController

from feedback import FeedbackController
from front import FormsController
from front import FrontController
from health import HealthController
from buttons import ButtonsController
from buttons import ButtonjsController
from captcha import CaptchaController
from embed import EmbedController
from error import ErrorController
from post import PostController
from toolbar import ToolbarController
from awards import AwardsController
from ads import AdsController
from usage import UsageController
from errorlog import ErrorlogController
from promotecontroller import PromoteController
from mediaembed import MediaembedController
from mediaembed import AdController

from querycontroller import QueryController

try:
    from r2admin.controllers.adminapi import ApiController
except ImportError:
    from api import ApiController

from api import ApiminimalController, ApihelpController
from apiv1 import APIv1Controller as Apiv1Controller
from oauth2 import OAuth2FrontendController as Oauth2frontendController
from oauth2 import OAuth2AccessController as Oauth2accessController
from admin import AdminController
from redirect import RedirectController
from ipn import IpnController
