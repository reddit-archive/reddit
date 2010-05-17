import cPickle as pickle
from datetime import datetime

from r2.lib import amqp

from pylons import g

working_prefix = 'working_'
prefix = 'prec_link_'
TIMEOUT = 600 # after TIMEOUT seconds, assume that the process
              # calculating a given query has crashed and allow it to
              # be rerun as appropriate

def add_query(cached_results):
    amqp.add_item('prec_links', pickle.dumps(cached_results, -1),
                  delivery_mode = amqp.DELIVERY_TRANSIENT)

def run():
    def callback(msg):
        # cr is a r2.lib.db.queries.CachedResults
        cr = pickle.loads(msg.body)
        iden = cr.query._iden()

        working_key = working_prefix + iden
        key = prefix + iden

        last_time = g.memcache.get(key)
        # check to see if we've computed this job since it was
        # added to the queue
        if last_time and last_time > msg.timestamp:
            print 'skipping, already computed ', key
            return

        if not cr.preflight_check():
            print 'skipping, preflight check failed', key
            return

        # check if someone else is working on this
        elif not g.memcache.add(working_key, 1, TIMEOUT):
            print 'skipping, someone else is working', working_key
            return

        print 'working: ', iden, cr.query._rules, cr.query._sort
        start = datetime.now()
        try:
            cr.update()
            g.memcache.set(key, datetime.now())

            cr.postflight()

        finally:
            g.memcache.delete(working_key)

        done = datetime.now()
        q_time_s = (done - msg.timestamp).seconds
        proc_time_s = (done - start).seconds + ((done - start).microseconds/1000000.0)
        print ('processed %s in %.6f seconds after %d seconds in queue'
               % (iden, proc_time_s, q_time_s))

    amqp.consume_items('prec_links', callback)
