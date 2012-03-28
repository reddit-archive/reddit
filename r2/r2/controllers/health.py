from threading import Thread
import os
import time
import json

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
        return json.dumps(g.versions, sort_keys=True, indent=4)
