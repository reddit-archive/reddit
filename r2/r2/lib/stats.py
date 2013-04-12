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

import collections
import functools
import os
import random
import socket
import time
import threading

from pycassa import columnfamily
from pycassa import pool

from r2.lib import cache
from r2.lib import utils

class TimingStatBuffer:
    """Dictionary of keys to cumulative time+count values.

    This provides thread-safe accumulation of pairs of values. Iterating over
    instances of this class yields (key, (total_time, count)) tuples.
    """

    Timing = collections.namedtuple('Timing', ['key', 'start', 'end'])


    def __init__(self):
        # Store data internally as a map of keys to complex values. The real
        # part of the complex value is the total time (in seconds), and the
        # imaginary part is the total count.
        self.data = collections.defaultdict(complex)
        self.log = threading.local()

    def record(self, key, start, end, publish=True):
        if publish:
            # Add to the total time and total count with a single complex value,
            # so as to avoid inconsistency from a poorly timed context switch.
            self.data[key] += (end - start) + 1j

        if getattr(self.log, 'timings', None) is not None:
            self.log.timings.append(self.Timing(key, start, end))

    def flush(self):
        """Yields accumulated timing and counter data and resets the buffer."""
        data, self.data = self.data, collections.defaultdict(complex)
        while True:
            try:
                k, v = data.popitem()
            except KeyError:
                break

            total_time, count = v.real, v.imag
            yield k, str(int(count)) + '|c'
            divisor = count or 1
            mean = total_time / divisor
            yield k, str(mean * 1000) + '|ms'

    def start_logging(self):
        self.log.timings = []

    def end_logging(self):
        timings = getattr(self.log, 'timings', None)
        self.log.timings = None
        return timings


class CountingStatBuffer:
    """Dictionary of keys to cumulative counts."""

    def __init__(self):
        self.data = collections.defaultdict(int)

    def record(self, key, delta):
        self.data[key] += delta

    def flush(self):
        """Yields accumulated counter data and resets the buffer."""
        data, self.data = self.data, collections.defaultdict(int)
        for k, v in data.iteritems():
            yield k, str(v) + '|c'


class StringCountBuffer:
    """Dictionary of keys to counts of various values."""

    def __init__(self):
        self.data = collections.defaultdict(
            functools.partial(collections.defaultdict, int))

    @staticmethod
    def _encode_string(string):
        # escape \ -> \\, | -> \&, : -> \;, and newline -> \n
        return (
            string.replace('\\', '\\\\')
                .replace('\n', '\\n')
                .replace('|', '\\&')
                .replace(':', '\\;'))

    def record(self, key, value, count=1):
        self.data[key][value] += count

    def flush(self):
        new_data = collections.defaultdict(
            functools.partial(collections.defaultdict, int))
        data, self.data = self.data, new_data
        for k, counts in data.iteritems():
            for v, count in counts.iteritems():
                yield k, str(count) + '|s|' + self._encode_string(v)


class StatsdConnection:
    def __init__(self, addr, compress=True):
        if addr:
            self.host, self.port = self._parse_addr(addr)
            self.sock = self._make_socket()
        else:
            self.host = self.port = self.sock = None
        self.compress = compress

    @classmethod
    def _make_socket(cls):
        return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    @staticmethod
    def _parse_addr(addr):
        host, port_str = addr.rsplit(':', 1)
        return host, int(port_str)

    @staticmethod
    def _compress(lines):
        compressed_lines = []
        previous = ''
        for line in sorted(lines):
            prefix = os.path.commonprefix([previous, line])
            if len(prefix) > 3:
                prefix_len = len(prefix)
                compressed_lines.append(
                    '^%02x%s' % (prefix_len, line[prefix_len:]))
            else:
                compressed_lines.append(line)
            previous = line
        return compressed_lines

    def send(self, data):
        if self.sock is None:
            return
        data = ('%s:%s' % item for item in data)
        if self.compress:
            data = self._compress(data)
        payload = '\n'.join(data)
        self.sock.sendto(payload, (self.host, self.port))


class StatsdClient:
    _data_iterator = iter
    _make_conn = StatsdConnection

    def __init__(self, addr=None, sample_rate=1.0):
        self.sample_rate = sample_rate
        self.timing_stats = TimingStatBuffer()
        self.counting_stats = CountingStatBuffer()
        self.string_counts = StringCountBuffer()
        self.connect(addr)

    def connect(self, addr):
        self.conn = self._make_conn(addr)

    def disconnect(self):
        self.conn = self._make_conn(None)

    def flush(self):
        data = list(self.timing_stats.flush())
        data.extend(self.counting_stats.flush())
        data.extend(self.string_counts.flush())
        self.conn.send(self._data_iterator(data))


def _get_stat_name(*name_parts):
    def to_str(value):
        if isinstance(value, unicode):
            value = value.encode('utf-8', 'replace')
        return value
    return '.'.join(to_str(x) for x in name_parts if x)


class Counter:
    def __init__(self, client, name):
        self.client = client
        self.name = name

    def _send(self, subname, delta):
        name = _get_stat_name(self.name, subname)
        return self.client.counting_stats.record(name, delta)

    def increment(self, subname=None, delta=1):
        self._send(subname, delta)

    def decrement(self, subname=None, delta=1):
        self._send(subname, -delta)

    def __add__(self, delta):
        self.increment(delta=delta)
        return self

    def __sub__(self, delta):
        self.decrement(delta=delta)
        return self


class Timer:
    _time = time.time

    def __init__(self, client, name, publish=True):
        self.client = client
        self.name = name
        self.publish = publish
        self._start = None
        self._last = None
        self._stop = None
        self._timings = []

    def flush(self):
        for timing in self._timings:
            self.send(*timing)
        self._timings = []

    def elapsed_seconds(self):
        if self._start is None:
            raise AssertionError("timer hasn't been started")
        if self._stop is None:
            raise AssertionError("timer hasn't been stopped")
        return self._stop - self._start

    def send(self, subname, start, end):
        name = _get_stat_name(self.name, subname)
        self.client.timing_stats.record(name, start, end,
                                        publish=self.publish)

    def start(self):
        self._last = self._start = self._time()

    def intermediate(self, subname):
        if self._last is None:
            raise AssertionError("timer hasn't been started")
        if self._stop is not None:
            raise AssertionError("timer is stopped")
        last, self._last = self._last, self._time()
        self._timings.append((subname, last, self._last))

    def stop(self, subname='total'):
        if self._start is None:
            raise AssertionError("timer hasn't been started")
        if self._stop is not None:
            raise AssertionError('timer is already stopped')
        self._stop = self._time()
        self.flush()
        self.send(subname, self._start, self._stop)


class Stats:
    # Sample rate for recording cache hits/misses, relative to the global
    # sample_rate.
    CACHE_SAMPLE_RATE = 0.01

    CASSANDRA_KEY_SUFFIXES = ['error', 'ok']

    def __init__(self, addr, sample_rate):
        self.client = StatsdClient(addr, sample_rate)

    def get_timer(self, name, publish=True):
        return Timer(self.client, name, publish)

    def transact(self, action, start, end):
        timer = self.get_timer('service_time')
        timer.send(action, start, end)

    def get_counter(self, name):
        return Counter(self.client, name)

    def action_count(self, counter_name, name, delta=1):
        counter = self.get_counter(counter_name)
        if counter:
            from pylons import request
            counter.increment('%s.%s' % (request.environ["pylons.routes_dict"]["action"], name), delta=delta)

    def action_event_count(self, event_name, state=None, delta=1, true_name="success", false_name="fail"):
        counter_name = 'event.%s' % event_name
        if state == True:
            self.action_count(counter_name, true_name, delta=delta)
        elif state == False:
            self.action_count(counter_name, false_name, delta=delta)
        self.action_count(counter_name, 'total', delta=delta)

    def simple_event(self, event_name, delta=1):
        parts = event_name.split('.')
        counter = self.get_counter('.'.join(['event'] + parts[:-1]))
        if counter:
            counter.increment(parts[-1], delta=delta)

    def event_count(self, event_name, name):
        counter = self.get_counter('event.%s' % event_name)
        if counter:
            counter.increment(name)
            counter.increment('total')

    def cache_count(self, name, delta=1, sample_rate=None):
        if sample_rate is None:
            sample_rate = self.CACHE_SAMPLE_RATE
        counter = self.get_counter('cache')
        if counter and random.random() < sample_rate:
            counter.increment(name, delta=delta)

    def cache_count_multi(self, data, cache_name=None, sample_rate=None):
        if sample_rate is None:
            sample_rate = self.CACHE_SAMPLE_RATE
        counter = self.get_counter('cache')
        if counter and random.random() < sample_rate:
            for name, delta in data.iteritems():
                counter.increment(name, delta=delta)

    def amqp_processor(self, queue_name):
        """Decorator for recording stats for amqp queue consumers/handlers."""
        def decorator(processor):
            def wrap_processor(msgs, *args):
                # Work the same for amqp.consume_items and amqp.handle_items.
                msg_tup = utils.tup(msgs)

                start = time.time()
                try:
                    return processor(msgs, *args)
                finally:
                    service_time = (time.time() - start) / len(msg_tup)
                    for n, msg in enumerate(msg_tup):
                        fake_start = start + n * service_time
                        fake_end = fake_start + service_time
                        self.transact('amqp.%s' % queue_name,
                                      fake_start, fake_end)
                    self.flush()
            return wrap_processor
        return decorator

    def flush(self):
        self.client.flush()

    def start_logging_timings(self):
        self.client.timing_stats.start_logging()

    def end_logging_timings(self):
        return self.client.timing_stats.end_logging()

    def cassandra_event(self, operation, column_families, success,
                        start, end):
        if not self.client:
            return
        if not isinstance(column_families, list):
            column_families = [column_families]
        for cf in column_families:
            key = '.'.join([
                'cassandra', cf, operation,
                self.CASSANDRA_KEY_SUFFIXES[success]])
            self.client.timing_stats.record(key, start, end)

    def pg_before_cursor_execute(self, conn, cursor, statement, parameters,
                               context, executemany):
        context._query_start_time = time.time()

    def pg_after_cursor_execute(self, conn, cursor, statement, parameters,
                              context, executemany):
        dsn = dict(part.split('=', 1)
                   for part in context.engine.url.query['dsn'].split())
        start = context._query_start_time
        self.pg_event(dsn['host'], dsn['dbname'], start, time.time())

    def pg_event(self, db_server, db_name, start, end):
        if not self.client:
            return
        key = '.'.join(['pg', db_server.replace('.', '-'), db_name])
        self.client.timing_stats.record(key, start, end)

    def count_string(self, key, value, count=1):
        self.client.string_counts.record(key, str(value), count=count)
   

class CacheStats:
    def __init__(self, parent, cache_name):
        self.parent = parent
        self.cache_name = cache_name
        self.hit_stat_name = '%s.hit' % self.cache_name
        self.miss_stat_name = '%s.miss' % self.cache_name
        self.total_stat_name = '%s.total' % self.cache_name

    def cache_hit(self, delta=1):
        if delta:
            self.parent.cache_count(self.hit_stat_name, delta=delta)
            self.parent.cache_count(self.total_stat_name, delta=delta)

    def cache_miss(self, delta=1):
        if delta:
            self.parent.cache_count(self.miss_stat_name, delta=delta)
            self.parent.cache_count(self.total_stat_name, delta=delta)

    def cache_report(self, hits=0, misses=0, cache_name=None, sample_rate=None):
        if hits or misses:
            if not cache_name:
                cache_name = self.cache_name
            hit_stat_name = '%s.hit' % cache_name
            miss_stat_name = '%s.miss' % cache_name
            total_stat_name = '%s.total' % cache_name
            data = {
                hit_stat_name: hits,
                miss_stat_name: misses,
                total_stat_name: hits + misses,
            }
            self.parent.cache_count_multi(data, cache_name=cache_name,
                                          sample_rate=sample_rate)


class StatsCollectingConnectionPool(pool.ConnectionPool):
    def __init__(self, keyspace, stats=None, *args, **kwargs):
        pool.ConnectionPool.__init__(self, keyspace, *args, **kwargs)
        self.stats = stats

    def _get_new_wrapper(self, server):
        host, sep, port = server.partition(':')
        self.stats.event_count('cassandra.connections', host)

        cf_types = (columnfamily.ColumnParent, columnfamily.ColumnPath)

        def get_cf_name_from_args(args, kwargs):
            for v in args:
                if isinstance(v, cf_types):
                    return v.column_family
            for v in kwargs.itervalues():
                if isinstance(v, cf_types):
                    return v.column_family
            return None

        def get_cf_name_from_batch_mutation(args, kwargs):
            cf_names = set()
            mutation_map = args[0]
            for key_mutations in mutation_map.itervalues():
                cf_names.update(key_mutations)
            return list(cf_names)

        instrumented_methods = dict(
            get=get_cf_name_from_args,
            get_slice=get_cf_name_from_args,
            multiget_slice=get_cf_name_from_args,
            get_count=get_cf_name_from_args,
            multiget_count=get_cf_name_from_args,
            get_range_slices=get_cf_name_from_args,
            get_indexed_slices=get_cf_name_from_args,
            insert=get_cf_name_from_args,
            batch_mutate=get_cf_name_from_batch_mutation,
            add=get_cf_name_from_args,
            remove=get_cf_name_from_args,
            remove_counter=get_cf_name_from_args,
            truncate=lambda args, kwargs: args[0],
        )

        def record_error(method_name, cf_name, start, end):
            if cf_name and self.stats:
                self.stats.cassandra_event(method_name, cf_name, False,
                                           start, end)

        def record_success(method_name, cf_name, start, end):
            if cf_name and self.stats:
                self.stats.cassandra_event(method_name, cf_name, True,
                                           start, end)

        def instrument(f, get_cf_name):
            def call_with_instrumentation(*args, **kwargs):
                cf_name = get_cf_name(args, kwargs)
                start = time.time()
                try:
                    result = f(*args, **kwargs)
                except:
                    record_error(f.__name__, cf_name, start, time.time())
                    raise
                else:
                    record_success(f.__name__, cf_name, start, time.time())
                    return result
            return call_with_instrumentation

        wrapper = pool.ConnectionPool._get_new_wrapper(self, server)
        for method_name, get_cf_name in instrumented_methods.iteritems():
            f = getattr(wrapper, method_name)
            setattr(wrapper, method_name, instrument(f, get_cf_name))
        return wrapper

