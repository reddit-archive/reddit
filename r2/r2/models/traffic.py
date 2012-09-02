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

import datetime

from pylons import g
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.schema import Column
from sqlalchemy.types import DateTime, Integer, String, BigInteger
from sqlalchemy.sql.expression import desc, distinct
from sqlalchemy.sql.functions import sum

from r2.lib.utils import timedelta_by_name
from r2.models.link import Link
from r2.lib.memoize import memoize


engine = g.dbm.get_engine("traffic")
Session = scoped_session(sessionmaker(bind=engine))
Base = declarative_base(bind=engine)


def memoize_traffic(**memoize_kwargs):
    """Wrap the memoize decorator and automatically determine memoize key.

    The memoize key is based off the full name (including class name) of the
    method being memoized.

    """
    def memoize_traffic_decorator(fn):
        def memoize_traffic_wrapper(cls, *args, **kwargs):
            method = ".".join((cls.__name__, fn.__name__))
            actual_memoize_decorator = memoize(method, **memoize_kwargs)
            actual_memoize_wrapper = actual_memoize_decorator(fn)
            return actual_memoize_wrapper(cls, *args, **kwargs)
        return memoize_traffic_wrapper
    return memoize_traffic_decorator


class PeekableIterator(object):
    """Iterator that supports peeking at the next item in the iterable."""

    def __init__(self, iterable):
        self.iterator = iter(iterable)
        self.item = None

    def peek(self):
        """Get the next item in the iterable without advancing our position."""
        if not self.item:
            try:
                self.item = self.iterator.next()
            except StopIteration:
                return None
        return self.item

    def next(self):
        """Get the next item in the iterable and advance our position."""
        item = self.peek()
        self.item = None
        return item


def zip_timeseries(*series, **kwargs):
    """Zip timeseries data while gracefully handling gaps in the data.

    Timeseries data is expected to be a sequence of two-tuples (date, values).
    Values is expected itself to be a tuple. The width of the values tuples
    should be the same across all elements in a timeseries sequence. The result
    will be a single sequence in timeseries format.

    Gaps in sequences are filled with an appropriate number of zeros based on
    the size of the first value-tuple of that sequence.

    """

    next_slice = (max if kwargs.get("order", "descending") == "descending"
                  else min)
    iterators = [PeekableIterator(s) for s in series]
    widths = [len(w.peek() or []) for w in iterators]

    while True:
        items = [it.peek() for it in iterators]
        if not any(items):
            return

        current_slice = next_slice(item[0] for item in items if item)

        data = []
        for i, item in enumerate(items):
            # each item is (date, data)
            if item and item[0] == current_slice:
                data.extend(item[1])
                iterators[i].next()
            else:
                data.extend([0] * widths[i])

        yield current_slice, tuple(data)


def decrement_month(date, amount=1):
    """Given a truncated datetime, return a new one one month in the past."""

    if date.day != 1:
        raise ValueError("Input must be truncated to the 1st of the month.")

    date -= datetime.timedelta(days=1)
    return date.replace(day=1)


def fill_gaps_generator(interval, start_time, stop_time, query, *columns):
    """Generate a timeseries sequence with a value for every sample expected.

    Iterate backwards in steps specified by interval from the most recent date
    (stop_time) to the oldest (start_time) and pull the columns listed out of
    query. If the query doesn't have data for a time slice, fill the gap with
    an appropriate number of zeroes.

    """

    iterator = PeekableIterator(query)
    step = timedelta_by_name(interval)
    current_slice = stop_time

    while current_slice > start_time:
        row = iterator.peek()

        if row and row.date == current_slice:
            yield current_slice, tuple(getattr(row, c) for c in columns)
            iterator.next()
        else:
            yield current_slice, tuple(0 for c in columns)

        # moving backwards a month isn't a fixed timedelta -- special case it
        if interval != "month":
            current_slice -= step
        else:
            current_slice = decrement_month(current_slice)


def fill_gaps(*args, **kwargs):
    """Listify the generator returned by fill_gaps_generator for `memoize`."""
    generator = fill_gaps_generator(*args, **kwargs)
    return list(generator)


time_range_by_interval = dict(hour=datetime.timedelta(days=4),
                              day=datetime.timedelta(weeks=8),
                              month=datetime.timedelta(weeks=52))


def time_range(interval):
    """Calculate the time range to view for a given level of precision.

    The coarser our granularity, the more history we'll want to see.

    """

    # the stop time is the most recent slice-time; get this by truncating
    # the appropriate amount from the current time
    stop_time = datetime.datetime.utcnow()
    stop_time = stop_time.replace(minute=0, second=0, microsecond=0)
    if interval in ("day", "month"):
        stop_time = stop_time.replace(hour=0)
    if interval == "month":
        stop_time = stop_time.replace(day=1)

    # then the start time is easy to work out
    range = time_range_by_interval[interval]
    start_time = stop_time - range

    return start_time, stop_time


def points_for_interval(interval):
    """Calculate the number of data points to render for a given interval."""
    range = time_range_by_interval[interval]
    interval = timedelta_by_name(interval)
    return range.total_seconds() / interval.total_seconds()


def make_history_query(cls, interval):
    """Build a generic query showing the history of a given aggregate."""

    start_time, stop_time = time_range(interval)
    q = (Session.query(cls)
                .filter(cls.date >= start_time))

    # subscription stats doesn't have an interval (it's only daily)
    if hasattr(cls, "interval"):
        q = q.filter(cls.interval == interval)

    q = q.order_by(desc(cls.date))

    return start_time, stop_time, q


def top_last_month(cls, key):
    """Aggregate a listing of the top items (by pageviews) last month.

    We use the last month because it's guaranteed to be fully computed and
    therefore will be more meaningful.

    """
    cur_month = datetime.date.today().replace(day=1)
    last_month = decrement_month(cur_month)

    q = (Session.query(cls)
                .filter(cls.date == last_month)
                .filter(cls.interval == "month")
                .order_by(desc(cls.date), desc(cls.pageview_count))
                .limit(55))

    return [(getattr(r, key), (r.unique_count, r.pageview_count))
            for r in q.all()]


def totals(cls, interval):
    """Aggregate sitewide totals for self-serve promotion traffic.

    We only aggregate codenames that start with a link type prefix which
    effectively filters out all DART / 300x100 etc. traffic numbers.

    """
    start_time, stop_time = time_range(interval)
    q = (Session.query(cls.date, sum(cls.pageview_count).label("sum"))
                .filter(cls.interval == interval)
                .filter(cls.date > start_time)
                .filter(cls.codename.startswith(Link._type_prefix))
                .group_by(cls.date)
                .order_by(desc(cls.date)))
    return fill_gaps(interval, start_time, stop_time, q, "sum")


def promotion_history(cls, codename, start, stop):
    """Get hourly traffic for a self-serve promotion across all campaigns."""
    q = (Session.query(cls)
                .filter(cls.interval == "hour")
                .filter(cls.codename == codename)
                .filter(cls.date >= start)
                .filter(cls.date <= stop)
                .order_by(cls.date))
    return [(r.date, (r.unique_count, r.pageview_count)) for r in q.all()]


@memoize("traffic_last_modified", time=60 * 10)
def get_traffic_last_modified():
    """Guess how far behind the traffic processing system is."""
    return (Session.query(SitewidePageviews.date)
                   .order_by(desc(SitewidePageviews.date))
                   .limit(1)
                   .one()).date


class SitewidePageviews(Base):
    __tablename__ = "traffic_aggregate"

    date = Column(DateTime(), nullable=False, primary_key=True)
    interval = Column(String(), nullable=False, primary_key=True)
    unique_count = Column("unique", Integer())
    pageview_count = Column("total", BigInteger())

    @classmethod
    @memoize_traffic(time=3600)
    def history(cls, interval):
        start_time, stop_time, q = make_history_query(cls, interval)
        return fill_gaps(interval, start_time, stop_time, q,
                         "unique_count", "pageview_count")


class PageviewsBySubreddit(Base):
    __tablename__ = "traffic_subreddits"

    subreddit = Column(String(), nullable=False, primary_key=True)
    date = Column(DateTime(), nullable=False, primary_key=True)
    interval = Column(String(), nullable=False, primary_key=True)
    unique_count = Column("unique", Integer())
    pageview_count = Column("total", Integer())

    @classmethod
    @memoize_traffic(time=3600)
    def history(cls, interval, subreddit):
        start_time, stop_time, q = make_history_query(cls, interval)
        q = q.filter(cls.subreddit == subreddit)
        return fill_gaps(interval, start_time, stop_time, q,
                         "unique_count", "pageview_count")

    @classmethod
    @memoize_traffic(time=3600 * 6)
    def top_last_month(cls):
        return top_last_month(cls, "subreddit")


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

    @classmethod
    @memoize_traffic(time=3600)
    def history(cls, interval, lang):
        start_time, stop_time, q = make_history_query(cls, interval)
        q = q.filter(cls.lang == lang)
        return fill_gaps(interval, start_time, stop_time, q,
                         "unique_count", "pageview_count")

    @classmethod
    @memoize_traffic(time=3600 * 6)
    def top_last_month(cls):
        return top_last_month(cls, "lang")


class ClickthroughsByCodename(Base):
    __tablename__ = "traffic_click"

    codename = Column("fullname", String(), nullable=False, primary_key=True)
    date = Column(DateTime(), nullable=False, primary_key=True)
    interval = Column(String(), nullable=False, primary_key=True)
    unique_count = Column("unique", Integer())
    pageview_count = Column("total", Integer())

    @classmethod
    @memoize_traffic(time=3600)
    def history(cls, interval, codename):
        start_time, stop_time, q = make_history_query(cls, interval)
        q = q.filter(cls.codename == codename)
        return fill_gaps(interval, start_time, stop_time, q, "unique_count",
                                                             "pageview_count")

    @classmethod
    @memoize_traffic(time=3600)
    def promotion_history(cls, codename, start, stop):
        return promotion_history(cls, codename, start, stop)

    @classmethod
    @memoize_traffic(time=3600)
    def historical_totals(cls, interval):
        return totals(cls, interval)


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

    @classmethod
    @memoize_traffic(time=3600)
    def history(cls, interval, codename):
        start_time, stop_time, q = make_history_query(cls, interval)
        q = q.filter(cls.codename == codename)
        return fill_gaps(interval, start_time, stop_time, q,
                         "unique_count", "pageview_count")

    @classmethod
    @memoize_traffic(time=3600)
    def promotion_history(cls, codename, start, stop):
        return promotion_history(cls, codename, start, stop)

    @classmethod
    @memoize_traffic(time=3600)
    def historical_totals(cls, interval):
        return totals(cls, interval)

    @classmethod
    @memoize_traffic(time=3600)
    def top_last_month(cls):
        return top_last_month(cls, "codename")

    @classmethod
    @memoize_traffic(time=3600)
    def recent_codenames(cls, fullname):
        """Get a list of recent codenames used for 300x100 ads.

        The 300x100 ads get a codename that looks like "fullname_campaign".
        This function gets a list of recent campaigns.
        """
        start_time, stop_time = time_range("day")
        query = (Session.query(distinct(cls.codename).label("codename"))
                        .filter(cls.date > start_time)
                        .filter(cls.codename.startswith(fullname)))
        return [row.codename for row in query]


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

    @classmethod
    @memoize_traffic(time=3600 * 6)
    def history(cls, interval, subreddit):
        start_time, stop_time, q = make_history_query(cls, interval)
        q = q.filter(cls.subreddit == subreddit)
        return fill_gaps(interval, start_time, stop_time, q,
                         "subscriber_count")

# create the tables if they don't exist
if g.db_create_tables:
    Base.metadata.create_all()
