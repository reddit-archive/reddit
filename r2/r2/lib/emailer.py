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
# All portions of the code written by CondeNet are Copyright (c) 2006-2008
# CondeNet, Inc. All Rights Reserved.
################################################################################
from email.MIMEText import MIMEText
from pylons import c,g
from pages import PasswordReset
from r2.models.account import passhash
from r2.config import cache
import os, random

def email_address(name, address):
    return '"%s" <%s>' % (name, address) if name else address

feedback = email_address('reddit feedback', g.feedback_email)

def simple_email(to, fr, subj, body):
    msg = MIMEText(body)
    msg['Subject'] = subj
    msg['From'] = fr
    msg['To'] = to
    assert not fr.startswith('-') and not to.startswith('-'), 'security'
    i, o = os.popen2(["/usr/sbin/sendmail", '-f', fr, to])
    i.write(msg.as_string())
    i.close()
    o.close()
    del i, o

def sys_email(email, body, name='', subj = lambda x: x):
    fr = (c.user.name if c.user else 'Anonymous user')
    if name and name != fr:
        fr = "%s [%s]" % (name, fr)

    fr = email_address(fr, email)
    subj = subj(fr)
    simple_email(feedback, fr, subj, body)


def feedback_email(email, body, name=''):
    sys_email(email, body, name=name, 
              subj = lambda fr: "[feedback] feedback from %s" % fr)

def ad_inq_email(email, body, name=''):
    sys_email(email, body, name=name, 
              subj = lambda fr: "[ad_inq] ad inquiry from %s" % fr)


def password_email(user):
    key = passhash(random.randint(0, 1000), user.email)
    passlink = 'http://' + c.domain + '/resetpassword/' + key
    cache.set("reset_%s" %key, user._id, time=1800)
    simple_email(user.email, 'reddit@reddit.com',
                 'reddit.com password reset',
                 PasswordReset(user=user, passlink=passlink).render(style='email'))

