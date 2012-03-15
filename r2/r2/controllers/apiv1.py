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
from pylons import c
from r2.controllers.oauth2 import OAuth2ResourceController, require_oauth2_scope
from r2.lib.jsontemplates import IdentityJsonTemplate

class APIv1Controller(OAuth2ResourceController):
   def try_pagecache(self):
      pass

   @require_oauth2_scope("identity")
   def GET_me(self):
      """Returns the identity of the user currently authenticated via OAuth."""
      resp = IdentityJsonTemplate().data(c.oauth_user)
      return self.api_wrapper(resp)
