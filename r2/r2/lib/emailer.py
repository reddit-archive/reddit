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
from pylons.i18n import _
from pylons import c, g, request
from r2.lib.pages import PasswordReset, Share, Mail_Opt
from r2.lib.utils import timeago
from r2.models import passhash, Email, Default
from r2.config import cache
import os, random, datetime
import smtplib

def email_address(name, address):
    return '"%s" <%s>' % (name, address) if name else address
feedback = email_address('reddit feedback', g.feedback_email)

def send_mail(msg, fr, to, test = False):
    if not test:
        session = smtplib.SMTP(g.smtp_server)
        session.sendmail(fr, to, msg.as_string())
        session.quit()
    else:
        g.log.debug(msg.as_string())

def simple_email(to, fr, subj, body, test = False):
    def utf8(s):
        return s.encode('utf8') if isinstance(s, unicode) else s
    msg = MIMEText(utf8(body))
    msg.set_charset('utf8')
    msg['To']      = utf8(to)
    msg['From']    = utf8(fr)
    msg['Subject'] = utf8(subj)
    send_mail(msg, fr, to, test = test)

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

def share(link, emails, from_name = ""):
    now = datetime.datetime.now(g.tz)
    ival = now - timeago(g.new_link_share_delay)
    date = max(now,link._date + ival)
    Email.handler.add_to_queue(c.user, link, emails, from_name, date,
                               request.ip, Email.Kind.SHARE)
                               
def send_queued_mail():
    now = datetime.datetime.now(g.tz)
    if not c.site:
        c.site = Default

    clear = False
    session = smtplib.SMTP(g.smtp_server)
    try:
        for email in Email.get_unsent(now):
            clear = True
            if not email.should_queue():
                continue
            elif email.kind == Email.Kind.SHARE:
                email.fr_addr = g.share_reply
                email.body = Share(username = email.from_name(),
                                   msg_hash = email.msg_hash,
                                   link = email.thing).render(style = "email")
                email.subject = _("[reddit] %(user)s has shared a link with you") % \
                                {"user": email.from_name()}
                session.sendmail(email.fr_addr, email.to_addr,
                                 email.to_MIMEText().as_string())
            elif email.kind == Email.Kind.OPTOUT:
                email.fr_addr = g.share_reply
                email.body = Mail_Opt(msg_hash = email.msg_hash,
                                      leave = True).render(style = "email")
                email.subject = _("[reddit] email removal notice")
                session.sendmail(email.fr_addr, email.to_addr,
                                 email.to_MIMEText().as_string())
                
            elif email.kind == Email.Kind.OPTIN:
                email.fr_addr = g.share_reply

                email.body = Mail_Opt(msg_hash = email.msg_hash,
                                      leave = False).render(style = "email")
                email.subject = _("[reddit] email addition notice")
                session.sendmail(email.fr_addr, email.to_addr,
                                 email.to_MIMEText().as_string())

            else:
                # handle other types of emails here
                pass
            email.set_sent()
    finally:
        session.quit()
    if clear:
        Email.handler.clear_queue(now)
            


def opt_out(msg_hash):
    email, added =  Email.handler.opt_out(msg_hash)
    if email and added:
        Email.handler.add_to_queue(None, None, [email], "reddit.com",
                                   datetime.datetime.now(g.tz),
                                   '127.0.0.1', Email.Kind.OPTOUT)
    return email, added
        
def opt_in(msg_hash):
    email, removed =  Email.handler.opt_in(msg_hash)
    if email and removed:
        Email.handler.add_to_queue(None, None, [email], "reddit.com",
                                   datetime.datetime.now(g.tz),
                                   '127.0.0.1', Email.Kind.OPTIN)
    return email, removed
