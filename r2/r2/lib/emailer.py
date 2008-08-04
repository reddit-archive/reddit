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
from r2.models import passhash, Email, Default, has_opted_out
from r2.config import cache
import os, random, datetime
import smtplib, traceback, sys

def email_address(name, address):
    return '"%s" <%s>' % (name, address) if name else address
feedback = email_address('reddit feedback', g.feedback_email)

def send_mail(msg, fr, to):
    session = smtplib.SMTP(g.smtp_server)
    session.sendmail(fr, to, msg.as_string())
    session.quit()

def simple_email(to, fr, subj, body):
    def utf8(s):
        return s.encode('utf8') if isinstance(s, unicode) else s
    msg = MIMEText(utf8(body))
    msg.set_charset('utf8')
    msg['To']      = utf8(to)
    msg['From']    = utf8(fr)
    msg['Subject'] = utf8(subj)
    send_mail(msg, fr, to)

def password_email(user):
    key = passhash(random.randint(0, 1000), user.email)
    passlink = 'http://' + c.domain + '/resetpassword/' + key
    cache.set("reset_%s" %key, user._id, time=1800)
    simple_email(user.email, 'reddit@reddit.com',
                 'reddit.com password reset',
                 PasswordReset(user=user, passlink=passlink).render(style='email'))


def _feedback_email(email, body, kind, name='', reply_to = ''):
    """Function for handling feedback and ad_inq emails.  Adds an
    email to the mail queue to the feedback email account."""
    Email.handler.add_to_queue(c.user if c.user_is_loggedin else None, 
                               None, [feedback], name, email, 
                               datetime.datetime.now(), 
                               request.ip, kind, body = body, 
                               reply_to = reply_to)

def feedback_email(email, body, name='', reply_to = ''):
    """Queues a feedback email to the feedback account."""
    return _feedback_email(email, body,  Email.Kind.FEEDBACK, name = name, 
                           reply_to = reply_to)

def ad_inq_email(email, body, name='', reply_to = ''):
    """Queues a ad_inq email to the feedback account."""
    return _feedback_email(email, body,  Email.Kind.ADVERTISE, name = name,
                           reply_to = reply_to)

    
def share(link, emails, from_name = "", reply_to = "", body = ""):
    """Queues a 'share link' email."""
    now = datetime.datetime.now(g.tz)
    ival = now - timeago(g.new_link_share_delay)
    date = max(now,link._date + ival)
    Email.handler.add_to_queue(c.user, link, emails, from_name, g.share_reply,
                               date, request.ip, Email.Kind.SHARE,
                               body = body, reply_to = reply_to)
                               
def send_queued_mail():
    """sends mail from the mail queue to smtplib for delivery.  Also,
    on successes, empties the mail queue and adds all emails to the
    sent_mail list."""
    now = datetime.datetime.now(g.tz)
    if not c.site:
        c.site = Default

    clear = False
    session = smtplib.SMTP(g.smtp_server)
    # convienence funciton for sending the mail to the singly-defined session and
    # marking the mail as read.
    def sendmail(email):
        try:
            session.sendmail(email.fr_addr, email.to_addr,
                             email.to_MIMEText().as_string())
            email.set_sent()
        # exception happens only for local recipient that doesn't exist
        except smtplib.SMTPRecipientsRefused:
            # handle error and print, but don't stall the rest of the queue
	    print "Handled error sending mail (traceback to follow)"
	    traceback.print_exc(file = sys.stdout)
        

    try:
        for email in Email.get_unsent(now):
            clear = True

            should_queue = email.should_queue()
            # check only on sharing that the mail is invalid 
            if email.kind == Email.Kind.SHARE and should_queue:
                email.body = Share(username = email.from_name(),
                                   msg_hash = email.msg_hash,
                                   link = email.thing,
                                   body = email.body).render(style = "email")
                email.subject = _("[reddit] %(user)s has shared a link with you") % \
                                {"user": email.from_name()}
                sendmail(email)
            elif email.kind == Email.Kind.OPTOUT:
                email.body = Mail_Opt(msg_hash = email.msg_hash,
                                      leave = True).render(style = "email")
                email.subject = _("[reddit] email removal notice")
                sendmail(email)
                
            elif email.kind == Email.Kind.OPTIN:
                email.body = Mail_Opt(msg_hash = email.msg_hash,
                                      leave = False).render(style = "email")
                email.subject = _("[reddit] email addition notice")
                sendmail(email)

            elif email.kind in (Email.Kind.FEEDBACK, Email.Kind.ADVERTISE):
                if email.kind == Email.Kind.FEEDBACK:
                    email.subject = "[feedback] feedback from '%s'" % \
                                    email.from_name()
                else:
                    email.subject = "[ad_inq] feedback from '%s'" % \
                                    email.from_name()
                sendmail(email)
            # handle failure
            else:
                email.set_sent(rejected = True)

    finally:
        session.quit()
        
    # clear is true if anything was found and processed above
    if clear:
        Email.handler.clear_queue(now)
            


def opt_out(msg_hash):
    """Queues an opt-out email (i.e., a confirmation that the email
    address has been opted out of receiving any future mail)"""
    email, added =  Email.handler.opt_out(msg_hash)
    if email and added:
        Email.handler.add_to_queue(None, None, [email], "reddit.com",
                                   datetime.datetime.now(g.tz),
                                   '127.0.0.1', Email.Kind.OPTOUT)
    return email, added
        
def opt_in(msg_hash):
    """Queues an opt-in email (i.e., that the email has been removed
    from our opt out list)"""
    email, removed =  Email.handler.opt_in(msg_hash)
    if email and removed:
        Email.handler.add_to_queue(None, None, [email], "reddit.com",
                                   datetime.datetime.now(g.tz),
                                   '127.0.0.1', Email.Kind.OPTIN)
    return email, removed
