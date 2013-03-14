#! /usr/bin/python
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


from r2.lib import amqp, emailer
from pylons import g
from datetime import datetime
from md5 import md5
from random import shuffle, choice

import pickle

try:
    words = file(g.words_file).read().split("\n")
except IOError:
    words = []

shuffle(words)

def randword():
    try:
        return choice(words)
    except IndexError:
        return '???'

q = 'log_q'

def run(streamfile=None, verbose=False):
    if streamfile:
        stream_fp = open(streamfile, "a")
    else:
        stream_fp = None

    def streamlog(msg, important=False):
        if stream_fp:
            stream_fp.write(msg + "\n")
            stream_fp.flush()
        if important:
            print msg

    def add_timestamps (d):
        d['hms'] = d['time'].strftime("%H:%M:%S")

        d['occ'] = "<%s:%s, pid=%-5s, %s>" % (d['host'], d['port'], d['pid'],
                                      d['time'].strftime("%Y-%m-%d %H:%M:%S"))

    def limited_append(l, item):
        if len(l) >= 25:
            l.pop(12)
        l.append(item)

    def log_exception(d, daystring):
        exc_desc = d['exception_desc']
        exc_type = d['exception_type']

        exc_str = "%s: %s" % (exc_type, exc_desc)

        add_timestamps(d)

        tb = []

        key_material = exc_type
        pretty_lines = []

        make_lock_seen = False
        flaky_db_seen = False
        cassandra_seen = False

        for tpl in d['traceback']:
            tb.append(tpl)
            filename, lineno, funcname, text = tpl
            if text is None:
                pass
            elif (text.startswith("with g.make_lock(") or
                  text.startswith("with make_lock(")):
                make_lock_seen = True
            elif (text.startswith("(ProgrammingError) server closed the connection")):
                flaky_db_seen = True
            if '/cassandra/' in filename.lower():
                cassandra_seen = True
            if '/pycassa/' in filename.lower():
                cassandra_seen = True
            key_material += "%s %s " % (filename, funcname)
            pretty_lines.append ("%s:%s: %s()" % (filename, lineno, funcname))
            pretty_lines.append ("    %s" % text)

        if exc_desc.startswith("QueuePool limit of size"):
            fingerprint = "QueuePool_overflow"
        elif exc_desc.startswith("error 2 from memcached_get: HOSTNAME "):
            fingerprint = "memcache_suckitude"
        elif exc_type == "TimeoutExpired" and make_lock_seen:
            fingerprint = "make_lock_timeout"
        elif exc_desc.startswith("(OperationalError) FATAL: the database " +
                                 "system is in recovery mode"):
            fingerprint = "recovering_db"
        elif exc_desc.startswith("(OperationalError) could not connect " +
                                 "to server"):
            fingerprint = "unconnectable_db"
        elif exc_desc.startswith("(OperationalError) server closed the " +
                                 "connection unexpectedly"):
            fingerprint = "flaky_db_op"
        elif cassandra_seen:
            fingerprint = "something's wrong with cassandra"
        else:
            fingerprint = md5(key_material).hexdigest()

        nickname_key = "error_nickname-" + fingerprint
        status_key = "error_status-" + fingerprint

        nickname = g.hardcache.get(nickname_key)

        if nickname is None:
            nickname = '"%s" Exception' % randword().capitalize()
            news = ("A new kind of thing just happened! " +
                    "I'm going to call it a %s\n\n" % nickname)

            news += "Where and when: %s\n\n" % d['occ']
            news += "Traceback:\n"
            news += "\n".join(pretty_lines)
            news += exc_str
            news += "\n"

            emailer.nerds_email(news, "Exception Watcher")

            g.hardcache.set(nickname_key, nickname, 86400 * 365)
            g.hardcache.set(status_key, "new", 86400)

        if g.hardcache.get(status_key) == "fixed":
            g.hardcache.set(status_key, "new", 86400)
            news = "This was marked as fixed: %s\n" % nickname
            news += "But it just occurred, so I'm marking it new again."
            emailer.nerds_email(news, "Exception Watcher")

        err_key = "-".join(["error", daystring, fingerprint])

        existing = g.hardcache.get(err_key)

        if not existing:
            existing = dict(exception=exc_str, traceback=tb, occurrences=[])

        existing.setdefault('times_seen', 0)
        existing['times_seen'] += 1

        limited_append(existing['occurrences'], d['occ'])

        g.hardcache.set(err_key, existing, 7 * 86400)

        streamlog ("%s [X] %-70s" % (d['hms'], nickname), verbose)

    def log_text(d, daystring):
        add_timestamps(d)
        char = d['level'][0].upper()
        streamlog ("%s [%s] %r" % (d['hms'], char, d['text']), verbose)
        logclass_key = "logclass-" + d['classification']

        if not g.hardcache.get(logclass_key):
            g.hardcache.set(logclass_key, True, 86400 * 90)

            if d['level'] != 'debug':
                news = "The code just generated a [%s] message.\n" % \
                       d['classification']
                news += "I don't remember ever seeing one of those before.\n"
                news += "\n"
                news += "It happened on: %s\n" % d['occ']
                news += "The log level was: %s\n" % d['level']
                news += "The complete text was:\n"
                news += repr(d['text'])
                emailer.nerds_email (news, "reddit secretary")

        occ_key = "-".join(["logtext", daystring,
                            d['level'], d['classification']])

        occurrences = g.hardcache.get(occ_key)

        if occurrences is None:
            occurrences = []

        d2 = {}

        d2['occ'] = d['occ']
        d2['text'] = repr(d['text'])

        limited_append(occurrences, d2)
        g.hardcache.set(occ_key, occurrences, 86400 * 7)

    def myfunc(msg):
        daystring = datetime.now(g.display_tz).strftime("%Y/%m/%d")

        try:
            d = pickle.loads(msg.body)
        except TypeError:
            streamlog ("wtf is %r" % msg.body, True)
            return

        if not 'type' in d:
            streamlog ("wtf is %r" % d, True)
        elif d['type'] == 'exception':
            try:
                log_exception(d, daystring)
            except Exception as e:
                print "Error in log_exception(): %r" % e
        elif d['type'] == 'text':
            try:
                log_text(d, daystring)
            except Exception as e:
                print "Error in log_text(): %r" % e
        else:
            streamlog ("wtf is %r" % d['type'], True)

    amqp.consume_items(q, myfunc, verbose=verbose)

