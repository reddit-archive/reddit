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

"""
For talking to authorize.net credit card payments via their XML api.

This file consists mostly of wrapper classes for dealing with their
API, while the actual useful functions live in interaction.py
"""

import re
import socket
from httplib import HTTPSConnection
from urlparse import urlparse

from BeautifulSoup import BeautifulStoneSoup
from pylons import g
from xml.sax.saxutils import escape

from r2.lib.export import export
from r2.lib.utils import iters, Storage
from r2.models.bidding import CustomerID, PayID, ShippingAddress

__all__ = ["PROFILE_LIMIT"]


# list of the most common errors.
Errors = Storage(TESTMODE="E00009",
                 TRANSACTION_FAIL="E00027",
                 DUPLICATE_RECORD="E00039", 
                 RECORD_NOT_FOUND="E00040",
                 TOO_MANY_PAY_PROFILES="E00042",
                 TOO_MANY_SHIP_ADDRESSES="E00043")

PROFILE_LIMIT = 10 # max payment profiles per user allowed by authorize.net

@export
class AuthorizeNetException(Exception):
    def __init__(self, msg):
        # don't let CC info show up in logs
        msg = re.sub("<cardNumber>\d+(\d{4})</cardNumber>", 
                     "<cardNumber>...\g<1></cardNumber>",
                     msg)
        msg = re.sub("<cardCode>\d+</cardCode>",
                     "<cardCode>omitted</cardCode>",
                     msg)
        super(AuthorizeNetException, self).__init__(msg)



# xml tags whose content shouldn't be escaped 
_no_escape_list = ["extraOptions"]


class SimpleXMLObject(object):
    """
    All API transactions are done with authorize.net using XML, so
    here's a class for generating and extracting structured data from
    XML.
    """
    _keys = []
    def __init__(self, **kw):
        self._used_keys = self._keys if self._keys else kw.keys()
        for k in self._used_keys:
            if not hasattr(self, k):
                setattr(self, k, kw.get(k, ""))

    @staticmethod
    def simple_tag(name, content, **attrs):
        attrs = " ".join('%s="%s"' % (k, v) for k, v in attrs.iteritems())
        if attrs:
            attrs = " " + attrs
        return ("<%(name)s%(attrs)s>%(content)s</%(name)s>" %
                dict(name=name, content=content, attrs=attrs))

    def toXML(self):
        content = []
        def process(k, v):
            if isinstance(v, SimpleXMLObject):
                v = v.toXML()
            elif v is not None:
                v = unicode(v)
                if k not in _no_escape_list:
                    v = escape(v) # escape &, <, and >
            if v is not None:
                content.append(self.simple_tag(k, v))

        for k in self._used_keys:
            v = getattr(self, k)
            if isinstance(v, iters):
                for val in v:
                    process(k, val)
            else:
                process(k, v)
        return self._wrapper("".join(content))

    @classmethod
    def fromXML(cls, data):
        kw = {}
        for k in cls._keys:
            d = data.find(k.lower())
            if d and d.contents:
                kw[k] = unicode(d.contents[0])
        return cls(**kw)


    def __repr__(self):
        return "<%s {%s}>" % (self.__class__.__name__,
                              ",".join("%s=%s" % (k, repr(getattr(self, k)))
                                       for k in self._used_keys))

    def _name(self):
        name = self.__class__.__name__
        return name[0].lower() + name[1:]
    
    def _wrapper(self, content):
        return content


class Auth(SimpleXMLObject):
    _keys = ["name", "transactionKey"]


@export
class Address(SimpleXMLObject):
    _keys = ["firstName", "lastName", "company", "address",
             "city", "state", "zip", "country", "phoneNumber",
             "faxNumber",
             "customerPaymentProfileId",
             "customerAddressId" ]
    def __init__(self, **kw):
        kw['customerPaymentProfileId'] = kw.get("customerPaymentProfileId",
                                                 None)
        kw['customerAddressId'] = kw.get("customerAddressId", None)
        SimpleXMLObject.__init__(self, **kw)


@export
class CreditCard(SimpleXMLObject):
    _keys = ["cardNumber", "expirationDate", "cardCode"]


class Profile(SimpleXMLObject):
    """
    Converts a user into a Profile object.
    """
    _keys = ["merchantCustomerId", "description",
             "email", "customerProfileId", "paymentProfiles", "shipToList",
             "validationMode"]
    def __init__(self, user, paymentProfiles, address,
                 validationMode=None):
        SimpleXMLObject.__init__(self, merchantCustomerId=user._fullname,
                                 description=user.name, email="",
                                 paymentProfiles=paymentProfiles,
                                 shipToList=address,
                                 validationMode=validationMode,
                                 customerProfileId=CustomerID.get_id(user))

class PaymentProfile(SimpleXMLObject):
    _keys = ["billTo", "payment", "customerPaymentProfileId", "validationMode"]
    def __init__(self, billTo, card, paymentId=None,
                 validationMode=None):
        SimpleXMLObject.__init__(self, billTo=billTo,
                                 customerPaymentProfileId=paymentId,
                                 payment=SimpleXMLObject(creditCard=card),
                                 validationMode=validationMode)

    @classmethod
    def fromXML(cls, res):
        payid = int(res.customerpaymentprofileid.contents[0])
        return cls(Address.fromXML(res.billto),
                   CreditCard.fromXML(res.payment), payid)


@export
class Order(SimpleXMLObject):
    _keys = ["invoiceNumber", "description", "purchaseOrderNumber"]


class Transaction(SimpleXMLObject):
    _keys = ["amount", "customerProfileId", "customerPaymentProfileId",
             "transId", "order"]

    def __init__(self, amount, profile_id, pay_id, trans_id=None,
                 order=None):
        SimpleXMLObject.__init__(self, amount=amount,
                                 customerProfileId=profile_id,
                                 customerPaymentProfileId=pay_id,
                                 transId=trans_id,
                                 order=order)

    def _wrapper(self, content):
        return self.simple_tag(self._name(), content)


# authorize and charge
@export
class ProfileTransAuthCapture(Transaction): pass


# only authorize (no charge is made)
@export
class ProfileTransAuthOnly(Transaction): pass


# charge only (requires previous auth_only)
@export
class ProfileTransPriorAuthCapture(Transaction): pass


# stronger than above: charge even on decline (not sure why you would want to)
@export
class ProfileTransCaptureOnly(Transaction): pass


# refund a transaction
@export
class ProfileTransRefund(Transaction): pass


# void a transaction
@export
class ProfileTransVoid(Transaction): pass


#-----
class AuthorizeNetRequest(SimpleXMLObject):
    _keys = ["merchantAuthentication"]

    @property
    def merchantAuthentication(self):
        return Auth(name=g.authorizenetname,
                    transactionKey=g.authorizenetkey)

    def _wrapper(self, content):
        return ('<?xml version="1.0" encoding="utf-8"?>' +
                self.simple_tag(self._name(), content,
                             xmlns="AnetApi/xml/v1/schema/AnetApiSchema.xsd"))

    def make_request(self):
        u = urlparse(g.authorizenetapi)
        try:
            conn = HTTPSConnection(u.hostname, u.port)
            conn.request("POST", u.path, self.toXML().encode('utf-8'),
                         {"Content-type": "text/xml"})
            res = conn.getresponse()
            res = self.handle_response(res.read())
            conn.close()
            return res
        except socket.error:
            return False

    def is_error_code(self, res, code):
        return (res.message.code and res.message.code.contents and
                res.message.code.contents[0] == code)


    def process_error(self, res):
        msg = "Response %r from request %r" % (res, self.toXML())
        raise AuthorizeNetException(msg)

    _autoclose_re = re.compile("<([^/]+)/>")
    def _autoclose_handler(self, m):
        return "<%(m)s></%(m)s>" % dict(m=m.groups()[0])

    def handle_response(self, res):
        res = self._autoclose_re.sub(self._autoclose_handler, res)
        res = BeautifulStoneSoup(res, 
                                 markupMassage=False, 
                                 convertEntities=BeautifulStoneSoup.XML_ENTITIES)
        if res.resultcode.contents[0] == u"Ok":
            return self.process_response(res)
        else:
            return self.process_error(res)

    def process_response(self, res):
        raise NotImplementedError

class CustomerRequest(AuthorizeNetRequest):
    _keys = AuthorizeNetRequest._keys + ["customerProfileId"]
    def __init__(self, user, **kw):
        if isinstance(user, int):
            cust_id = user
            self._user = None
        else:
            cust_id = CustomerID.get_id(user)
            self._user = user
        AuthorizeNetRequest.__init__(self, customerProfileId=cust_id, **kw)

# --- real request classes below


class CreateCustomerProfileRequest(AuthorizeNetRequest):
    """
    Create a new user object on authorize.net and return the new object ID.

    Handles the case of already existing users on either end
    gracefully and will update the Account object accordingly.
    """
    _keys = AuthorizeNetRequest._keys + ["profile", "validationMode"]

    def __init__(self, user, validationMode=None):
        # cache the user object passed in
        self._user = user
        AuthorizeNetRequest.__init__(self,
                                     profile=Profile(user, None, None), 
                                     validationMode=validationMode)

    def process_response(self, res):
        customer_id = int(res.customerprofileid.contents[0])
        CustomerID.set(self._user, customer_id)
        return customer_id

    def make_request(self):
        # don't send a new request if the user already has an id
        return (CustomerID.get_id(self._user) or
                AuthorizeNetRequest.make_request(self))

    re_lost_id = re.compile("A duplicate record with ID (\d+) already exists")
    def process_error(self, res):
        if self.is_error_code(res, Errors.DUPLICATE_RECORD):
            # authorize.net has a record for this customer but we don't. get
            # the correct id from the error message and update our db
            matches = self.re_lost_id.match(res.find("text").contents[0])
            if matches:
                match_groups = matches.groups()
                CustomerID.set(self._user, match_groups[0])
                g.log.debug("Updated missing authorize.net id for user %s" % self._user._id)
            else:
                # could happen if the format of the error message changes.
                msg = ("Failed to fix duplicate authorize.net profile id. "
                       "re_lost_id regexp may need to be updated. Response: %r" 
                       % res)
                raise AuthorizeNetException(msg)
        # otherwise, we might have sent a user that already had a customer ID
        cust_id = CustomerID.get_id(self._user)
        if cust_id:
            return cust_id
        return AuthorizeNetRequest.process_error(self, res)


class CreateCustomerPaymentProfileRequest(CustomerRequest):
    """
    Adds a payment profile to an existing user object.  The profile
    includes a valid address and a credit card number.
    """
    _keys = (CustomerRequest._keys + ["paymentProfile", "validationMode"])

    def __init__(self, user, address, creditcard, validationMode=None):
        CustomerRequest.__init__(self, user,
                                 paymentProfile=PaymentProfile(address,
                                                               creditcard),
                                 validationMode=validationMode)

    def process_response(self, res):
        pay_id = int(res.customerpaymentprofileid.contents[0])
        PayID.add(self._user, pay_id)
        return pay_id

    def process_error(self, res):
        if self.is_error_code(res, Errors.DUPLICATE_RECORD):
            u, data = GetCustomerProfileRequest(self._user).make_request()
            profiles = data.paymentProfiles
            if len(profiles) == 1:
                return profiles[0].customerPaymentProfileId
            return
        return CustomerRequest.process_error(self, res)


class CreateCustomerShippingAddressRequest(CustomerRequest):
    """
    Adds a shipping address.
    """
    _keys = CustomerRequest._keys + ["address"]
    def process_response(self, res):
        pay_id = int(res.customeraddressid.contents[0])
        ShippingAddress.add(self._user, pay_id)
        return pay_id

    def process_error(self, res):
        if self.is_error_code(res, Errors.DUPLICATE_RECORD):
            return
        return CustomerRequest.process_error(self, res)


class GetCustomerPaymentProfileRequest(CustomerRequest):
    _keys = CustomerRequest._keys + ["customerPaymentProfileId"]
    """
    Gets a payment profile by user Account object and authorize.net
    profileid of the payment profile.

    Error handling: make_request returns None if the id generates a
    RECORD_NOT_FOUND error from the server.  The user object is
    cleaned up in either case; if the user object lacked the (valid)
    pay id, it is added to its list, while if the pay id is invalid,
    it is removed from the user object.
    """
    def __init__(self, user, profileid):
        CustomerRequest.__init__(self, user,
                                 customerPaymentProfileId=profileid)
    def process_response(self, res):
        # add the id to the user object in case something has gone wrong
        PayID.add(self._user, self.customerPaymentProfileId)
        return PaymentProfile.fromXML(res.paymentprofile)

    def process_error(self, res):
        if self.is_error_code(res, Errors.RECORD_NOT_FOUND):
            PayID.delete(self._user, self.customerPaymentProfileId)
        return CustomerRequest.process_error(self, res)


class GetCustomerShippingAddressRequest(CustomerRequest):
    """
    Same as GetCustomerPaymentProfileRequest except with shipping addresses.

    Error handling is identical.
    """
    _keys = CustomerRequest._keys + ["customerAddressId"]
    def __init__(self, user, shippingid):
        CustomerRequest.__init__(self, user,
                                 customerAddressId=shippingid)

    def process_response(self, res):
        # add the id to the user object in case something has gone wrong
        ShippingAddress.add(self._user, self.customerAddressId)
        return Address.fromXML(res.address)

    def process_error(self, res):
        if self.is_error_code(res, Errors.RECORD_NOT_FOUND):
            ShippingAddress.delete(self._user, self.customerAddressId)
        return CustomerRequest.process_error(self, res)
 

class GetCustomerProfileIdsRequest(AuthorizeNetRequest):
    """
    Get a list of all customer ids that have been recorded with
    authorize.net
    """
    def process_response(self, res):
        return [int(x.contents[0]) for x in res.ids.findAll('numericstring')]


class GetCustomerProfileRequest(CustomerRequest): 
    """
    Given a user, find their customer information.
    """
    def process_response(self, res):
        from r2.models import Account
        fullname = res.merchantcustomerid.contents[0]
        name = res.description.contents[0]
        customer_id = int(res.customerprofileid.contents[0])
        acct = Account._by_name(name)

        # make sure we are updating the correct account!
        if acct.name == name:
            CustomerID.set(acct, customer_id)
        else:
            raise AuthorizeNetException, \
                  "account name doesn't match authorize.net account"

        # parse the ship-to list, and make sure the Account is up todate
        ship_to = []
        for profile in res.findAll("shiptolist"):
            a = Address.fromXML(profile)
            ShippingAddress.add(acct, a.customerAddressId)
            ship_to.append(a)

        # parse the payment profiles, and ditto
        profiles = []
        for profile in res.findAll("paymentprofiles"):
            a = Address.fromXML(profile)
            cc = CreditCard.fromXML(profile.payment)
            payprof = PaymentProfile(a, cc, int(a.customerPaymentProfileId))
            PayID.add(acct, a.customerPaymentProfileId)
            profiles.append(payprof)

        return acct, Profile(acct, profiles, ship_to)
    
class DeleteCustomerProfileRequest(CustomerRequest):
    """
    Delete a customer shipping address
    """
    def process_response(self, res):
        if self._user:
            CustomerID.delete(self._user)
        return 

    def process_error(self, res):
        if self.is_error_code(res, Errors.RECORD_NOT_FOUND):
            CustomerID.delete(self._user)
        return CustomerRequest.process_error(self, res)


class DeleteCustomerPaymentProfileRequest(GetCustomerPaymentProfileRequest):
    """
    Delete a customer shipping address
    """
    def process_response(self, res):
        PayID.delete(self._user, self.customerPaymentProfileId)
        return True

    def process_error(self, res):
        if self.is_error_code(res, Errors.RECORD_NOT_FOUND):
            PayID.delete(self._user, self.customerPaymentProfileId)
        return GetCustomerPaymentProfileRequest.process_error(self, res)


class DeleteCustomerShippingAddressRequest(GetCustomerShippingAddressRequest):
    """
    Delete a customer shipping address
    """
    def process_response(self, res):
        ShippingAddress.delete(self._user, self.customerAddressId)
        return True

    def process_error(self, res):
        if self.is_error_code(res, Errors.RECORD_NOT_FOUND):
            ShippingAddress.delete(self._user, self.customerAddressId)
        GetCustomerShippingAddressRequest.process_error(self, res)


# TODO
#class UpdateCustomerProfileRequest(AuthorizeNetRequest):
#    _keys = (AuthorizeNetRequest._keys + ["profile"])
#    
#    def __init__(self, user):
#        profile = Profile(user, None, None)
#        AuthorizeNetRequest.__init__(self, profile = profile)

class UpdateCustomerPaymentProfileRequest(CreateCustomerPaymentProfileRequest):
    """
    For updating the user's payment profile
    """
    def __init__(self, user, paymentid, address, creditcard, 
                 validationMode=None):
        CustomerRequest.__init__(self, user,
                                 paymentProfile=PaymentProfile(address,
                                                               creditcard,
                                                               paymentid),
                                 validationMode=validationMode)

    def process_response(self, res):
        return self.paymentProfile.customerPaymentProfileId


class UpdateCustomerShippingAddressRequest(
    CreateCustomerShippingAddressRequest):
    """
    For updating the user's shipping address
    """
    def __init__(self, user, address_id, address):
        address.customerAddressId = address_id
        CreateCustomerShippingAddressRequest.__init__(self, user,
                                                      address=address)

    def process_response(self, res):
        return True


class CreateCustomerProfileTransactionRequest(AuthorizeNetRequest):
    _keys = AuthorizeNetRequest._keys + ["transaction", "extraOptions"]

    # unlike every other response we get back, this api function
    # returns CSV data of the response with no field labels.  these
    # are used in package_response to zip this data into a usable
    # storage.
    response_keys = ("response_code",
                     "response_subcode",
                     "response_reason_code",
                     "response_reason_text",
                     "authorization_code",
                     "avs_response",
                     "trans_id",
                     "invoice_number",
                     "description",
                     "amount", "method",
                     "transaction_type",
                     "customerID",
                     "firstName", "lastName",
                     "company", "address", "city", "state",
                     "zip", "country", 
                     "phoneNumber", "faxNumber", "email",
                     "shipTo_firstName", "shipTo_lastName",
                     "shipTo_company", "shipTo_address",
                     "shipTo_city", "shipTo_state",
                     "shipTo_zip", "shipTo_country",
                     "tax", "duty", "freight",
                     "tax_exempt", "po_number", "md5",
                     "cav_response")

    # list of casts for the response fields given above
    response_types = dict(response_code=int,
                          response_subcode=int,
                          response_reason_code=int,
                          trans_id=int)

    def __init__(self, **kw):
        from pylons import g
        self._extra = kw.get("extraOptions", {})
        #if g.debug:
        #    self._extra['x_test_request'] = "TRUE"
        AuthorizeNetRequest.__init__(self, **kw)

    @property
    def extraOptions(self):
        return "<![CDATA[%s]]>" % "&".join("%s=%s" % x
                                            for x in self._extra.iteritems())

    def process_response(self, res):
        return (True, self.package_response(res))

    def process_error(self, res):
        if self.is_error_code(res, Errors.TRANSACTION_FAIL):
            return (False, self.package_response(res))
        elif self.is_error_code(res, Errors.TESTMODE):
            return (None, None)
        return AuthorizeNetRequest.process_error(self, res)


    def package_response(self, res):
        content = res.directresponse.contents[0]
        s = Storage(zip(self.response_keys, content.split(',')))
        for name, cast in self.response_types.iteritems():
            try:
                s[name] = cast(s[name])
            except ValueError:
                pass
        return s


class GetSettledBatchListRequest(AuthorizeNetRequest):
    _keys = AuthorizeNetRequest._keys + ["includeStatistics", 
                                         "firstSettlementDate", 
                                         "lastSettlementDate"]
    def __init__(self, start_date, end_date, **kw):
        AuthorizeNetRequest.__init__(self, 
                                     includeStatistics=1,
                                     firstSettlementDate=start_date.isoformat(),
                                     lastSettlementDate=end_date.isoformat(),
                                     **kw)

    def process_response(self, res):
        return res

