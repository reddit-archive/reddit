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
# All portions of the code written by reddit are Copyright (c) 2006-2012 reddit
# Inc. All Rights Reserved.
###############################################################################

from xml.dom.minidom import Document
from httplib import HTTPSConnection
from urlparse import urlparse
import base64

from pylons.controllers.util import abort
from pylons import c, g, response
from pylons.i18n import _

from validator import *
from r2.models import *

from reddit_base import RedditController

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


def verify_ipn(parameters):
    paraemeters['cmd'] = '_notify-validate'
    try:
        safer = dict([k, v.encode('utf-8')] for k, v in parameters.items())
        params = urllib.urlencode(safer)
    except UnicodeEncodeError:
        g.log.error("problem urlencoding %r" % (parameters,))
        raise
    req = urllib2.Request(g.PAYPAL_URL, params)
    req.add_header("Content-type", "application/x-www-form-urlencoded")

    response = urllib2.urlopen(req)
    status = response.read()

    if status != "VERIFIED":
        raise ValueError("Invalid IPN response: %r" % status)


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
    if pennies >= 2999:
        months = 12 * (pennies / 2999)
        days  = 366 * (pennies / 2999)
    else:
        months = pennies / 399
        days   = 31 * months
    return (months, days)

def send_gift(buyer, recipient, months, days, signed, giftmessage):
    admintools.engolden(recipient, days)
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

    subject = sender + " just sent you reddit gold!"
    message = strings.youve_got_gold % dict(sender=md_sender, amount=amount)

    if giftmessage and giftmessage.strip():
        message += "\n\n" + strings.giftgold_note + giftmessage

    send_system_message(recipient, subject, message)

    g.log.info("%s gifted %s to %s" % (buyer.name, amount, recipient.name))

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
        giftmessage = payment_blob["giftmessage"]
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

        if not c.user_is_admin:
            if months > c.user.gold_creddits:
                raise ValueError("%s is trying to sneak around the creddit check"
                                 % c.user.name)

            c.user.gold_creddits -= months
            c.user.gold_creddit_escrow += months
            c.user._commit()

        send_gift(c.user, recipient, months, days, signed, giftmessage)

        if not c.user_is_admin:
            c.user.gold_creddit_escrow -= months
            c.user._commit()

        payment_blob["status"] = "processed"
        g.hardcache.set(blob_key, payment_blob, 86400 * 30)

        form.set_html(".status", _("the gold has been delivered!"))
        jquery("button").hide()

    @textresponse(full_sn = VLength('serial-number', 100))
    def POST_gcheckout(self, full_sn):
        if full_sn:
            short_sn = full_sn.split('-')[0]
            g.log.error( "GOOGLE CHECKOUT: %s" % short_sn)
            trans = _google_ordernum_request(short_sn)

            # get the financial details
            auth = trans.find("authorization-amount-notification")

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
            elif auth.find("financial-order-state"
                           ).contents[0] == "CHARGEABLE":
                email = str(auth.find("email").contents[0])
                payer_id = str(auth.find('buyer-id').contents[0])
                # get the "secret"
                custom = None
                cart = trans.find("shopping-cart")
                if cart:
                    for item in cart.findAll("merchant-private-item-data"):
                        custom = str(item.contents[0])
                        break
                if custom:
                    days = None
                    try:
                        pennies = int(float(trans.find("order-total"
                                                      ).contents[0])*100)
                        months, days = months_and_days_from_pennies(pennies)
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

        # More sanity checks...
        if False: # TODO: remove this line
            verify_ipn(parameters)

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
            giftmessage = payment_blob.get("giftmessage", False)
            send_gift(buyer, recipient, months, days, signed, giftmessage)
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
