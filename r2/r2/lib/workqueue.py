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
# All portions of the code written by CondeNet are Copyright (c) 2006-2008
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

    def __init__(self, jobs, num_workers = 5, timeout = 30):
        """Creates a WorkQueue that will process jobs with num_workers
        threads. If a job takes longer than timeout seconds to run, WorkQueue
        won't wait for it to finish before claiming to be finished."""
        self.jobs = Queue()
        self.work_count = Queue(num_workers)
        self.workers = {}
        self.timeout = timedelta(seconds = timeout)

        for j in jobs:
            self.jobs.put(j)

    def monitor(self):
        done = False
        while not done:
            if self.jobs.empty() and not self.workers:
                done = True

            for worker, start_time in self.workers.items():
                if (not worker.isAlive() or
                    datetime.now() - start_time > self.timeout): 
                    self.work_count.get_nowait()
                    self.jobs.task_done()
                    del self.workers[worker]

            time.sleep(1)

    def start(self):
        monitor_thread = Thread(target = self.monitor)
        monitor_thread.setDaemon(True)
        monitor_thread.start()

        while not self.jobs.empty():
            job = self.jobs.get()

            work_thread = Thread(target = job)
            work_thread.setDaemon(True)
            self.work_count.put(True)
            self.workers[work_thread] = datetime.now()
            work_thread.start()

if __name__ == '__main__':
    def make_job(n):
        import random, time
        def job():
            print 'starting %s' % n
            time.sleep(random.randint(1, 10))
            print 'ending %s' % n
        return job

    jobs = [make_job(n) for n in xrange(10)]
    wq = WorkQueue(jobs, timeout = 2)
    wq.start()
    wq.jobs.join()
    print 'DONE'

