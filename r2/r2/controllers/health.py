from threading import Thread
import os
import time

from pylons.controllers.util import abort
from pylons import c, g, response

from reddit_base import MinimalController
from r2.lib.amqp import worker

from validator import *

class HealthController(MinimalController):
    def post(self):
        pass

    def try_pagecache(self):
        pass

    def pre(self):
        pass

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
            response.headers['Content-Type'] = 'text/plain'
            return "i'm still alive!"

    @validate(secret=nop('secret'))
    def GET_threads(self, secret):
        if not g.shutdown_secret:
            self.abort404()
        if not secret or secret != g.shutdown_secret:
            self.abort403()

        c.dontcache = True

        if g.shutdown:
            c.response.content = "not bothering to check, due to shutdown"
        else:
            thread_pool = c.thread_pool
            tt = thread_pool.track_threads()
            s = ''
            for k in ('idle', 'busy', 'hung', 'dying', 'zombie'):
                s += "%s=%s " % (k, len(tt[k]))

            s += "\n"
            c.response.content = s

        response.headers['Content-Type'] = 'text/plain'
        return c.response

    @validate(secret=nop('secret'))
    def GET_sleep(self, secret):
        if not g.shutdown_secret:
            self.abort404()
        if not secret or secret != g.shutdown_secret:
            self.abort403()

        from time import sleep
        seconds = int(request.GET.get('time', 60))
        seconds = min(seconds, 300)
        sleep(seconds)
        response.headers['Content-Type'] = 'text/plain'
        return "slept"

    @validate(secret=nop('secret'))
    def GET_dump(self, secret):
        import sys, traceback, threading

        if not g.shutdown_secret:
            self.abort404()
        if not secret or secret != g.shutdown_secret:
            self.abort403()

        thread_pool = c.thread_pool

        this_thread = threading.current_thread().ident

        idle = thread_pool.idle_workers
        busy = []

        for thread in thread_pool.workers:
            if thread.ident not in idle:
                busy.append(thread.ident)

        output = ''
        for thread_id, stack in sys._current_frames().items():
            if thread_id == this_thread:
                continue
            if thread_id not in busy:
                continue
            output += '%s\n' % thread_id
            tb = traceback.extract_stack(stack)

            for i, (filename, lineno, fnname, line) in enumerate(tb):
                output += ('    %(filename)s(%(lineno)d): %(fnname)s\n'
                           % dict(filename=filename, lineno=lineno, fnname=fnname))
                output += ('      %(line)s\n' % dict(line=line))

            output += "\n"

        response.headers['Content-Type'] = 'text/plain'
        return output or 'no busy threads'

    @validate(secret=nop('secret'))
    def GET_shutdown(self, secret):
        if not g.shutdown_secret:
            self.abort404()
        if not secret or secret != g.shutdown_secret:
            self.abort403()

        c.dontcache = True
        #the will make the next health-check initiate the shutdown
        g.shutdown = 'init'
        response.headers['Content-Type'] = 'text/plain'
        return 'shutting down...'
