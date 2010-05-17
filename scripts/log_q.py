#! /usr/bin/python

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

def run(limit=100, streamfile=None, verbose=False):
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

        for tpl in d['traceback']:
            tb.append(tpl)
            filename, lineno, funcname, text = tpl
            if text is None:
                pass
            elif (text.startswith("with g.make_lock(") or
                  text.startswith("with make_lock(")):
                make_lock_seen = True
            key_material += "%s %s " % (filename, funcname)
            pretty_lines.append ("%s:%s: %s()" % (filename, lineno, funcname))
            pretty_lines.append ("    %s" % text)

        if exc_desc.startswith("QueuePool limit of size"):
            fingerprint = "QueuePool_overflow"
        elif exc_desc.startswith("error 2 from memcached_get: HOSTNAME "):
            fingerprint = "memcache_suckitude"
        elif exc_type == "TimeoutExpired" and make_lock_seen:
            fingerprint = "make_lock_timeout"
        elif exc_type == "NoServerAvailable":
            fingerprint = "cassandra_suckitude"
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

    def myfunc(msgs, chan):
        daystring = datetime.now(g.display_tz).strftime("%Y/%m/%d")

        for msg in msgs:
            try:
                d = pickle.loads(msg.body)
            except TypeError:
                streamlog ("wtf is %r" % msg.body, True)
                continue

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

    amqp.handle_items(q, myfunc, limit=limit, drain=False, verbose=verbose)

