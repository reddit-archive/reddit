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

from email.MIMEText import MIMEText
import datetime
import traceback, sys, smtplib

from pylons import c, g

from r2.lib.utils import timeago
from r2.models import Email, DefaultSR, Account, Award
from r2.models.token import EmailVerificationToken, PasswordResetToken


def _feedback_email(email, body, kind, name='', reply_to = ''):
    """Function for handling feedback and ad_inq emails.  Adds an
    email to the mail queue to the feedback email account."""
    Email.handler.add_to_queue(c.user if c.user_is_loggedin else None,
                               g.feedback_email, name, email,
                               kind, body = body, reply_to = reply_to)

def _system_email(email, body, kind, reply_to = "", thing = None):
    """
    For sending email from the system to a user (reply address will be
    feedback and the name will be reddit.com)
    """
    Email.handler.add_to_queue(c.user if c.user_is_loggedin else None,
                               email, g.domain, g.feedback_email,
                               kind, body = body, reply_to = reply_to,
                               thing = thing)

def _nerds_email(body, from_name, kind):
    """
    For sending email to the nerds who run this joint
    """
    Email.handler.add_to_queue(None, g.nerds_email, from_name, g.nerds_email,
                               kind, body = body)

def _gold_email(body, to_address, from_name, kind):
    """
    For sending email to reddit gold subscribers
    """
    Email.handler.add_to_queue(None, to_address, from_name, g.goldthanks_email,
                               kind, body = body)

def verify_email(user):
    """
    For verifying an email address
    """
    from r2.lib.pages import VerifyEmail
    user.email_verified = False
    user._commit()
    Award.take_away("verified_email", user)

    token = EmailVerificationToken._new(user)
    emaillink = 'http://' + g.domain + '/verification/' + token._id
    g.log.debug("Generated email verification link: " + emaillink)

    _system_email(user.email,
                  VerifyEmail(user=user,
                              emaillink = emaillink).render(style='email'),
                  Email.Kind.VERIFY_EMAIL)

def password_email(user):
    """
    For resetting a user's password.
    """
    from r2.lib.pages import PasswordReset

    reset_count_key = "email-reset_count_%s" % user._id
    g.cache.add(reset_count_key, 0, time=3600 * 12)
    if g.cache.incr(reset_count_key) > 3:
        return False

    reset_count_global = "email-reset_count_global"
    g.cache.add(reset_count_global, 0, time=3600)
    if g.cache.incr(reset_count_global) > 1000:
        raise ValueError("Somebody's beating the hell out of the password reset box")

    token = PasswordResetToken._new(user)
    passlink = 'http://' + g.domain + '/resetpassword/' + token._id
    g.log.info("Generated password reset link: " + passlink)
    _system_email(user.email,
                  PasswordReset(user=user,
                                passlink=passlink).render(style='email'),
                  Email.Kind.RESET_PASSWORD)
    return True

def password_change_email(user):
    """Queues a system email for a password change notification."""
    from r2.lib.pages import PasswordChangeEmail

    return _system_email(user.email,
                         PasswordChangeEmail(user=user).render(style='email'),
                         Email.Kind.PASSWORD_CHANGE)

def email_change_email(user):
    """Queues a system email for a email change notification."""
    from r2.lib.pages import EmailChangeEmail

    return _system_email(user.email,
                         EmailChangeEmail(user=user).render(style='email'),
                         Email.Kind.EMAIL_CHANGE)

def feedback_email(email, body, name='', reply_to = ''):
    """Queues a feedback email to the feedback account."""
    return _feedback_email(email, body,  Email.Kind.FEEDBACK, name = name,
                           reply_to = reply_to)

def ad_inq_email(email, body, name='', reply_to = ''):
    """Queues a ad_inq email to the feedback account."""
    return _feedback_email(email, body,  Email.Kind.ADVERTISE, name = name,
                           reply_to = reply_to)

def gold_email(body, to_address, from_name=g.domain):
    return _gold_email(body, to_address, from_name, Email.Kind.GOLDMAIL)

def nerds_email(body, from_name=g.domain):
    """Queues a feedback email to the nerds running this site."""
    return _nerds_email(body, from_name, Email.Kind.NERDMAIL)

def share(link, emails, from_name = "", reply_to = "", body = ""):
    """Queues a 'share link' email."""
    now = datetime.datetime.now(g.tz)
    ival = now - timeago(g.new_link_share_delay)
    date = max(now,link._date + ival)
    Email.handler.add_to_queue(c.user, emails, from_name, g.share_reply,
                               Email.Kind.SHARE, date = date,
                               body = body, reply_to = reply_to,
                               thing = link)

def send_queued_mail(test = False):
    """sends mail from the mail queue to smtplib for delivery.  Also,
    on successes, empties the mail queue and adds all emails to the
    sent_mail list."""
    from r2.lib.pages import Share, Mail_Opt
    now = datetime.datetime.now(g.tz)
    if not c.site:
        c.site = DefaultSR()

    clear = False
    if not test:
        session = smtplib.SMTP(g.smtp_server)
    def sendmail(email):
        try:
            mimetext = email.to_MIMEText()
            if mimetext is None:
                print ("Got None mimetext for email from %r and to %r"
                       % (email.fr_addr, email.to_addr))
            if test:
                print mimetext.as_string()
            else:
                session.sendmail(email.fr_addr, email.to_addr,
                                 mimetext.as_string())
                email.set_sent(rejected = False)
        # exception happens only for local recipient that doesn't exist
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused,
                UnicodeDecodeError, AttributeError):
            # handle error and print, but don't stall the rest of the queue
            print "Handled error sending mail (traceback to follow)"
            traceback.print_exc(file = sys.stdout)
            email.set_sent(rejected = True)


    try:
        for email in Email.get_unsent(now):
            clear = True

            should_queue = email.should_queue()
            # check only on sharing that the mail is invalid
            if email.kind == Email.Kind.SHARE:
                if should_queue:
                    email.body = Share(username = email.from_name(),
                                       msg_hash = email.msg_hash,
                                       link = email.thing,
                                       body =email.body).render(style = "email")
                else:
                    email.set_sent(rejected = True)
                    continue
            elif email.kind == Email.Kind.OPTOUT:
                email.body = Mail_Opt(msg_hash = email.msg_hash,
                                      leave = True).render(style = "email")
            elif email.kind == Email.Kind.OPTIN:
                email.body = Mail_Opt(msg_hash = email.msg_hash,
                                      leave = False).render(style = "email")
            # handle unknown types here
            elif not email.body:
                email.set_sent(rejected = True)
                continue
            sendmail(email)

    finally:
        if not test:
            session.quit()

    # clear is true if anything was found and processed above
    if clear:
        Email.handler.clear_queue(now)



def opt_out(msg_hash):
    """Queues an opt-out email (i.e., a confirmation that the email
    address has been opted out of receiving any future mail)"""
    email, added =  Email.handler.opt_out(msg_hash)
    if email and added:
        _system_email(email, "", Email.Kind.OPTOUT)
    return email, added

def opt_in(msg_hash):
    """Queues an opt-in email (i.e., that the email has been removed
    from our opt out list)"""
    email, removed =  Email.handler.opt_in(msg_hash)
    if email and removed:
        _system_email(email, "", Email.Kind.OPTIN)
    return email, removed


def _promo_email(thing, kind, body = "", **kw):
    from r2.lib.pages import Promo_Email
    a = Account._byID(thing.author_id, True)
    body = Promo_Email(link = thing, kind = kind,
                       body = body, **kw).render(style = "email")
    return _system_email(a.email, body, kind, thing = thing,
                         reply_to = "selfservicesupport@reddit.com")


def new_promo(thing):
    return _promo_email(thing, Email.Kind.NEW_PROMO)

def promo_bid(thing, bid, start_date):
    return _promo_email(thing, Email.Kind.BID_PROMO, bid = bid,
                        start_date = start_date)

def accept_promo(thing):
    return _promo_email(thing, Email.Kind.ACCEPT_PROMO)

def reject_promo(thing, reason = ""):
    return _promo_email(thing, Email.Kind.REJECT_PROMO, reason)

def queue_promo(thing, bid, trans_id):
    return _promo_email(thing, Email.Kind.QUEUED_PROMO, bid = bid,
                        trans_id = trans_id)

def live_promo(thing):
    return _promo_email(thing, Email.Kind.LIVE_PROMO)

def finished_promo(thing):
    return _promo_email(thing, Email.Kind.FINISHED_PROMO)


def send_html_email(to_addr, from_addr, subject, html, subtype="html"):
    from r2.lib.filters import _force_utf8
    msg = MIMEText(_force_utf8(html), subtype)
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr

    session = smtplib.SMTP(g.smtp_server)
    session.sendmail(from_addr, to_addr, msg.as_string())
    session.quit()
