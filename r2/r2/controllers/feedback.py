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
from pylons import c, request
from pylons.i18n import _
from r2.lib.pages import FormPage, Feedback, Captcha

class FeedbackController(RedditController):

    def _feedback(self, name = '', email = '', message='', 
                replyto='', action=''):
        title = _("inquire about advertising on reddit") if action else ''
        captcha = Captcha() if not c.user_is_loggedin \
            or c.user.needs_captcha() else None
        if request.get.has_key("done"):
            success = _("thanks for your message! you should hear back from us shortly.")
        else:
            success = ''
            return FormPage(_("advertise") if action == 'ad_inq' \
                                else _("feedback"),
                        content = Feedback(captcha=captcha,
                                           message=message, 
                                           replyto=replyto,
                                           email=email, name=name, 
                                           success=success,
                                           action=action,
                                           title=title),
                        loginbox = False).render()


    def GET_ad_inq(self):
        return self._feedback(action='ad_inq')

    def GET_feedback(self):
        return self._feedback()
