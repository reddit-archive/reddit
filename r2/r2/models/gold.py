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

from r2.lib.db.tdb_sql import make_metadata, index_str, create_table

from pylons import g, c
from pylons.i18n import _
from datetime import datetime
import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.schema import Column
from sqlalchemy.sql import and_
from sqlalchemy.types import String, Integer

from xml.dom.minidom import Document
from r2.lib.utils import tup, randstr
from httplib import HTTPSConnection
from urlparse import urlparse
from time import time
import socket, base64
from BeautifulSoup import BeautifulStoneSoup

gold_bonus_cutoff = datetime(2010,7,27,0,0,0,0,g.tz)

ENGINE_NAME = 'authorize'

ENGINE = g.dbm.get_engine(ENGINE_NAME)
METADATA = make_metadata(ENGINE)

Session = scoped_session(sessionmaker(bind=ENGINE))
Base = declarative_base(bind=ENGINE)

gold_table = sa.Table('reddit_gold', METADATA,
                      sa.Column('trans_id', sa.String, nullable = False,
                                primary_key = True),
                      # status can be: invalid, unclaimed, claimed
                      sa.Column('status', sa.String, nullable = False),
                      sa.Column('date', sa.DateTime(timezone=True),
                                nullable = False,
                                default = sa.func.now()),
                      sa.Column('payer_email', sa.String, nullable = False),
                      sa.Column('paying_id', sa.String, nullable = False),
                      sa.Column('pennies', sa.Integer, nullable = False),
                      sa.Column('secret', sa.String, nullable = True),
                      sa.Column('account_id', sa.String, nullable = True),
                      sa.Column('days', sa.Integer, nullable = True),
                      sa.Column('subscr_id', sa.String, nullable = True))

indices = [index_str(gold_table, 'status', 'status'),
           index_str(gold_table, 'date', 'date'),
           index_str(gold_table, 'account_id', 'account_id'),
           index_str(gold_table, 'secret', 'secret', unique = True),
           index_str(gold_table, 'payer_email', 'payer_email'),
           index_str(gold_table, 'subscr_id', 'subscr_id')]
create_table(gold_table, indices)


def with_sqlalchemy_session(f):
    """Ensures sqlalchemy session is closed (due to connection pooling)."""
    def close_session_after(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        finally:
            Session.remove()

    return close_session_after


class GoldPartnerCodesExhaustedError(Exception):
    pass


class GoldPartnerDealCode(Base):
    """Promo codes for deals from reddit gold partners."""

    __tablename__ = "reddit_gold_partner_deal_codes"

    id = Column(Integer, primary_key=True)
    deal = Column(String, nullable=False)
    code = Column(String, nullable=False)
    user = Column(Integer, nullable=True)

    @classmethod
    @with_sqlalchemy_session
    def get_codes_for_user(cls, user):
        results = Session.query(cls).filter(cls.user == user._id)
        codes = {r.deal: r.code for r in results}
        return codes
    
    @classmethod
    @with_sqlalchemy_session
    def claim_code(cls, user, deal):
        # check if they already have a code for this deal and return it
        try:
            result = (Session.query(cls)
                      .filter(and_(cls.user == user._id,
                                   cls.deal == deal))
                      .one())
            return result.code
        except NoResultFound:
            pass

        # select an unclaimed code, assign it to the user, and return it
        try:
            claiming = (Session.query(cls)
                        .filter(and_(cls.deal == deal,
                                     cls.user == None,
                                     func.pg_try_advisory_lock(cls.id)))
                        .limit(1)
                        .one())
        except NoResultFound:
            raise GoldPartnerCodesExhaustedError

        claiming.user = user._id
        Session.add(claiming)
        Session.commit()

        # release the lock
        Session.query(func.pg_advisory_unlock_all()).all()

        return claiming.code 


def create_unclaimed_gold (trans_id, payer_email, paying_id,
                           pennies, days, secret, date,
                           subscr_id = None):

    try:
        gold_table.insert().execute(trans_id=str(trans_id),
                                    subscr_id=subscr_id,
                                    status="unclaimed",
                                    payer_email=payer_email,
                                    paying_id=paying_id,
                                    pennies=pennies,
                                    days=days,
                                    secret=str(secret),
                                    date=date
                                    )
    except IntegrityError:
        rp = gold_table.update(
            sa.and_(gold_table.c.status == 'uncharged',
                    gold_table.c.trans_id == str(trans_id)),
            values = {
                gold_table.c.status: "unclaimed",
                gold_table.c.payer_email: payer_email,
                gold_table.c.paying_id: paying_id,
                gold_table.c.pennies: pennies,
                gold_table.c.days: days,
                gold_table.c.secret:secret,
                gold_table.c.subscr_id : subscr_id
                },
            ).execute()

# TODO: this should really live in emailer.py
def notify_unclaimed_gold(txn_id, gold_secret, payer_email, source):
    from r2.lib import emailer
    url = "http://www.reddit.com/thanks/" + gold_secret

    # No point in i18n, since we don't have access to the user's
    # language info (or name) at this point
    if gold_secret.startswith("cr_"):
        body = """
Thanks for buying reddit gold gift creddits! We have received your %s
transaction, number %s.

Your secret claim code is %s. To associate the
creddits with your reddit account, just visit
%s
""" % (source, txn_id, gold_secret, url)
    else:
        body = """
Thanks for subscribing to reddit gold! We have received your %s
transaction, number %s.

Your secret subscription code is %s. You can use it to associate this
subscription with your reddit account -- just visit
%s
""" % (source, txn_id, gold_secret, url)

    emailer.gold_email(body, payer_email, "reddit gold subscriptions")


def create_claimed_gold (trans_id, payer_email, paying_id,
                         pennies, days, secret, account_id, date,
                         subscr_id = None, status="claimed"):
    gold_table.insert().execute(trans_id=trans_id,
                                subscr_id=subscr_id,
                                status=status,
                                payer_email=payer_email,
                                paying_id=paying_id,
                                pennies=pennies,
                                days=days,
                                secret=secret,
                                account_id=account_id,
                                date=date)

def create_gift_gold (giver_id, recipient_id, days, date, signed):
    trans_id = "X%d%s-%s" % (int(time()), randstr(2), 'S' if signed else 'A')

    gold_table.insert().execute(trans_id=trans_id,
                                status="gift",
                                paying_id=giver_id,
                                payer_email='',
                                pennies=0,
                                days=days,
                                account_id=recipient_id,
                                date=date)

def account_by_payingid(paying_id):
    s = sa.select([sa.distinct(gold_table.c.account_id)],
                  gold_table.c.paying_id == paying_id)
    res = s.execute().fetchall()

    if len(res) != 1:
        return None

    return int(res[0][0])

# returns None if the ID was never valid
# returns "already claimed" if it's already been claimed
# Otherwise, it's valid and the function claims it, returning a tuple with:
#   * the number of days
#   * the subscr_id, if any
def claim_gold(secret, account_id):
    if not secret:
        return None

    # The donation email has the code at the end of the sentence,
    # so they might get sloppy and catch the period or some whitespace.
    secret = secret.strip(". ")

    rp = gold_table.update(sa.and_(gold_table.c.status == 'unclaimed',
                                   gold_table.c.secret == secret),
                           values = {
                                      gold_table.c.status: 'claimed',
                                      gold_table.c.account_id: account_id,
                                    },
                           ).execute()
    if rp.rowcount == 0:
        just_claimed = False
    elif rp.rowcount == 1:
        just_claimed = True
    else:
        raise ValueError("rowcount == %d?" % rp.rowcount)

    s = sa.select([gold_table.c.days, gold_table.c.subscr_id],
                  gold_table.c.secret == secret,
                  limit = 1)
    rows = s.execute().fetchall()

    if not rows:
        return None
    elif just_claimed:
        return (rows[0].days, rows[0].subscr_id)
    else:
        return "already claimed"

def check_by_email(email):
    s = sa.select([gold_table.c.status,
                           gold_table.c.secret,
                           gold_table.c.days,
                           gold_table.c.account_id],
                          gold_table.c.payer_email == email)
    return s.execute().fetchall()

# google checkout specific code:
def new_google_transaction(trans_id):
    # transid is in three parts: the actual ID, an identifier, and the status
    key = trans_id.split('-')[0]
    g.log.error("inserting %s" % key)
    try:
        gold_table.insert().execute(trans_id="g" + str(key),
                                    subscr_id="",
                                    status="uncharged",
                                    payer_email="",
                                    paying_id="",
                                    pennies=0,
                                    days=0,
                                    secret=None,
                                    date=datetime.now(g.tz))
    except IntegrityError:
        s = sa.select([gold_table.c.trans_id],
                      sa.and_(gold_table.c.status == 'declined',
                              gold_table.c.trans_id == "g" + str(key)))
        res = s.execute().fetchall()
        if res:
            gold_table.update(gold_table.c.trans_id == "g" + str(key),
                              values = { gold_table.c.status : 'uncharged' }
                              ).execute()
        else:
            g.log.error("transaction id already exists in table: %s" % key)


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


def process_google_transaction(trans_id):
    trans = _google_ordernum_request(trans_id)

    # get the financial details
    auth = trans.find("authorization-amount-notification")
    
    # creddits?
    is_creddits = False
    cart = trans.find("shopping-cart")
    if cart:
        for item in cart.findAll("item-name"):
            if "creddit" in item.contents[0]:
                is_creddits = True
                break

    if not auth:
        # see if the payment was declinded
        status = trans.findAll('financial-order-state')
        if 'PAYMENT_DECLINED' in [x.contents[0] for x in status]:
            g.log.error("google declined transaction found: '%s'" % trans_id)
            rp = gold_table.update(
                sa.and_(gold_table.c.status == 'uncharged',
                        gold_table.c.trans_id == 'g' + str(trans_id)),
                values = { gold_table.c.status : "declined" }).execute()
        elif 'REVIEWING' not in [x.contents[0] for x in status]:
            g.log.error("google transaction not found: '%s', status: %s"
                        % (trans_id, [x.contents[0] for x in status]))
    elif auth.find("financial-order-state").contents[0] == "CHARGEABLE":
        email = str(auth.find("email").contents[0])
        payer_id = str(auth.find('buyer-id').contents[0])
        days = None
        try:
            pennies = int(float(auth.find("order-total").contents[0])*100)
            if is_creddits:
                secret = "cr_"
                if pennies >= g.gold_year_price.pennies:
                    days = 12 * 31 * int(pennies / g.gold_year_price.pennies)
                else:
                    days = 31 * int(pennies / g.gold_month_price.pennies)
            elif pennies == g.gold_year_price.pennies:
                secret = "ys_"
                days = 366
            elif pennies == g.gold_month_price.pennies:
                secret = "m_"
                days = 31
            else:
                g.log.error("Got %d pennies via Google?" % pennies)
                rp = gold_table.update(
                    sa.and_(gold_table.c.status == 'uncharged',
                            gold_table.c.trans_id == 'g' + str(trans_id)),
                    values = { gold_table.c.status : "strange",
                               gold_table.c.pennies : pennies,
                               gold_table.c.payer_email : email,
                               gold_table.c.paying_id : payer_id
                               }).execute()
                return
        except ValueError:
            g.log.error("no amount in google checkout for transid %s"
                     % trans_id)
            return

        secret += randstr(10)

        # no point charging twice.  If we are in this func, the db doesn't
        # know it was already charged so we still have to update and email
        charged = trans.find("charge-amount-notification")
        if not charged:
            _google_charge_and_ship(trans_id)

        create_unclaimed_gold("g" + str(trans_id),
                              email, payer_id, pennies, days, str(secret),
                              datetime.now(g.tz))

        notify_unclaimed_gold(trans_id, secret, email, "Google")


def process_uncharged():
    s = sa.select([gold_table.c.trans_id],
                 gold_table.c.status == 'uncharged')
    res = s.execute().fetchall()

    for trans_id, in res:
        if trans_id.startswith('g'):
            trans_id = trans_id[1:]
            process_google_transaction(trans_id)


def retrieve_gold_transaction(transaction_id):
    s = sa.select([gold_table], gold_table.c.trans_id == transaction_id)
    res = s.execute().fetchall()
    if res:
        return res[0]   # single row per transaction_id


def update_gold_transaction(transaction_id, status):
    rp = gold_table.update(gold_table.c.trans_id == str(transaction_id),
                           values={gold_table.c.status: status}).execute()
