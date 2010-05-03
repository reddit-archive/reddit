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
# The Original Code is Reddit.
# 
# The Original Developer is the Initial Developer.  The Initial Developer of the
# Original Code is CondeNet, Inc.
# 
# All portions of the code written by CondeNet are Copyright (c) 2006-2009
# CondeNet, Inc. All Rights Reserved.
################################################################################

from pylons import g
from Queue import Queue, Empty
from threading import Thread
from datetime import datetime, timedelta
import time

log = g.log


class WorkQueue(object):
    """A WorkQueue is a queue that takes a number of functions and runs
    them in parallel"""
    global_env = g._current_obj()

    def __init__(self, jobs = [], num_workers = 5, timeout = None):
        """Creates a WorkQueue that will process jobs with num_workers
        threads. If a job takes longer than timeout seconds to run, WorkQueue
        won't wait for it to finish before claiming to be finished."""
        self.jobs = Queue()
        self.work_count = Queue(num_workers)
        self.workers = {}
        if timeout:
            self.timeout = timedelta(seconds = timeout)
        else:
            self.timeout = None

        for j in jobs:
            self.jobs.put(j)

    def monitor(self):
        """The monitoring thread. Every second it checks for finished, dead,
        or timed-out jobs and removes them from the queue."""
        while True:
            for worker, start_time in self.workers.items():
                if (not worker.isAlive() or
                    self.timeout
                    and datetime.now() - start_time > self.timeout):

                    self.work_count.get_nowait()
                    self.jobs.task_done()
                    del self.workers[worker]

            time.sleep(1)

    def _init_thread(self, job, global_env):
        # make sure that pylons.g is available for the worker thread
        g._push_object(global_env)
        try:
            job()
        finally:
            # free it up
            g._pop_object()

    def run(self):
        """The main thread for the queue. Pull a job off the job queue and
        create a thread for it."""
        while True:
            job = self.jobs.get()

            work_thread = Thread(target = self._init_thread,
                                 args=(job, self.global_env))
            work_thread.setDaemon(True)
            self.work_count.put(True)
            self.workers[work_thread] = datetime.now()
            work_thread.start()

    def start(self):
        """Spawn a monitoring thread and the main thread for this queue. """
        monitor_thread = Thread(target = self.monitor)
        monitor_thread.setDaemon(True)
        monitor_thread.start()

        main_thread = Thread(target = self.run)
        main_thread.setDaemon(True)
        main_thread.start()

    def add(self, job):
        """Put a new job on the queue."""
        self.jobs.put(job)

    def wait(self):
        """Blocks until every job that has been added to the queue is
        finished."""
        self.jobs.join()

    def __enter__(self):
        "required for 'with' blocks"
        self.start()
        return self

    def __exit__(self, _type, _value, _tb):
        "required for 'with' blocks"
        self.wait()


def test():
    import random, time

    def make_job(n):
        def job():
            print 'starting %s' % n
            time.sleep(random.randint(1, 10))
            print 'ending %s' % n
        return job

    print "TEST 1 (premade jobs)"
    jobs = [make_job(n) for n in xrange(10)]
    wq = WorkQueue(jobs, timeout = 5)
    wq.start()
    wq.wait()

    print "TEST 2 (jobs added while running)"
    with WorkQueue(jobs, timeout = 5) as wq:
        for x in range(10):
            print 'added job %d' % x
            wq.add(make_job(x))

    print 'DONE'
