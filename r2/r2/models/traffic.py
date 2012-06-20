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

from pylons import g
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.schema import Column
from sqlalchemy.types import DateTime, Integer, String, BigInteger



engine = g.dbm.get_engine("traffic")
Session = scoped_session(sessionmaker(bind=engine))
Base = declarative_base(bind=engine)


class SitewidePageviews(Base):
    __tablename__ = "traffic_aggregate"

    date = Column(DateTime(), nullable=False, primary_key=True)
    interval = Column(String(), nullable=False, primary_key=True)
    unique_count = Column("unique", Integer())
    pageview_count = Column("total", BigInteger())


class PageviewsBySubreddit(Base):
    __tablename__ = "traffic_subreddits"

    subreddit = Column(String(), nullable=False, primary_key=True)
    date = Column(DateTime(), nullable=False, primary_key=True)
    interval = Column(String(), nullable=False, primary_key=True)
    unique_count = Column("unique", Integer())
    pageview_count = Column("total", Integer())


class PageviewsBySubredditAndPath(Base):
    __tablename__ = "traffic_srpaths"

    srpath = Column(String(), nullable=False, primary_key=True)
    date = Column(DateTime(), nullable=False, primary_key=True)
    interval = Column(String(), nullable=False, primary_key=True)
    unique_count = Column("unique", Integer())
    pageview_count = Column("total", Integer())


class PageviewsByLanguage(Base):
    __tablename__ = "traffic_lang"

    lang = Column(String(), nullable=False, primary_key=True)
    date = Column(DateTime(), nullable=False, primary_key=True)
    interval = Column(String(), nullable=False, primary_key=True)
    unique_count = Column("unique", Integer())
    pageview_count = Column("total", Integer())


class ClickthroughsByCodename(Base):
    __tablename__ = "traffic_click"

    codename = Column("fullname", String(), nullable=False, primary_key=True)
    date = Column(DateTime(), nullable=False, primary_key=True)
    interval = Column(String(), nullable=False, primary_key=True)
    unique_count = Column("unique", Integer())
    pageview_count = Column("total", Integer())


class TargetedClickthroughsByCodename(Base):
    __tablename__ = "traffic_clicktarget"

    codename = Column("fullname", String(), nullable=False, primary_key=True)
    subreddit = Column(String(), nullable=False, primary_key=True)
    date = Column(DateTime(), nullable=False, primary_key=True)
    interval = Column(String(), nullable=False, primary_key=True)
    unique_count = Column("unique", Integer())
    pageview_count = Column("total", Integer())


class AdImpressionsByCodename(Base):
    __tablename__ = "traffic_thing"

    codename = Column("fullname", String(), nullable=False, primary_key=True)
    date = Column(DateTime(), nullable=False, primary_key=True)
    interval = Column(String(), nullable=False, primary_key=True)
    unique_count = Column("unique", Integer())
    pageview_count = Column("total", Integer())


class TargetedImpressionsByCodename(Base):
    __tablename__ = "traffic_thingtarget"

    codename = Column("fullname", String(), nullable=False, primary_key=True)
    subreddit = Column(String(), nullable=False, primary_key=True)
    date = Column(DateTime(), nullable=False, primary_key=True)
    interval = Column(String(), nullable=False, primary_key=True)
    unique_count = Column("unique", Integer())
    pageview_count = Column("total", Integer())


class SubscriptionsBySubreddit(Base):
    __tablename__ = "traffic_subscriptions"

    subreddit = Column(String(), nullable=False, primary_key=True)
    date = Column(DateTime(), nullable=False, primary_key=True)
    subscriber_count = Column("unique", Integer())


# create the tables if they don't exist
if g.db_create_tables:
    Base.metadata.create_all()
