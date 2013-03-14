#!/usr/bin/env python
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

from r2.tests import RedditTestCase


class AuthorizeNetExceptionTest(RedditTestCase):

    def test_exception_message(self):
        from r2.lib.authorize.api import AuthorizeNetException
        card_number = "<cardNumber>1111222233334444</cardNumber>"
        expected = "<cardNumber>...4444</cardNumber>"
        full_msg = "Wrong Card %s was given"

        exp = AuthorizeNetException(full_msg % (card_number))

        self.assertNotEqual(str(exp), (full_msg % card_number))
        self.assertEqual(str(exp), (full_msg % expected))

class SimpleXMLObjectTest(RedditTestCase):

    def setUp(self):
        from r2.lib.authorize.api import SimpleXMLObject
        self.basic_object = SimpleXMLObject(name="Test",
                                           test="123",
                                           )

    def test_to_xml(self):
        self.assertEqual(self.basic_object.toXML(),
                         "<test>123</test><name>Test</name>",
                         "Unexpected XML produced")

    def test_simple_tag(self):
        from r2.lib.authorize.api import SimpleXMLObject
        xml_output = SimpleXMLObject.simple_tag("cat", "Jini", breed="calico",
                                                               demenor="evil",
                                                               )
        self.assertEqual(xml_output,
                         '<cat breed="calico" demenor="evil">Jini</cat>')

    def test_from_xml(self):
        from r2.lib.authorize.api import SimpleXMLObject
        from BeautifulSoup import BeautifulStoneSoup
        class TestXML(SimpleXMLObject):
            _keys = ["color", "breed"]

        parsed = BeautifulStoneSoup("<dog>" +
                                    "<color>black</color>" +
                                    "<breed>mixed</breed>" +
                                    "<something>else</something>" +
                                    "</dog>")
        constructed = TestXML.fromXML(parsed)
        expected = SimpleXMLObject(color="black",
                                   breed="mixed",
                                   )
        self.assertEqual(constructed.toXML(), expected.toXML(), 
                         "Constructed does not match expected")

    def test_address(self):
        from r2.lib.authorize import Address
        address = Address(firstName="Bob",
                          lastName="Smith",
                          company="Reddit Inc.",
                          address="123 Main St.",
                          city="San Francisco",
                          state="California",
                          zip="12345",
                          country="USA",
                          phoneNumber="415-555-1234",
                          faxNumber="415-555-4321",
                          customerPaymentProfileId="1234567890",
                          customerAddressId="2233",
                          )
        expected = ("<firstName>Bob</firstName>" +
                   "<lastName>Smith</lastName>" +
                   "<company>Reddit Inc.</company>" +
                   "<address>123 Main St.</address>" +
                   "<city>San Francisco</city>" +
                   "<state>California</state>" +
                   "<zip>12345</zip>" +
                   "<country>USA</country>" +
                   "<phoneNumber>415-555-1234</phoneNumber>" +
                   "<faxNumber>415-555-4321</faxNumber>" +
                   "<customerPaymentProfileId>1234567890</customerPaymentProfileId>" +
                   "<customerAddressId>2233</customerAddressId>")

        self.assertEqual(address.toXML(), expected)

    def test_credit_card(self):
        from r2.lib.authorize import CreditCard
        card = CreditCard(cardNumber="1111222233334444",
                          expirationDate="11/22/33",
                          cardCode="123"
                          )
        expected = ("<cardNumber>1111222233334444</cardNumber>" +
                    "<expirationDate>11/22/33</expirationDate>" +
                    "<cardCode>123</cardCode>")
        self.assertEqual(card.toXML(), expected)

    def test_payment_profile(self):
        from r2.lib.authorize.api import PaymentProfile
        profile = PaymentProfile(billTo="Joe",
                                 paymentId="222",
                                 card="1111222233334444",
                                 validationMode="42",
                                 )
        expected = ("<billTo>Joe</billTo>" +
                    "<payment>" +
                        "<creditCard>1111222233334444</creditCard>" +
                    "</payment>" +
                    "<customerPaymentProfileId>222</customerPaymentProfileId>" +
                    "<validationMode>42</validationMode>")
        self.assertEqual(profile.toXML(), expected)

    def test_transation(self):
        from r2.lib.authorize.api import Transaction
        transaction = Transaction(amount="42.42",
                                  profile_id="112233",
                                  pay_id="1111",
                                  trans_id="2222", 
                                  order="42",
                                  )
     
        expected = ("<transaction>" +
                        "<amount>42.42</amount>" +
                        "<customerProfileId>112233</customerProfileId>" +
                        "<customerPaymentProfileId>1111</customerPaymentProfileId>" +
                        "<transId>2222</transId>" +
                        "<order>42</order>" +
                    "</transaction>")
        self.assertEqual(transaction.toXML(), expected)
    
class ImportTest(RedditTestCase):

    def test_importable(self):
        #validator
        from r2.lib.authorize import Address, CreditCard
        #promotecontroller
        from r2.lib.authorize import (
                                      get_account_info,
                                      edit_profile,
                                      PROFILE_LIMIT,
                                      )
        #promote.py
        from r2.lib.authorize import (
                                      auth_transaction,
                                      charge_transaction,
                                      is_charged_transaction,
                                      void_transaction,
                                      )
