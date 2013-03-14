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

from pylons import g

from r2.lib.db.thing import NotFound
from r2.lib.utils import Storage
from r2.lib.export import export
from r2.models.bidding import Bid, CustomerID, PayID

from r2.lib.authorize.api import (
    Address,
    AuthorizeNetException,
    CreateCustomerPaymentProfileRequest,
    CreateCustomerProfileRequest,
    CreateCustomerProfileTransactionRequest,
    CreditCard,
    GetCustomerProfileRequest,
    Order,
    ProfileTransAuthOnly,
    ProfileTransPriorAuthCapture,
    ProfileTransVoid,
    UpdateCustomerPaymentProfileRequest,
)

__all__ = []

# useful test data:
test_card = dict(AMEX       = ("370000000000002"  , 1234),
                 DISCOVER   = ("6011000000000012" , 123),
                 MASTERCARD = ("5424000000000015" , 123),
                 VISA       = ("4007000000027"    , 123),
                 # visa card which generates error codes based on the amount
                 ERRORCARD  = ("4222222222222"    , 123))

test_card = Storage((k, CreditCard(cardNumber=x,
                                   expirationDate="2011-11",
                                   cardCode=y)) for k, (x, y) in
                    test_card.iteritems())

test_address = Address(firstName="John",
                       lastName="Doe",
                       address="123 Fake St.",
                       city="Anytown",
                       state="MN",
                       zip="12346")


@export
def get_account_info(user, recursed=False): 
    # if we don't have an ID for the user, try to make one
    if not CustomerID.get_id(user):
        cust_id = CreateCustomerProfileRequest(user).make_request()

    # if we do have a customerid, we should be able to fetch it from authorize
    try:
        u, data = GetCustomerProfileRequest(user).make_request()
    except AuthorizeNetException:
        u = None

    # if the user and the returned user don't match, delete the
    # current customer_id and recurse
    if u != user:
        if not recursed:
            CustomerID.delete(user)
            return get_account_info(user, True)
        else:
            raise AuthorizeNetException, "error creating user"
    return data


@export
def edit_profile(user, address, creditcard, pay_id=None):
    if pay_id:
        return UpdateCustomerPaymentProfileRequest(
            user, pay_id, address, creditcard).make_request()
    else:
        return CreateCustomerPaymentProfileRequest(
            user, address, creditcard).make_request()


def _make_transaction(trans_cls, amount, user, pay_id,
                      order=None, trans_id=None, test=None):
    """
    private function for handling transactions (since the data is
    effectively the same regardless of trans_cls)
    """
    # format the amount
    if amount:
        amount = "%.2f" % amount
    # lookup customer ID
    cust_id = CustomerID.get_id(user)
    # create a new transaction
    trans = trans_cls(amount, cust_id, pay_id, trans_id=trans_id,
                      order=order)
    extra = {}
    # the optional test field makes the transaction a test, and will
    # make the response be the error code corresponding to int(test).
    if isinstance(test, int):
        extra = dict(x_test_request="TRUE",
                     x_card_num=test_card.ERRORCARD.cardNumber,
                     x_amount=test)

    # using the transaction, generate a transaction request and make it
    req = CreateCustomerProfileTransactionRequest(transaction=trans,
                                                  extraOptions=extra)
    return req.make_request()


@export
def auth_transaction(amount, user, payid, thing, campaign, test=None):
    # use negative pay_ids to identify freebies, coupons, or anything
    # that doesn't require a CC.
    if payid < 0:
        trans_id = -thing._id
        # update previous freebie transactions if we can
        try:
            bid = Bid.one(thing_id=thing._id,
                          transaction=trans_id,
                          campaign=campaign)
            bid.bid = amount
            bid.auth()
        except NotFound:
            bid = Bid._new(trans_id, user, payid, thing._id, amount, campaign)
        return bid.transaction, ""

    elif int(payid) in PayID.get_ids(user):
        order = Order(invoiceNumber="T%dC%d" % (thing._id, campaign))
        success, res = _make_transaction(ProfileTransAuthOnly,
                                         amount, user, payid,
                                         order=order, test=test)
        if success:
            if test:
                return auth_transaction(amount, user, -1, thing, campaign,
                                        test = test)
            else:
                Bid._new(res.trans_id, user, payid, thing._id, amount, campaign)
                return res.trans_id, ""
        elif res is None:
            # we are in test mode!
            return auth_transaction(amount, user, -1, thing, test=test)
        # duplicate transaction, which is bad, but not horrible.  Log
        # the transaction id, creating a new bid if necessary. 
        elif res.trans_id and (res.response_code, res.response_reason_code) == (3,11):
            g.log.error("Authorize.net duplicate trans %d on campaign %d" % 
                        (res.trans_id, campaign))
            try:
                Bid.one(res.trans_id, campaign=campaign)
            except NotFound:
                Bid._new(res.trans_id, user, payid, thing._id, amount, campaign)
        return res.trans_id, res.response_reason_text


@export
def void_transaction(user, trans_id, campaign, test=None):
    bid =  Bid.one(transaction=trans_id, campaign=campaign)
    bid.void()
    if trans_id > 0:
        res = _make_transaction(ProfileTransVoid,
                                None, user, None, trans_id=trans_id,
                                test=test)
        return res


@export
def is_charged_transaction(trans_id, campaign):
    if not trans_id: return False # trans_id == 0 means no bid
    bid =  Bid.one(transaction=trans_id, campaign=campaign)
    return bid.is_charged()


@export
def charge_transaction(user, trans_id, campaign, test=None):
    bid =  Bid.one(transaction=trans_id, campaign=campaign)
    if not bid.is_charged():
        bid.charged()
        if trans_id < 0:
            # freebies are automatically authorized
            return True
        elif bid.account_id == user._id:
            res = _make_transaction(ProfileTransPriorAuthCapture,
                                    bid.bid, user,
                                    bid.pay_id, trans_id=trans_id,
                                    test=test)
            return bool(res)

    # already charged
    return True
