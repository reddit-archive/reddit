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

import datetime

from pylons import g, request
from sqlalchemy import (
    and_,
    Boolean,
    BigInteger,
    Column,
    DateTime,
    Date,
    Float,
    func as safunc,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql.base import PGInet as Inet
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import NoResultFound

from r2.lib.db.thing import Thing, NotFound
from r2.lib.memoize import memoize
from r2.lib.utils import Enum, to_date
from r2.models.account import Account
from r2.models import Link


engine = g.dbm.get_engine('authorize')
# Allocate a session maker for communicating object changes with the back end  
Session = sessionmaker(autocommit = True, autoflush = True, bind = engine)
# allocate a SQLalchemy base class for auto-creation of tables based
# on class fields.  
# NB: any class that inherits from this class will result in a table
# being created, and subclassing doesn't work, hence the
# object-inheriting interface classes.
Base = declarative_base(bind = engine)

class Sessionized(object):
    """
    Interface class for wrapping up the "session" in the 0.5 ORM
    required for all database communication.  This allows subclasses
    to have a "query" and "commit" method that doesn't require
    managing of the session.
    """
    session = Session()

    def __init__(self, *a, **kw):
        """
        Common init used by all other classes in this file.  Allows
        for object-creation based on the __table__ field which is
        created by Base (further explained in _disambiguate_args).
        """
        for k, v in self._disambiguate_args(None, *a, **kw):
            setattr(self, k.name, v)
    
    @classmethod
    def _new(cls, *a, **kw):
        """
        Just like __init__, except the new object is committed to the
        db before being returned.
        """
        obj = cls(*a, **kw)
        obj._commit()
        return obj

    def _commit(self):
        """
        Commits current object to the db.
        """
        with self.session.begin():
            self.session.add(self)

    def _delete(self):
        """
        Deletes current object from the db. 
        """
        with self.session.begin():
            self.session.delete(self)

    @classmethod
    def query(cls, **kw):
        """
        Ubiquitous class-level query function. 
        """
        q = cls.session.query(cls)
        if kw:
            q = q.filter_by(**kw)
        return q

    @classmethod
    def _disambiguate_args(cls, filter_fn, *a, **kw):
        """
        Used in _lookup and __init__ to interpret *a as being a list
        of args to match columns in the same order as __table__.c

        For example, if a class Foo has fields a and b, this function
        allows the two to work identically:
        
        >>> foo = Foo(a = 'arg1', b = 'arg2')
        >>> foo = Foo('arg1', 'arg2')

        Additionally, this function invokes _make_storable on each of
        the values in the arg list (including *a as well as
        kw.values())

        """
        args = []
        if filter_fn is None:
            cols = cls.__table__.c
        else:
            cols = filter(filter_fn, cls.__table__.c)
        for k, v in zip(cols, a):
            if not kw.has_key(k.name):
                args.append((k, cls._make_storable(v)))
            else:
                raise TypeError,\
                      "got multiple arguments for '%s'" % k.name

        cols = dict((x.name, x) for x in cls.__table__.c)
        for k, v in kw.iteritems():
            if cols.has_key(k):
                args.append((cols[k], cls._make_storable(v)))
        return args

    @classmethod
    def _make_storable(self, val):
        if isinstance(val, Account):
            return val._id
        elif isinstance(val, Thing):
            return val._fullname
        else:
            return val

    @classmethod
    def _lookup(cls, multiple, *a, **kw):
        """
        Generates an executes a query where it matches *a to the
        primary keys of the current class's table.

        The primary key nature can be overridden by providing an
        explicit list of columns to search.

        This function is only a convenience function, and is called
        only by one() and lookup().
        """
        args = cls._disambiguate_args(lambda x: x.primary_key, *a, **kw)
        res = cls.query().filter(and_(*[k == v for k, v in args]))
        try:
            res = res.all() if multiple else res.one()
            # res.one() will raise NoResultFound, while all() will
            # return an empty list.  This will make the response
            # uniform
            if not res:
                raise NoResultFound
        except NoResultFound: 
            raise NotFound, "%s with %s" % \
                (cls.__name__,
                 ",".join("%s=%s" % x for x in args))
        return res

    @classmethod
    def lookup(cls, *a, **kw):
        """
        Returns all objects which match the kw list, or primary keys
        that match the *a.
        """
        return cls._lookup(True, *a, **kw)

    @classmethod
    def one(cls, *a, **kw):
        """
        Same as lookup, but returns only one argument. 
        """
        return cls._lookup(False, *a, **kw)

    @classmethod
    def add(cls, key, *a):
        try:
            cls.one(key, *a)
        except NotFound:
            cls(key, *a)._commit()
    
    @classmethod
    def delete(cls, key, *a):
        try:
            cls.one(key, *a)._delete()
        except NotFound:
            pass
    
    @classmethod
    def get(cls, key):
        try:
            return cls.lookup(key)
        except NotFound:
            return []

class CustomerID(Sessionized, Base):
    __tablename__  = "authorize_account_id"

    account_id    = Column(BigInteger, primary_key = True,
                           autoincrement = False)
    authorize_id  = Column(BigInteger)

    def __repr__(self):
        return "<AuthNetID(%s)>" % self.authorize_id

    @classmethod
    def set(cls, user, _id):
        try:
            existing = cls.one(user)
            existing.authorize_id = _id
            existing._commit()
        except NotFound:
            cls(user, _id)._commit()
    
    @classmethod
    def get_id(cls, user):
        try:
            return cls.one(user).authorize_id
        except NotFound:
            return

class PayID(Sessionized, Base):
    __tablename__ = "authorize_pay_id"

    account_id    = Column(BigInteger, primary_key = True,
                           autoincrement = False)
    pay_id        = Column(BigInteger, primary_key = True,
                           autoincrement = False)

    def __repr__(self):
        return "<%s(%d)>" % (self.__class__.__name__, self.authorize_id)

    @classmethod
    def get_ids(cls, key):
        return [int(x.pay_id) for x in cls.get(key)]

class ShippingAddress(Sessionized, Base):
    __tablename__ = "authorize_ship_id"

    account_id    = Column(BigInteger, primary_key = True,
                           autoincrement = False)
    ship_id       = Column(BigInteger, primary_key = True,
                           autoincrement = False)

    def __repr__(self):
        return "<%s(%d)>" % (self.__class__.__name__, self.authorize_id)

class Bid(Sessionized, Base):
    __tablename__ = "bids"

    STATUS        = Enum("AUTH", "CHARGE", "REFUND", "VOID")

    # will be unique from authorize
    transaction   = Column(BigInteger, primary_key = True,
                           autoincrement = False)

    # identifying characteristics
    account_id    = Column(BigInteger, index = True, nullable = False)
    pay_id        = Column(BigInteger, index = True, nullable = False)
    thing_id      = Column(BigInteger, index = True, nullable = False)

    # breadcrumbs
    ip            = Column(Inet)
    date          = Column(DateTime(timezone = True), default = safunc.now(),
                           nullable = False)

    # bid information:
    bid           = Column(Float, nullable = False)
    charge        = Column(Float)

    status        = Column(Integer, nullable = False,
                           default = STATUS.AUTH)

    # make this a primary key as well so that we can have more than
    # one freebie per campaign
    campaign      = Column(Integer, default = 0, primary_key = True)

    @classmethod
    def _new(cls, trans_id, user, pay_id, thing_id, bid, campaign = 0):
        bid = Bid(trans_id, user, pay_id, 
                  thing_id, getattr(request, 'ip', '0.0.0.0'), bid = bid,
                  campaign = campaign)
        bid._commit()
        return bid

#    @classmethod
#    def for_transactions(cls, transids):
#        transids = filter(lambda x: x != 0, transids)
#        if transids:
#            q = cls.query()
#            q = q.filter(or_(*[cls.transaction == i for i in transids]))
#            return dict((p.transaction, p) for p in q)
#        return {}

    def set_status(self, status):
        if self.status != status:
            self.status = status
            self._commit()

    def auth(self):
        self.set_status(self.STATUS.AUTH)

    def is_auth(self):
        return (self.status == self.STATUS.AUTH)

    def void(self):
        self.set_status(self.STATUS.VOID)

    def is_void(self):
        return (self.status == self.STATUS.VOID)

    def charged(self):
        self.set_status(self.STATUS.CHARGE)

    def is_charged(self):
        """
        Returns True if transaction has been charged with authorize.net or is
        a freebie with "charged" status.
        """
        return (self.status == self.STATUS.CHARGE)

    def refund(self):
        self.set_status(self.STATUS.REFUND)


class PromotionWeights(Sessionized, Base):
    __tablename__ = "promotion_weight"

    thing_name = Column(String, primary_key = True,
                        nullable = False, index = True)

    promo_idx    = Column(BigInteger, index = True, autoincrement = False,
                          primary_key = True)

    sr_name    = Column(String, primary_key = True,
                        nullable = True,  index = True)
    date       = Column(Date(), primary_key = True,
                        nullable = False, index = True)

    # because we might want to search by account
    account_id   = Column(BigInteger, index = True, autoincrement = False)

    # bid and weight should always be the same, but they don't have to be
    bid        = Column(Float, nullable = False)
    weight     = Column(Float, nullable = False)

    finished   = Column(Boolean)

    @classmethod
    def reschedule(cls, thing, idx, sr, start_date, end_date, total_weight,
                   finished = False):
        cls.delete_unfinished(thing, idx)
        cls.add(thing, idx, sr, start_date, end_date, total_weight,
                finished = finished)

    @classmethod
    def add(cls, thing, idx, sr, start_date, end_date, total_weight,
            finished = False):
        start_date = to_date(start_date)
        end_date   = to_date(end_date)

        # anything set by the user will be uniform weighting
        duration = max((end_date - start_date).days, 1)
        weight = total_weight / duration

        d = start_date
        while d < end_date:
            cls._new(thing, idx, sr, d,
                     thing.author_id, weight, weight, finished = finished)
            d += datetime.timedelta(1)

    @classmethod
    def delete_unfinished(cls, thing, idx):
        #TODO: do this the right (fast) way before release.  I don't
        #have the inclination to figure out the proper delete method
        #now
        for item in cls.query(thing_name = thing._fullname,
                              promo_idx = idx,
                              finished = False):
            item._delete()

    @classmethod
    def get_campaigns(cls, start, end=None, author_id=None):
        start = to_date(start)
        q = cls.query()
        if end:
            end = to_date(end)
            q = q.filter(and_(cls.date >= start, cls.date < end))
        else:
            q = q.filter(cls.date == start)
        
        if author_id:
            q = q.filter(cls.account_id == author_id)
        
        return list(q)

    @classmethod
    def get_schedule(cls, start_date, end_date, author_id = None):
        res = {}
        for x in cls.get_campaigns(start_date, end_date, author_id):
            res.setdefault((x.thing_name, x.promo_idx), []).append(x.date)

        return [(k[0], k[1], min(v), max(v)) for k, v in res.iteritems()]

    @classmethod
    @memoize('promodates.bid_history', time = 10 * 60)
    def bid_history(cls, start_date, end_date = None, account_id = None):
        from r2.lib import promote
        from r2.models import PromoCampaign
        
        if not end_date:
            end_date = datetime.datetime.now(g.tz)
        
        start_date = to_date(start_date)
        end_date   = to_date(end_date)
        q = cls.query()
        q = q.filter(and_(cls.date >= start_date, cls.date < end_date))
        q = list(q)

        links = Link._by_fullname([x.thing_name for x in q], data=True)

        d = start_date
        res = []
        while d < end_date:
            bid = 0
            refund = 0
            for i in q:
                if d == i.date:
                    l = links[i.thing_name]
                    if (not promote.is_rejected(l) and 
                        not promote.is_unpaid(l) and 
                        not l._deleted):

                        try:
                            camp = PromoCampaign._byID(i.promo_idx, data=True)
                            bid += i.bid
                            refund += i.bid if camp.is_freebie() else 0
                        except NotFound:
                            g.log.error("Skipping missing PromoCampaign in "
                                        "bidding.bid_history, campaign id: %d" 
                                        % i.promo_idx)
            res.append([d, bid, refund])
            d += datetime.timedelta(1)
        return res

# do all the leg work of creating/connecting to tables
if g.db_create_tables:
    Base.metadata.create_all()

