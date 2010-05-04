from threading import Thread
import os
import time

from pylons.controllers.util import abort
from pylons import c, g

from reddit_base import RedditController
from r2.lib.amqp import worker

from validator import *

class HealthController(RedditController):
    def shutdown(self):
        thread_pool = c.thread_pool
        def _shutdown():
            #give busy threads 30 seconds to finish up
            for s in xrange(30):
                busy = thread_pool.track_threads()['busy']
                if not busy:
                    break
                time.sleep(1)

            thread_pool.shutdown()
            worker.join()
            os._exit(3)

        t = Thread(target = _shutdown)
        t.setDaemon(True)
        t.start()

    def GET_health(self):
        c.dontcache = True

        if g.shutdown:
            if g.shutdown == 'init':
                self.shutdown()
                g.shutdown = 'shutdown'
            abort(503, 'service temporarily unavailable')
        else:
            c.response_content_type = 'text/plain'
            c.response.content = "i'm still alive!"
            return c.response

    @validate(secret=nop('secret'))
    def GET_shutdown(self, secret):
        if not g.shutdown_secret:
            self.abort404()
        if not secret or secret != g.shutdown_secret:
            self.abort403()

        c.dontcache = True
        #the will make the next health-check initiate the shutdown
        g.shutdown = 'init'
        c.response_content_type = 'text/plain'
        c.response.content = 'shutting down...'
        return c.response
