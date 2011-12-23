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

    def GET_health(self):
        c.dontcache = True
        response.headers['Content-Type'] = 'text/plain'
        return "i'm still alive!"

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
