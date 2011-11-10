import random
import time

from r2.lib import cache
from r2.lib import utils

class Stats:
    # Sample rate for recording cache hits/misses, relative to the global
    # sample_rate.
    CACHE_SAMPLE_RATE = 0.01

    def __init__(self, addr, sample_rate):
        if addr:
            import statsd
            self.statsd = statsd
            self.host, port = addr.split(':')
            self.port = int(port)
            self.sample_rate = sample_rate
            self.connection = self.statsd.connection.Connection(
                self.host, self.port, self.sample_rate)
        else:
            self.host = None
            self.port = None
            self.sample_rate = None
            self.connection = None

    def get_timer(self, name):
        if self.connection:
            return self.statsd.timer.Timer(name, self.connection)
        else:
            return None

    def transact(self, action, service_time_sec):
        timer = self.get_timer('service_time')
        if timer:
            timer.send(action, service_time_sec)

    def get_counter(self, name):
        if self.connection:
            return self.statsd.counter.Counter(name, self.connection)
        else:
            return None

    def cache_count(self, name, delta=1):
        counter = self.get_counter('cache')
        if counter and random.random() < self.CACHE_SAMPLE_RATE:
            counter.increment(name, delta=delta)

    def amqp_processor(self, processor):
        """Decorator for recording stats for amqp queue consumers/handlers."""
        def wrap_processor(msgs, *args):
            # Work the same for amqp.consume_items and amqp.handle_items.
            msg_tup = utils.tup(msgs)

            start = time.time()
            try:
                return processor(msgs, *args)
            finally:
                service_time = (time.time() - start) / len(msg_tup)
                for msg in msg_tup:
                    self.transact('amqp.%s' % msg.delivery_info['routing_key'],
                                  service_time)
        return wrap_processor

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
