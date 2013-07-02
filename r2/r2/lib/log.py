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
# All portions of the code written by reddit are Copyright (c) 2006-2013 reddit
# Inc. All Rights Reserved.
###############################################################################

import cPickle

from datetime import datetime

from pylons import g, c, request
from weberror.reporter import Reporter


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


class LogQueueErrorReporter(Reporter):
    """ErrorMiddleware-compatible reporter that writes exceptions to log_q.

    The log_q queue processor then picks these up, updates the /admin/errors
    overview, and decides whether or not to send out emails about them.

    """

    @staticmethod
    def _operational_exceptions():
        """Get a list of exceptions caused by transient operational stuff.

        These errors aren't terribly useful to track in /admin/errors because
        they aren't directly bugs in the code but rather symptoms of
        operational issues.

        """

        import _pylibmc
        import sqlalchemy.exc
        import pycassa.pool
        import r2.lib.db.thing
        import r2.lib.lock

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

    def report(self, exc_data):
        from r2.lib import amqp

        if issubclass(exc_data.exception_type, self._operational_exceptions()):
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
