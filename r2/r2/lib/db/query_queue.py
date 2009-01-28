from __future__ import with_statement
from r2.lib.workqueue import WorkQueue
from r2.lib.db.tdb_sql import make_metadata, create_table, index_str

import cPickle as pickle
from datetime import datetime
from urllib2 import Request, urlopen
from urllib import urlencode
from threading import Lock
import time

import sqlalchemy as sa
from sqlalchemy.exceptions import SQLError

from pylons import g
tz = g.tz

#the current 
running = set()
running_lock = Lock()

def make_query_queue_table():
    engine = g.dbm.engines['query_queue']
    metadata = make_metadata(engine)
    table =  sa.Table(g.db_app_name + '_query_queue', metadata,
                      sa.Column('iden', sa.String, primary_key = True),
                      sa.Column('query', sa.Binary),
                      sa.Column('date', sa.DateTime(timezone = True)))
    date_idx = index_str(table, 'date', 'date')
    create_table(table, [date_idx])
    return table

query_queue_table = make_query_queue_table()

def add_query(cached_results):
    """Adds a CachedResults instance to the queue db, ignoring duplicates"""
    d = dict(iden = cached_results.query._iden(),
             query = pickle.dumps(cached_results, -1),
             date = datetime.now(tz))
    try:
        query_queue_table.insert().execute(d)
    except SQLError, e:
        #don't worry about inserting duplicates
        if not 'IntegrityError' in e.message:
            raise

def remove_query(iden):
    """Removes a row identified with iden from the query queue. To be
    called after a CachedResults is updated."""
    table = query_queue_table
    d = table.delete(table.c.iden == iden)
    d.execute()

def get_query():
    """Gets the next query off the queue, ignoring the currently running
    queries."""
    table = query_queue_table

    s = table.select(order_by = sa.asc(table.c.date), limit = 1)
    s.append_whereclause(sa.and_(*[table.c.iden != i for i in running]))
    r = s.execute().fetchone()

    if r:
        return r.iden, r.query
    else:
        return None, None

def make_query_job(iden, pickled_cr):
    """Creates a job to send to the query worker. Updates a cached result
    then removes the query from both the queue and the running set. If
    sending the job fails, the query is only remove from the running
    set."""
    precompute_worker = g.query_queue_worker
    def job():
        try:
            finished = False
            r = Request(url = precompute_worker + '/doquery',
                        data = urlencode([('query', pickled_cr)]),
                        #this header prevents pylons from turning the
                        #parameter into unicode, which breaks pickling
                        headers = {'x-dont-decode':'true'})
            urlopen(r)
            finished = True
        finally:
            with running_lock:
                running.remove(iden)
                #if finished is false, we'll leave the query in the db
                #so we can try again later (e.g. in the event the
                #worker is down)
                if finished:
                    remove_query(iden)
    return job

def run():
    """Pull jobs from the queue, creates a job, and sends them to a
    WorkQueue for processing."""
    num_workers = g.num_query_queue_workers
    wq = WorkQueue(num_workers = num_workers)
    wq.start()

    while True:
        job = None
        #limit the total number of jobs in the WorkQueue. we don't
        #need to load the entire db queue right away (the db queue can
        #get quite large).
        if len(running) < 2 * num_workers:
            with running_lock:
                iden, pickled_cr = get_query()
                if pickled_cr is not None:
                    if not iden in running:
                        running.add(iden)
                        job = make_query_job(iden, pickled_cr)
                        wq.add(job)

        #if we didn't find a job, sleep before trying again
        if not job:
            time.sleep(1)
