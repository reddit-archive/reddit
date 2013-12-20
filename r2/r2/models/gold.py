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

import pytz

from pycassa import NotFoundException
from pycassa.system_manager import INT_TYPE, UTF8_TYPE
from pylons import g, c
from pylons.i18n import _
from datetime import datetime
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.sql.expression import select
from sqlalchemy.sql.functions import sum as sa_sum

from r2.lib.utils import GoldPrice, randstr
import re
from random import choice
from time import time

from r2.lib.db import tdb_cassandra
from r2.lib.db.tdb_cassandra import NotFound
from r2.models import Account
from r2.models.subreddit import Frontpage
from r2.models.wiki import WikiPage
from r2.lib.memoize import memoize

import stripe

gold_bonus_cutoff = datetime(2010,7,27,0,0,0,0,g.tz)
gold_static_goal_cutoff = datetime(2013, 11, 7, tzinfo=g.display_tz)

ENGINE_NAME = 'authorize'

ENGINE = g.dbm.get_engine(ENGINE_NAME)
METADATA = make_metadata(ENGINE)
TIMEZONE = pytz.timezone("America/Los_Angeles")

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
           index_str(gold_table, 'secret', 'secret'),
           index_str(gold_table, 'payer_email', 'payer_email'),
           index_str(gold_table, 'subscr_id', 'subscr_id')]
create_table(gold_table, indices)


class GoldRevenueGoalByDate(object):
    __metaclass__ = tdb_cassandra.ThingMeta

    _use_db = True
    _cf_name = "GoldRevenueGoalByDate"
    _read_consistency_level = tdb_cassandra.CL.ONE
    _write_consistency_level = tdb_cassandra.CL.ALL
    _extra_schema_creation_args = {
        "column_name_class": UTF8_TYPE,
        "default_validation_class": INT_TYPE,
    }
    _compare_with = UTF8_TYPE
    _type_prefix = None

    ROWKEY = '1'

    @staticmethod
    def _colkey(date):
        return date.strftime("%Y-%m-%d")

    @classmethod
    def set(cls, date, goal):
        cls._cf.insert(cls.ROWKEY, {cls._colkey(date): int(goal)})

    @classmethod
    def get(cls, date):
        """Gets the goal for a date, or the nearest previous goal."""
        try:
            colkey = cls._colkey(date)
            col = cls._cf.get(
                cls.ROWKEY,
                column_reversed=True,
                column_start=colkey,
                column_count=1,
            )
            return col.values()[0]
        except NotFoundException:
            return None


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


def create_gold_code(trans_id, payer_email, paying_id, pennies, days, date):
    if not trans_id:
        trans_id = "GC%d%s" % (int(time()), randstr(2))

    valid_chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    # keep picking new codes until we find an unused one
    while True:
        code = randstr(10, alphabet=valid_chars)

        s = sa.select([gold_table],
                      sa.and_(gold_table.c.secret == code.lower(),
                              gold_table.c.status == 'unclaimed'))
        res = s.execute().fetchall()
        if not res:
            gold_table.insert().execute(
                trans_id=trans_id,
                status='unclaimed',
                payer_email=payer_email,
                paying_id=paying_id,
                pennies=pennies,
                days=days,
                secret=code.lower(),
                date=date)
            return code

                
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
    secret = secret.replace("-", "").lower()

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


def retrieve_gold_transaction(transaction_id):
    s = sa.select([gold_table], gold_table.c.trans_id == transaction_id)
    res = s.execute().fetchall()
    if res:
        return res[0]   # single row per transaction_id


def update_gold_transaction(transaction_id, status):
    rp = gold_table.update(gold_table.c.trans_id == str(transaction_id),
                           values={gold_table.c.status: status}).execute()


def transactions_by_user(user):
    s = sa.select([gold_table], gold_table.c.account_id == str(user._id))
    res = s.execute().fetchall()
    return res


def gold_payments_by_user(user):
    transactions = transactions_by_user(user)

    # filter out received gifts
    transactions = [trans for trans in transactions
                          if not trans.trans_id.startswith(('X', 'M'))]

    return transactions


def gold_received_by_user(user):
    transactions = transactions_by_user(user)
    transactions = [trans for trans in transactions
                          if trans.trans_id.startswith('X')]
    return transactions


def days_to_pennies(days):
    if days < 366:
        months = days / 31
        return months * g.gold_month_price.pennies
    else:
        years = days / 366
        return years * g.gold_year_price.pennies


def append_random_bottlecap_phrase(message):
    """Appends a random "bottlecap" phrase from the wiki page.

    The wiki page should be an unordered list with each item a separate
    bottlecap.
    """

    bottlecap = None
    try:
        wp = WikiPage.get(Frontpage, g.wiki_page_gold_bottlecaps)

        split_list = re.split('^[*-] ', wp.content, flags=re.MULTILINE)
        choices = [item.strip() for item in split_list if item.strip()]
        if len(choices):
            bottlecap = choice(choices)
    except NotFound:
        pass

    if bottlecap:
        message += '\n\n> ' + bottlecap
    return message


def gold_revenue_multi(dates):
    NON_REVENUE_STATUSES = ("declined", "chargeback", "fudge")
    date_expr = sa.func.date_trunc('day',
                    sa.func.timezone(TIMEZONE.zone, gold_table.c.date))
    query = (select([date_expr, sa_sum(gold_table.c.pennies)])
                .where(~ gold_table.c.status.in_(NON_REVENUE_STATUSES))
                .where(date_expr.in_(dates))
                .group_by(date_expr)
            )
    return {truncated_time.date(): pennies
                for truncated_time, pennies in ENGINE.execute(query)}


@memoize("gold-revenue-volatile", time=600)
def gold_revenue_volatile(date):
    return gold_revenue_multi([date]).get(date, 0)


@memoize("gold-revenue-steady")
def gold_revenue_steady(date):
    return gold_revenue_multi([date]).get(date, 0)


@memoize("gold-goal")
def gold_goal_on(date):
    """Returns the gold revenue goal (in pennies) for a given date."""
    return GoldRevenueGoalByDate.get(date)


def account_from_stripe_customer_id(stripe_customer_id):
    q = Account._query(Account.c.gold_subscr_id == stripe_customer_id,
                       Account.c._spam == (True, False), data=True)
    return next(iter(q), None)


@memoize("subscription-details", time=60)
def _get_subscription_details(stripe_customer_id):
    stripe.api_key = g.STRIPE_SECRET_KEY
    customer = stripe.Customer.retrieve(stripe_customer_id)

    if getattr(customer, 'deleted', False):
        return {}

    subscription = customer.subscription
    card = customer.active_card
    end = datetime.fromtimestamp(subscription.current_period_end).date()
    last4 = card.last4
    pennies = subscription.plan.amount

    return {
        'next_charge_date': end,
        'credit_card_last4': last4,
        'pennies': pennies,
    }


def get_subscription_details(user):
    if not getattr(user, 'gold_subscr_id', None):
        return

    return _get_subscription_details(user.gold_subscr_id)


def get_discounted_price(gold_price):
    discount = float(getattr(g, 'BTC_DISCOUNT', '0'))
    price = (gold_price.pennies * (1 - discount)) / 100.
    return GoldPrice("%.2f" % price)
