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

from datetime import datetime, timedelta
from httplib import HTTPSConnection
from urlparse import urlparse
from xml.dom.minidom import Document

import base64
import json

from BeautifulSoup import BeautifulStoneSoup
from pylons import c, g, request
from pylons.i18n import _
from sqlalchemy.exc import IntegrityError
import stripe

from r2.controllers.reddit_base import RedditController
from r2.lib.errors import MessageError
from r2.lib.filters import _force_unicode, _force_utf8
from r2.lib.log import log_text
from r2.lib.strings import strings
from r2.lib.utils import randstr, tup
from r2.lib.validator import (
    nop,
    textresponse,
    validatedForm,
    VFloat,
    VInt,
    VLength,
    VPrintable,
    VUser,
)
from r2.models import (
    Account,
    account_by_payingid,
    accountid_from_paypalsubscription,
    admintools,
    cancel_subscription,
    Comment,
    create_claimed_gold,
    create_gift_gold,
    make_comment_gold_message,
    NotFound,
    retrieve_gold_transaction,
    send_system_message,
    Thing,
    update_gold_transaction,
)


def generate_blob(data):
    passthrough = randstr(15)

    g.hardcache.set("payment_blob-" + passthrough,
                    data, 86400 * 30)
    g.log.info("just set payment_blob-%s", passthrough)
    return passthrough


def get_blob(code):
    key = "payment_blob-" + code
    with g.make_lock("payment_blob", "payment_blob_lock-" + code):
        blob = g.hardcache.get(key)
        if not blob:
            raise NotFound("No payment_blob-" + code)
        if blob.get('status', None) != 'initialized':
            raise ValueError("payment_blob %s has status = %s" %
                             (code, blob.get('status', None)))
        blob['status'] = "locked"
        g.hardcache.set(key, blob, 86400 * 30)
    return key, blob

def has_blob(custom):
    if not custom:
        return False

    blob = g.hardcache.get('payment_blob-%s' % custom)
    return bool(blob)

def dump_parameters(parameters):
    for k, v in parameters.iteritems():
        g.log.info("IPN: %r = %r" % (k, v))

def check_payment_status(payment_status):
    if payment_status is None:
        payment_status = ''

    psl = payment_status.lower()

    if psl == 'completed':
        return (None, psl)
    elif psl == 'refunded':
        log_text("refund", "Just got notice of a refund.", "info")
        # TODO: something useful when this happens -- and don't
        # forget to verify first
        return ("Ok", psl)
    elif psl == 'pending':
        log_text("pending",
                 "Just got notice of a Pending, whatever that is.", "info")
        # TODO: something useful when this happens -- and don't
        # forget to verify first
        return ("Ok", psl)
    elif psl == 'reversed':
        log_text("reversal",
                 "Just got notice of a PayPal reversal.", "info")
        # TODO: something useful when this happens -- and don't
        # forget to verify first
        return ("Ok", psl)
    elif psl == 'canceled_reversal':
        log_text("canceled_reversal",
                 "Just got notice of a PayPal 'canceled reversal'.", "info")
        return ("Ok", psl)
    elif psl == '':
        return (None, psl)
    else:
        raise ValueError("Unknown IPN status: %r" % payment_status)

def check_txn_type(txn_type, psl):
    if txn_type == 'subscr_signup':
        return ("Ok", None)
    elif txn_type == 'subscr_cancel':
        return ("Ok", "cancel")
    elif txn_type == 'subscr_eot':
        return ("Ok", None)
    elif txn_type == 'subscr_failed':
        log_text("failed_subscription",
                 "Just got notice of a failed PayPal resub.", "info")
        return ("Ok", None)
    elif txn_type == 'subscr_modify':
        log_text("modified_subscription",
                 "Just got notice of a modified PayPal sub.", "info")
        return ("Ok", None)
    elif txn_type == 'send_money':
        return ("Ok", None)
    elif txn_type in ('new_case',
        'recurring_payment_suspended_due_to_max_failed_payment'):
        return ("Ok", None)
    elif txn_type == 'subscr_payment' and psl == 'completed':
        return (None, "new")
    elif txn_type == 'web_accept' and psl == 'completed':
        return (None, None)
    else:
        raise ValueError("Unknown IPN txn_type / psl %r" %
                         ((txn_type, psl),))


def existing_subscription(subscr_id, paying_id, custom):
    if subscr_id is None:
        return None

    account_id = accountid_from_paypalsubscription(subscr_id)

    if not account_id and has_blob(custom):
        # New subscription contains the user info in hardcache
        return None

    should_set_subscriber = False
    if account_id is None:
        # Payment from legacy subscription (subscr_id not set), fall back
        # to guessing the user from the paying_id
        account_id = account_by_payingid(paying_id)
        should_set_subscriber = True
        if account_id is None:
            return None

    try:
        account = Account._byID(account_id, data=True)

        if account._deleted:
            g.log.info("Just got IPN renewal for deleted account #%d"
                       % account_id)
            return "deleted account"

        if should_set_subscriber:
            if hasattr(account, "gold_subscr_id") and account.gold_subscr_id:
                g.log.warning("Attempted to set subscr_id (%s) for account (%d) "
                              "that already has one." % (subscr_id, account_id))
                return None

            account.gold_subscr_id = subscr_id
            account._commit()
    except NotFound:
        g.log.info("Just got IPN renewal for non-existent account #%d" % account_id)

    return account

def months_and_days_from_pennies(pennies):
    if pennies >= g.gold_year_price.pennies:
        years = pennies / g.gold_year_price.pennies
        months = 12 * years
        days  = 366 * years
    else:
        months = pennies / g.gold_month_price.pennies
        days   = 31 * months
    return (months, days)

def send_gift(buyer, recipient, months, days, signed, giftmessage, comment_id):
    admintools.engolden(recipient, days)

    if comment_id:
        comment = Thing._by_fullname(comment_id, data=True)
        comment._gild(buyer)
    else:
        comment = None

    if signed:
        sender = buyer.name
        md_sender = "[%s](/user/%s)" % (sender, sender)
    else:
        sender = "someone"
        md_sender = "An anonymous redditor"

    create_gift_gold (buyer._id, recipient._id, days, c.start_time, signed)

    if months == 1:
        amount = "a month"
    else:
        amount = "%d months" % months

    if not comment:
        message = strings.youve_got_gold % dict(sender=md_sender, amount=amount)

        if giftmessage and giftmessage.strip():
            message += "\n\n" + strings.giftgold_note + giftmessage + '\n\n----'
    else:
        message = strings.youve_got_comment_gold % dict(
            url=comment.make_permalink_slow(),
        )

    message += '\n\n' + strings.gold_benefits_msg
    message += '\n\n' + strings.lounge_msg % {'link': '/r/'+g.lounge_reddit}

    subject = sender + " just sent you reddit gold!"

    try:
        send_system_message(recipient, subject, message)
    except MessageError:
        g.log.error('send_gift: could not send system message')

    g.log.info("%s gifted %s to %s" % (buyer.name, amount, recipient.name))
    return comment

def _google_ordernum_request(ordernums):
    d = Document()
    n = d.createElement("notification-history-request")
    n.setAttribute("xmlns", "http://checkout.google.com/schema/2")
    d.appendChild(n)

    on = d.createElement("order-numbers")
    n.appendChild(on)

    for num in tup(ordernums):
        gon = d.createElement('google-order-number')
        gon.appendChild(d.createTextNode("%s" % num))
        on.appendChild(gon)

    return _google_checkout_post(g.GOOGLE_REPORT_URL, d.toxml("UTF-8"))

def _google_charge_and_ship(ordernum):
    d = Document()
    n = d.createElement("charge-and-ship-order")
    n.setAttribute("xmlns", "http://checkout.google.com/schema/2")
    n.setAttribute("google-order-number", ordernum)

    d.appendChild(n)

    return _google_checkout_post(g.GOOGLE_REQUEST_URL, d.toxml("UTF-8"))


def _google_checkout_post(url, params):
    u = urlparse("%s%s" % (url, g.GOOGLE_ID))
    conn = HTTPSConnection(u.hostname, u.port)
    auth = base64.encodestring('%s:%s' % (g.GOOGLE_ID, g.GOOGLE_KEY))[:-1]
    headers = {"Authorization": "Basic %s" % auth,
               "Content-type": "text/xml; charset=\"UTF-8\""}

    conn.request("POST", u.path, params, headers)
    response = conn.getresponse().read()
    conn.close()

    return BeautifulStoneSoup(response)

class IpnController(RedditController):
    # Used when buying gold with creddits
    @validatedForm(VUser(),
                   months = VInt("months"),
                   passthrough = VPrintable("passthrough", max_length=50))
    def POST_spendcreddits(self, form, jquery, months, passthrough):
        if months is None or months < 1:
            form.set_html(".status", _("nice try."))
            return

        days = months * 31

        if not passthrough:
            raise ValueError("/spendcreddits got no passthrough?")

        blob_key, payment_blob = get_blob(passthrough)
        if payment_blob["goldtype"] != "gift":
            raise ValueError("/spendcreddits payment_blob %s has goldtype %s" %
                             (passthrough, payment_blob["goldtype"]))

        signed = payment_blob["signed"]
        giftmessage = _force_unicode(payment_blob["giftmessage"])
        recipient_name = payment_blob["recipient"]

        if payment_blob["account_id"] != c.user._id:
            fmt = ("/spendcreddits payment_blob %s has userid %d " +
                   "but c.user._id is %d")
            raise ValueError(fmt % passthrough,
                             payment_blob["account_id"],
                             c.user._id)

        try:
            recipient = Account._by_name(recipient_name)
        except NotFound:
            raise ValueError("Invalid username %s in spendcreddits, buyer = %s"
                             % (recipient_name, c.user.name))

        if recipient._deleted:
            form.set_html(".status", _("that user has deleted their account"))
            return

        if not c.user_is_admin:
            if months > c.user.gold_creddits:
                raise ValueError("%s is trying to sneak around the creddit check"
                                 % c.user.name)

            c.user.gold_creddits -= months
            c.user.gold_creddit_escrow += months
            c.user._commit()

        comment_id = payment_blob.get("comment")
        comment = send_gift(c.user, recipient, months, days, signed,
                            giftmessage, comment_id)

        if not c.user_is_admin:
            c.user.gold_creddit_escrow -= months
            c.user._commit()

        payment_blob["status"] = "processed"
        g.hardcache.set(blob_key, payment_blob, 86400 * 30)

        form.set_html(".status", _("the gold has been delivered!"))
        form.find("button").hide()

        if comment:
            gilding_message = make_comment_gold_message(comment,
                                                        user_gilded=True)
            jquery.gild_comment(comment_id, gilding_message, comment.gildings)

    @textresponse(full_sn = VLength('serial-number', 100))
    def POST_gcheckout(self, full_sn):
        if full_sn:
            short_sn = full_sn.split('-')[0]
            g.log.error( "GOOGLE CHECKOUT: %s" % short_sn)
            trans = _google_ordernum_request(short_sn)

            # get the financial details
            auth = trans.find("authorization-amount-notification")

            custom = None
            cart = trans.find("shopping-cart")
            if cart:
                private_item_data = cart.find("merchant-private-item-data")
                if private_item_data:
                    custom = str(private_item_data.contents[0])

            if not auth:
                # see if the payment was declinded
                status = trans.findAll('financial-order-state')
                if 'PAYMENT_DECLINED' in [x.contents[0] for x in status]:
                    g.log.error("google declined transaction found: '%s'" %
                                short_sn)
                elif 'REVIEWING' not in [x.contents[0] for x in status]:
                    g.log.error(("google transaction not found: " +
                                 "'%s', status: %s")
                                % (short_sn, [x.contents[0] for x in status]))
                else:
                    g.log.error(("google transaction status: " +
                                 "'%s', status: %s")
                                % (short_sn, [x.contents[0] for x in status]))
                    if custom:
                        payment_blob = validate_blob(custom)
                        buyer = payment_blob['buyer']
                        subject = _('gold order')
                        msg = _('your order has been received and gold will'
                                ' be delivered shortly. please bear with us'
                                ' as google wallet payments can take up to an'
                                ' hour to complete')
                        try:
                            send_system_message(buyer, subject, msg)
                        except MessageError:
                            g.log.error('gcheckout send_system_message failed')
            elif auth.find("financial-order-state"
                           ).contents[0] == "CHARGEABLE":
                email = str(auth.find("email").contents[0])
                payer_id = str(auth.find('buyer-id').contents[0])
                if custom:
                    days = None
                    try:
                        pennies = int(float(trans.find("order-total"
                                                      ).contents[0])*100)
                        months, days = months_and_days_from_pennies(pennies)
                        if not months:
                            raise ValueError("Bad pennies for %s" % short_sn)
                        charged = trans.find("charge-amount-notification")
                        if not charged:
                            _google_charge_and_ship(short_sn)

                        parameters = request.POST.copy()
                        self.finish(parameters, "g%s" % short_sn,
                                    email, payer_id, None,
                                    custom, pennies, months, days)
                    except ValueError, e:
                        g.log.error(e)
                else:
                    raise ValueError("Got no custom blob for %s" % short_sn)

            return (('<notification-acknowledgment ' +
                     'xmlns="http://checkout.google.com/schema/2" ' +
                     'serial-number="%s" />') % full_sn)
        else:
            g.log.error("GOOGLE CHCEKOUT: didn't work")
            g.log.error(repr(list(request.POST.iteritems())))

    @textresponse(paypal_secret = VPrintable('secret', 50),
                  payment_status = VPrintable('payment_status', 20),
                  txn_id = VPrintable('txn_id', 20),
                  paying_id = VPrintable('payer_id', 50),
                  payer_email = VPrintable('payer_email', 250),
                  mc_currency = VPrintable('mc_currency', 20),
                  mc_gross = VFloat('mc_gross'),
                  custom = VPrintable('custom', 50))
    def POST_ipn(self, paypal_secret, payment_status, txn_id, paying_id,
                 payer_email, mc_currency, mc_gross, custom):

        parameters = request.POST.copy()

        # Make sure it's really PayPal
        if paypal_secret != g.PAYPAL_SECRET:
            log_text("invalid IPN secret",
                     "%s guessed the wrong IPN secret" % request.ip,
                     "warning")
            raise ValueError

        # Return early if it's an IPN class we don't care about
        response, psl = check_payment_status(payment_status)
        if response:
            return response

        # Return early if it's a txn_type we don't care about
        response, subscription = check_txn_type(parameters['txn_type'], psl)
        if subscription is None:
            subscr_id = None
        elif subscription == "new":
            subscr_id = parameters['subscr_id']
        elif subscription == "cancel":
            cancel_subscription(parameters['subscr_id'])
        else:
            raise ValueError("Weird subscription: %r" % subscription)

        if response:
            return response

        # Check for the debug flag, and if so, dump the IPN dict
        if g.cache.get("ipn-debug"):
            g.cache.delete("ipn-debug")
            dump_parameters(parameters)

        if mc_currency != 'USD':
            raise ValueError("Somehow got non-USD IPN %r" % mc_currency)

        if not (txn_id and paying_id and payer_email and mc_gross):
            dump_parameters(parameters)
            raise ValueError("Got incomplete IPN")

        pennies = int(mc_gross * 100)
        months, days = months_and_days_from_pennies(pennies)

        # Special case: autorenewal payment
        existing = existing_subscription(subscr_id, paying_id, custom)
        if existing:
            if existing != "deleted account":
                create_claimed_gold ("P" + txn_id, payer_email, paying_id,
                                     pennies, days, None, existing._id,
                                     c.start_time, subscr_id)
                admintools.engolden(existing, days)

                g.log.info("Just applied IPN renewal for %s, %d days" %
                           (existing.name, days))
            return "Ok"

        # More sanity checks that all non-autorenewals should pass:

        if not custom:
            dump_parameters(parameters)
            raise ValueError("Got IPN with txn_id=%s and no custom"
                             % txn_id)

        self.finish(parameters, "P" + txn_id,
                    payer_email, paying_id, subscr_id,
                    custom, pennies, months, days)

    def finish(self, parameters, txn_id,
               payer_email, paying_id, subscr_id,
               custom, pennies, months, days):

        blob_key, payment_blob = get_blob(custom)

        buyer_id = payment_blob.get('account_id', None)
        if not buyer_id:
            dump_parameters(parameters)
            raise ValueError("No buyer_id in IPN/GC with custom='%s'" % custom)
        try:
            buyer = Account._byID(buyer_id)
        except NotFound:
            dump_parameters(parameters)
            raise ValueError("Invalid buyer_id %d in IPN/GC with custom='%s'"
                             % (buyer_id, custom))

        if subscr_id:
            buyer.gold_subscr_id = subscr_id

        instagift = False
        if payment_blob['goldtype'] in ('autorenew', 'onetime'):
            admintools.engolden(buyer, days)

            subject = _("thanks for buying reddit gold!")

            if g.lounge_reddit:
                lounge_url = "/r/" + g.lounge_reddit
                message = strings.lounge_msg % dict(link=lounge_url)
            else:
                message = ":)"
        elif payment_blob['goldtype'] == 'creddits':
            buyer._incr("gold_creddits", months)
            buyer._commit()
            subject = _("thanks for buying creddits!")
            message = _("To spend them, visit [/gold](/gold) or your favorite person's userpage.")
        elif payment_blob['goldtype'] == 'gift':
            recipient_name = payment_blob.get('recipient', None)
            try:
                recipient = Account._by_name(recipient_name)
            except NotFound:
                dump_parameters(parameters)
                raise ValueError("Invalid recipient_name %s in IPN/GC with custom='%s'"
                                 % (recipient_name, custom))
            signed = payment_blob.get("signed", False)
            giftmessage = _force_unicode(payment_blob.get("giftmessage", ""))
            comment_id = payment_blob.get("comment")
            send_gift(buyer, recipient, months, days, signed, giftmessage, comment_id)
            instagift = True
            subject = _("thanks for giving reddit gold!")
            message = _("Your gift to %s has been delivered." % recipient.name)
        else:
            dump_parameters(parameters)
            raise ValueError("Got status '%s' in IPN/GC" % payment_blob['status'])

        # Reuse the old "secret" column as a place to record the goldtype
        # and "custom", just in case we need to debug it later or something
        secret = payment_blob['goldtype'] + "-" + custom

        if instagift:
            status="instagift"
        else:
            status="processed"

        create_claimed_gold(txn_id, payer_email, paying_id, pennies, days,
                            secret, buyer_id, c.start_time,
                            subscr_id, status=status)

        send_system_message(buyer, subject, message)

        payment_blob["status"] = "processed"
        g.hardcache.set(blob_key, payment_blob, 86400 * 30)


class GoldPaymentController(RedditController):
    name = ''
    webhook_secret = ''
    event_type_mappings = {}

    @textresponse(secret=VPrintable('secret', 50))
    def POST_goldwebhook(self, secret):
        self.validate_secret(secret)
        res = self.process_response()
        status, passthrough, transaction_id, pennies, months = res

        try:
            event_type = self.event_type_mappings[status]
        except KeyError:
            g.log.error('%s %s: unknown status %s' % (self.name,
                                                      transaction_id,
                                                      status))
            self.abort403()
        self.process_webhook(event_type, passthrough, transaction_id, pennies,
                             months)

    def validate_secret(self, secret):
        if secret != self.webhook_secret:
            g.log.error('%s: invalid webhook secret from %s' % (self.name,
                                                                request.ip))
            self.abort403() 

    @classmethod
    def process_response(cls):
        """Extract status, passthrough, transaction_id, pennies."""
        raise NotImplementedError

    def process_webhook(self, event_type, passthrough, transaction_id, pennies,
                        months):
        if event_type == 'noop':
            return

        try:
            payment_blob = validate_blob(passthrough)
        except GoldException as e:
            g.log.error('%s %s: bad payment_blob %s' % (self.name,
                                                        transaction_id,
                                                        e))
            self.abort403()

        goldtype = payment_blob['goldtype']
        buyer = payment_blob['buyer']
        recipient = payment_blob.get('recipient', None)
        signed = payment_blob.get('signed', False)
        giftmessage = payment_blob.get('giftmessage', None)
        comment = payment_blob.get('comment', None)
        comment = comment._fullname if comment else None
        existing = retrieve_gold_transaction(transaction_id)

        if event_type == 'cancelled':
            subject = 'gold payment cancelled'
            msg = ('your gold payment has been cancelled, contact '
                   '%(gold_email)s for details' % {'gold_email':
                                                   g.goldthanks_email})
            send_system_message(buyer, subject, msg)
            if existing:
                # note that we don't check status on existing, probably
                # should update gold_table when a cancellation happens
                reverse_gold_purchase(transaction_id)
        elif event_type == 'succeeded':
            if existing and existing.status == 'processed':
                g.log.info('POST_goldwebhook skipping %s' % transaction_id)
                return

            payer_email = ''
            payer_id = ''
            subscription_id = None
            complete_gold_purchase(passthrough, transaction_id, payer_email,
                                   payer_id, subscription_id, pennies, months,
                                   goldtype, buyer, recipient, signed,
                                   giftmessage, comment)
        elif event_type == 'failed':
            subject = 'gold payment failed'
            msg = ('your gold payment has failed, contact %(gold_email)s for '
                   'details' % {'gold_email': g.goldthanks_email})
            send_system_message(buyer, subject, msg)
            # probably want to update gold_table here
        elif event_type == 'refunded':
            if not (existing and existing.status == 'processed'):
                return

            subject = 'gold refund'
            msg = ('your gold payment has been refunded, contact '
                   '%(gold_email)s for details' % {'gold_email':
                                                   g.goldthanks_email})
            send_system_message(buyer, subject, msg)
            reverse_gold_purchase(transaction_id)


class StripeController(GoldPaymentController):
    name = 'stripe'
    webhook_secret = g.STRIPE_WEBHOOK_SECRET
    event_type_mappings = {
        'charge.succeeded': 'succeeded',
        'charge.failed': 'failed',
        'charge.refunded': 'refunded',
        'customer.created': 'noop',
        'customer.card.created': 'noop',
        'transfer.created': 'noop',
        'transfer.paid': 'noop',
        'balance.available': 'noop',
    }

    @classmethod
    def process_response(cls):
        event_dict = json.loads(request.body)
        event = stripe.Event.construct_from(event_dict, g.STRIPE_SECRET_KEY)
        status = event.type
        event_type = cls.event_type_mappings.get(status)
        if not event_type:
            raise ValueError('Stripe: unrecognized status %s' % status)
        elif event_type == 'noop':
            return status, None, None, None, None

        charge = event.data.object
        description = charge.description
        try:
            passthrough, buyer_name = description.split('-', 1)
        except ValueError:
            g.log.error('stripe_error on charge: %s', charge)
            raise
        transaction_id = 'S%s' % charge.id
        pennies = charge.amount
        months, days = months_and_days_from_pennies(pennies)
        return status, passthrough, transaction_id, pennies, months

    @validatedForm(VUser(),
                   token=nop('stripeToken'),
                   passthrough=VPrintable("passthrough", max_length=50),
                   pennies=VInt('pennies'),
                   months=VInt("months"))
    def POST_goldcharge(self, form, jquery, token, passthrough, pennies, months):
        """
        Submit charge to stripe.

        Called by GoldPayment form. This submits the charge to stripe, and gold
        will be applied once we receive a webhook from stripe.

        """

        try:
            payment_blob = validate_blob(passthrough)
        except GoldException as e:
            # This should never happen. All fields in the payment_blob
            # are validated on creation
            form.set_html('.status',
                          _('something bad happened, try again later'))
            g.log.debug('POST_goldcharge: %s' % e.message)
            return

        penny_months, days = months_and_days_from_pennies(pennies)
        if not months or months != penny_months:
            form.set_html('.status', _('stop trying to trick the form'))
            return

        stripe.api_key = g.STRIPE_SECRET_KEY

        try:
            customer = stripe.Customer.create(card=token)

            if (customer['active_card']['address_line1_check'] == 'fail' or
                customer['active_card']['address_zip_check'] == 'fail'):
                form.set_html('.status',
                              _('error: address verification failed'))
                form.find('.stripe-submit').removeAttr('disabled').end()
                return

            if customer['active_card']['cvc_check'] == 'fail':
                form.set_html('.status', _('error: cvc check failed'))
                form.find('.stripe-submit').removeAttr('disabled').end()
                return

            charge = stripe.Charge.create(
                amount=pennies,
                currency="usd",
                customer=customer['id'],
                description='%s-%s' % (passthrough, c.user.name)
            )
        except stripe.CardError as e:
            form.set_html('.status', 'error: %s' % e.message)
            form.find('.stripe-submit').removeAttr('disabled').end()
        except stripe.InvalidRequestError as e:
            form.set_html('.status', _('invalid request'))
        except stripe.APIConnectionError as e:
            form.set_html('.status', _('api error'))
        except stripe.AuthenticationError as e:
            form.set_html('.status', _('connection error'))
        except stripe.StripeError as e:
            form.set_html('.status', _('error'))
            g.log.error('stripe error: %s' % e)
        else:
            form.set_html('.status', _('payment submitted'))

            # webhook usually sends near instantly, send a message in case
            subject = _('gold payment')
            msg = _('your payment is being processed and gold will be'
                    ' delivered shortly')
            send_system_message(c.user, subject, msg)


class CoinbaseController(GoldPaymentController):
    name = 'coinbase'
    webhook_secret = g.COINBASE_WEBHOOK_SECRET
    event_type_mappings = {
        'completed': 'succeeded',
        'cancelled': 'cancelled',
    }

    @classmethod
    def process_response(cls):
        event_dict = json.loads(request.body)
        g.log.debug('event_dict: %s' % event_dict)
        order = event_dict['order']
        transaction_id = 'C%s' % order['id']
        status = order['status']    # new/completed/cancelled
        pennies = int(order['total_native']['cents'])
        months, days = months_and_days_from_pennies(pennies)
        passthrough = order['custom']
        return status, passthrough, transaction_id, pennies, months


class RedditGiftsController(GoldPaymentController):
    """Handle notifications of gold purchases from reddit gifts.

    Payment is handled by reddit gifts. Once an order is complete they can hit
    this route to apply gold to a user's account.

    The post should include data in the form:
    {
        'transaction_id', transaction_id,
        'goldtype': goldtype,
        'buyer': buyer name,
        'pennies': pennies,
        'months': months,
        ['recipient': recipient name,]
        ['giftmessage': message,]
        ['signed': bool,]
    }

    """

    name = 'redditgifts'
    webhook_secret = g.RG_SECRET
    event_type_mappings = {'succeeded': 'succeeded'}

    def process_response(self):
        data = request.POST

        transaction_id = 'RG%s' % data['transaction_id']
        pennies = int(data['pennies'])
        months = int(data['months'])
        status = 'succeeded'

        buyer_name = data['buyer']
        goldtype = data['goldtype']

        buyer = Account._by_name(buyer_name)

        blob = {
            'goldtype': goldtype,
            'account_id': buyer._id,
            'account_name': buyer.name,
            'status': 'initialized',
        }

        if goldtype == 'gift':
            blob['recipient'] = data['recipient']
            giftmessage = data.get('giftmessage', None)
            blob['giftmessage'] = _force_utf8(giftmessage)
            signed = data.get('signed')
            blob['signed'] = True if signed == 'True' else False

        passthrough = generate_blob(blob)

        return status, passthrough, transaction_id, pennies, months


class GoldException(Exception): pass


def validate_blob(custom):
    """Validate payment_blob and return a dict with everything looked up."""
    ret = {}

    if not custom:
        raise GoldException('no custom')

    payment_blob = g.hardcache.get('payment_blob-%s' % str(custom))
    if not payment_blob:
        raise GoldException('no payment_blob')

    if not ('account_id' in payment_blob and
            'account_name' in payment_blob):
        raise GoldException('no account_id')

    try:
        buyer = Account._byID(payment_blob['account_id'], data=True)
        ret['buyer'] = buyer
    except NotFound:
        raise GoldException('bad account_id')

    if not buyer.name.lower() == payment_blob['account_name'].lower():
        raise GoldException('buyer mismatch')

    goldtype = payment_blob['goldtype']
    ret['goldtype'] = goldtype

    if goldtype == 'gift':
        recipient_name = payment_blob.get('recipient', None)
        if not recipient_name:
            raise GoldException('gift missing recpient')
        try:
            recipient = Account._by_name(recipient_name)
            ret['recipient'] = recipient
        except NotFound:
            raise GoldException('bad recipient')
        comment_fullname = payment_blob.get('comment', None)
        if comment_fullname:
            try:
                ret['comment'] = Comment._by_fullname(comment_fullname)
            except NotFound:
                raise GoldException('bad comment')
        ret['signed'] = payment_blob.get('signed', False)
        giftmessage = payment_blob.get('giftmessage')
        giftmessage = _force_unicode(giftmessage) if giftmessage else None
        ret['giftmessage'] = giftmessage
    elif goldtype not in ('onetime', 'autorenew', 'creddits'):
        raise GoldException('bad goldtype')

    return ret


def gold_lock(user):
    return g.make_lock('gold_purchase', 'gold_%s' % user._id)


def days_from_months(months):
    if months >= 12:
        assert months % 12 == 0
        years = months / 12
        days = years * 366
    else:
        days = months * 31
    return days


def complete_gold_purchase(secret, transaction_id, payer_email, payer_id,
                           subscription_id, pennies, months, goldtype, buyer,
                           recipient, signed, giftmessage, comment):
    """After receiving a message from a payment processor, apply gold.

    Shared endpoint for all payment processing systems. Validation of gold
    purchase (sender, recipient, etc.) should happen before hitting this.

    """

    gold_recipient = recipient or buyer
    with gold_lock(gold_recipient):
        gold_recipient._sync_latest()
        days = days_from_months(months)

        if goldtype in ('onetime', 'autorenew'):
            admintools.engolden(buyer, days)
            if goldtype == 'onetime':
                subject = "thanks for buying reddit gold!"
                if g.lounge_reddit:
                    lounge_url = "/r/" + g.lounge_reddit
                    message = strings.lounge_msg % dict(link=lounge_url)
                else:
                    message = ":)"
            else:
                subject = "your reddit gold has been renewed!"
                message = ("see the details of your subscription on "
                           "[your userpage](/u/%s)" % buyer.name)

        elif goldtype == 'creddits':
            buyer._incr('gold_creddits', months)
            subject = "thanks for buying creddits!"
            message = ("To spend them, visit http://%s/gold or your favorite "
                       "person's userpage." % (g.domain))

        elif goldtype == 'gift':
            send_gift(buyer, recipient, months, days, signed, giftmessage,
                      comment)
            subject = "thanks for giving reddit gold!"
            message = "Your gift to %s has been delivered." % recipient.name

        status = 'processed'
        secret_pieces = [goldtype]
        if goldtype == 'gift':
            secret_pieces.append(recipient.name)
        secret_pieces.append(secret)
        secret = '-'.join(secret_pieces)

        try:
            create_claimed_gold(transaction_id, payer_email, payer_id, pennies,
                                days, secret, buyer._id, c.start_time,
                                subscr_id=subscription_id, status=status)
        except IntegrityError:
            g.log.error('gold: got duplicate gold transaction')

        try:
            send_system_message(buyer, subject, message)
        except MessageError:
            g.log.error('complete_gold_purchase: could not send system message')


def subtract_gold_days(user, days):
    user.gold_expiration -= timedelta(days=days)
    if user.gold_expiration < datetime.now(g.display_tz):
        user.gold = False
    user._commit()


def subtract_gold_creddits(user, num):
    user._incr('gold_creddits', -num)


def reverse_gold_purchase(transaction_id):
    transaction = retrieve_gold_transaction(transaction_id)

    if not transaction:
        raise GoldException('gold_table %s not found' % transaction_id)

    buyer = Account._byID(int(transaction.account_id), data=True)
    recipient = None
    days = transaction.days
    months = days / 31

    secret = transaction.secret
    if '{' in secret:
        secret.strip('{}') # I goofed
        pieces = secret.split(',')
    else:
        pieces = secret.split('-')
    goldtype = pieces[0]
    if goldtype == 'gift':
        recipient_name, secret = pieces[1:]
        recipient = Account._by_name(recipient_name)

    gold_recipient = recipient or buyer
    with gold_lock(gold_recipient):
        gold_recipient._sync_latest()

        if goldtype in ('onetime', 'autorenew'):
            subtract_gold_days(buyer, days)

        elif goldtype == 'creddits':
            subtract_gold_creddits(buyer, months)

        elif goldtype == 'gift':
            subtract_gold_days(recipient, days)
            subject = 'your gifted gold has been reversed'
            message = 'sorry, but the payment was reversed'
            send_system_message(recipient, subject, message)
    update_gold_transaction(transaction_id, 'reversed')
