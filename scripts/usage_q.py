#! /usr/bin/python

from r2.lib import amqp
from r2.lib.log import log_text
from pylons import g
from datetime import datetime
from time import sleep

import pickle

q = 'usage_q'
tz = g.display_tz

def check_dict(body):
    d = pickle.loads(body)

    for k in ("start_time", "end_time", "action"):
        if k not in d:
            raise TypeError

    return d

def hund_from_start_and_end(start_time, end_time):
    elapsed = end_time - start_time

    hund_sec = int(elapsed.seconds * 100 +
                   elapsed.microseconds / 10000)
    hund_sec = max(hund_sec, 1) # assume every request takes at least 0.01s

    return hund_sec

def trunc_time(time, period):
    return time.replace(minute = period * (time.minute / period),
                        second = 0,
                        microsecond = 0)

def buckets(time):
    time = time.astimezone(tz)

    # Keep:
    #   Daily buckets for eight days
    #   1-hour buckets for 24 hours
    #   5-min buckets for two hours

    return [
             (86400 * 8, time.strftime("%Y/%m/%d_xx:xx")),
             (86400 * 1, time.strftime("%Y/%m/%d_%H:xx")),
             ( 3600 * 2, trunc_time(time,  5).strftime("%Y/%m/%d_%H:%M")),
           ]

def run(limit=1000, verbose=False):
    def myfunc(msgs, chan):
        incrs = {}

        for msg in msgs:
            try:
                d = check_dict(msg.body)
            except TypeError:
                log_text("usage_q error", "wtf is %r" % msg.body, "error")
                continue

            hund_sec = hund_from_start_and_end(d["start_time"], d["end_time"])

            action = d["action"].replace("-", "_")

            for exp_time, bucket in buckets(d["end_time"]):
                k = "%s-%s" % (bucket, action)
                incrs.setdefault(k, [0, 0, exp_time])
                incrs[k][0] += 1
                incrs[k][1] += hund_sec

        for k, (count, elapsed, exp_time) in incrs.iteritems():
            c_key = "profile_count-" + k
            e_key = "profile_elapsed-" + k

            if verbose:
                c_old = g.hardcache.get(c_key)
                e_old = g.hardcache.get(e_key)

            g.hardcache.accrue(c_key, delta=count,   time=exp_time)
            g.hardcache.accrue(e_key, delta=elapsed, time=exp_time)

            if verbose:
                c_new = g.hardcache.get(c_key)
                e_new = g.hardcache.get(e_key)

                print "%s: %s -> %s" % (c_key, c_old, c_new)
                print "%s: %s -> %s" % (e_key, e_old, e_new)

        if len(msgs) < limit / 2:
            if verbose:
                print "Sleeping..."
            sleep (10)
    amqp.handle_items(q, myfunc, limit=limit, drain=False, verbose=verbose,
                      sleep_time = 30)

