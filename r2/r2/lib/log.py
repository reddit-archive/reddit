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
# All portions of the code written by reddit are Copyright (c) 2006-2015 reddit
# Inc. All Rights Reserved.
###############################################################################

import cPickle
from datetime import datetime
from hashlib import md5

from pylons import request
from pylons import tmpl_context as c
from pylons import app_globals as g
from pylons.util import PylonsContext, AttribSafeContextObj, ContextObj
import raven
from raven.processors import Processor
from weberror.reporter import Reporter

from r2.lib.app_globals import Globals


QUEUE_NAME = 'log_q'


def _default_dict():
    return dict(time=datetime.now(g.display_tz),
                host=g.reddit_host,
                port="default",
                pid=g.reddit_pid)


def log_text(classification, text=None, level="info"):
    """Send some log text to log_q for appearance in the streamlog.

    This is deprecated. All logging should be done through python's stdlib
    logging library.

    """

    from r2.lib import amqp
    from r2.lib.filters import _force_utf8

    if text is None:
        text = classification

    if level not in ('debug', 'info', 'warning', 'error'):
        print "What kind of loglevel is %s supposed to be?" % level
        level = 'error'

    d = _default_dict()
    d['type'] = 'text'
    d['level'] = level
    d['text'] = _force_utf8(text)
    d['classification'] = classification

    amqp.add_item(QUEUE_NAME, cPickle.dumps(d))


def get_operational_exceptions():
    import _pylibmc
    import sqlalchemy.exc
    import pycassa.pool
    import r2.lib.db.thing
    import r2.lib.lock
    import r2.lib.cache

    return (
        SystemExit,  # gunicorn is shutting us down
        _pylibmc.MemcachedError,
        r2.lib.db.thing.NotFound,
        r2.lib.lock.TimeoutExpired,
        sqlalchemy.exc.OperationalError,
        sqlalchemy.exc.IntegrityError,
        pycassa.pool.AllServersUnavailable,
        pycassa.pool.NoConnectionAvailable,
        pycassa.pool.MaximumRetryException,
    )


class LogQueueErrorReporter(Reporter):
    """ErrorMiddleware-compatible reporter that writes exceptions to log_q.

    The log_q queue processor then picks these up, updates the /admin/errors
    overview, and decides whether or not to send out emails about them.

    """

    def report(self, exc_data):
        from r2.lib import amqp

        if issubclass(exc_data.exception_type, get_operational_exceptions()):
            return

        d = _default_dict()
        d["type"] = "exception"
        d["exception_type"] = exc_data.exception_type.__name__
        d["exception_desc"] = exc_data.exception_value
        # use the format that log_q expects; same as traceback.extract_tb
        d["traceback"] = [(f.filename, f.lineno, f.name,
                           f.get_source_line().strip())
                          for f in exc_data.frames]

        amqp.add_item(QUEUE_NAME, cPickle.dumps(d))


class SanitizeStackLocalsProcessor(Processor):
    keys_to_remove = (
        "self",
        "__traceback_supplement__",
    )

    classes_to_remove = (
        Globals,
        PylonsContext,
        AttribSafeContextObj,
        ContextObj,
    )

    def filter_stacktrace(self, data, **kwargs):
        def remove_keys(obj):
            if isinstance(obj, dict):
                for k in obj.keys():
                    if k in self.keys_to_remove:
                        obj.pop(k)
                    elif isinstance(obj[k], self.classes_to_remove):
                        obj.pop(k)
                    elif isinstance(obj[k], basestring):
                        contains_forbidden_repr = any(
                            _cls.__name__ in obj[k]
                            for _cls in self.classes_to_remove
                        )
                        if contains_forbidden_repr:
                            obj.pop(k)
                    elif isinstance(obj[k], (list, dict)):
                        remove_keys(obj[k])
            elif isinstance(obj, list):
                for v in obj:
                    if isinstance(v, (list, dict)):
                        remove_keys(v)

        for frame in data.get('frames', []):
            if 'vars' in frame:
                remove_keys(frame['vars'])


class RavenErrorReporter(Reporter):
    @classmethod
    def get_module_versions(cls):
        return {
            repo: commit_hash[:6]
            for repo, commit_hash in g.versions.iteritems()
        }

    @classmethod
    def get_raven_client(cls):
        repositories = g.versions.keys()
        release_str = '|'.join(
           "%s:%s" % (repo, commit_hash)
           for repo, commit_hash in sorted(g.versions.items())
        )
        release_hash = md5(release_str).hexdigest()

        RAVEN_CLIENT = raven.Client(
            dsn=g.sentry_dsn,
            # use the default transport to send errors from another thread:
            transport=raven.transport.threaded.ThreadedHTTPTransport,
            include_paths=repositories,
            processors=[
                'raven.processors.SanitizePasswordsProcessor',
                'r2.lib.log.SanitizeStackLocalsProcessor',
            ],
            release=release_hash,
            environment=g.pool_name,
            include_versions=False,     # handled by get_module_versions
        )
        return RAVEN_CLIENT

    def report(self, exc_data):
        if issubclass(exc_data.exception_type, get_operational_exceptions()):
            return

        client = self.get_raven_client()

        client.captureException(data={
            "modules": self.get_module_versions(),
        })


def write_error_summary(error):
    """Log a single-line summary of the error for easy log grepping."""
    fullpath = request.environ.get('FULLPATH', request.path)
    uid = c.user._id if c.user_is_loggedin else '-'
    g.log.error("E: %s U: %s FP: %s", error, uid, fullpath)


class LoggingErrorReporter(Reporter):
    """ErrorMiddleware-compatible reporter that writes exceptions to g.log."""

    def report(self, exc_data):
        # exception_formatted is the output of traceback.format_exception_only
        exception = exc_data.exception_formatted[-1].strip()

        # First emit a single-line summary.  This is great for grepping the
        # streaming log for errors.
        write_error_summary(exception)

        text, extra = self.format_text(exc_data)
        # TODO: send this all in one burst so that error reports aren't
        # interleaved / individual lines aren't dropped. doing so will take
        # configuration on the syslog side and potentially in apptail as well
        for line in text.splitlines():
            g.log.warning(line)
