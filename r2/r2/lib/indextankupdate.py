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
# All portions of the code written by CondeNet are Copyright (c) 2006-2010
# CondeNet, Inc. All Rights Reserved.
################################################################################
"""
    Module for communication reddit-level communication with IndexTank
"""

from __future__ import with_statement

from pylons import g, config

from r2.models import *
from r2.lib.cache import SelfEmptyingCache
from r2.lib import amqp, indextank
from r2.lib.solrsearch import indexed_types
import simplejson
import sys,os,os.path
import time

indextank_indexed_types = (Link,)

index = indextank.IndexTank(api_key = g.INDEXTANK_API_KEY,
                            index_code = g.INDEXTANK_IDX_CODE)

def maps_from_things(things):
    maps = []
    author_ids = [ thing.author_id for thing in things ]
    accounts = Account._byID(author_ids, data = True, return_dict = True)
    for thing in things:
        a = accounts[thing.author_id]
        if a._deleted:
            continue
        d = dict(fullname = thing._fullname,
                 text = thing.title,
                 author = a.name,
                 timestamp = thing._date.strftime("%s"),
                 ups = thing._ups,
                 downs = thing._downs,
                 num_comments = getattr(thing, "num_comments", 0))
        if thing.is_self and thing.selftext:
            d['selftext'] = thing.selftext
        else:
            d['url'] = thing.url
        maps.append(d)
    return maps

def to_boosts(ups, downs, num_comments):
    result = {}
    result[1] = ups
    result[2] = downs
    result[3] = num_comments
    return result

def inject_maps(maps):
    for d in maps:
        fullname = d.pop("fullname")
        ups = d.pop("ups")
        downs = d.pop("downs")
        num_comments = d.pop("num_comments")
        boosts = to_boosts(ups, downs, num_comments)

        if ups not in (0, 1) or downs != 0 or num_comments > 0:
            ok, result = index.boost(fullname, boosts=boosts)
            if ok:
                print "Boost-updated %s in IndexTank" % fullname
                continue
            else:
                print "Failed to update(%r, %r) with IndexTank" % (fullname, boosts)
                f = open("/tmp/indextank-error.html", "w")
                f.write(str(result))
#                g.cache.set("stop-indextank", True)

        ok, result = index.add(fullname, d, boosts)
        if ok:
            print "Added %s to IndexTank" % fullname
        else:
            print "Failed to add(%r, %r, %r) to IndexTank" % (fullname, d, boosts)
            f = open("/tmp/indextank-error.html", "w")
            f.write(str(result))
            g.cache.set("stop-indextank", True)

def delete_thing(thing):
    ok, result = index.delete(thing._fullname)
    if ok:
        print "Deleted %s from IndexTank" % thing._fullname
    else:
        print "Failed to delete %s from IndexTank" % thing._fullname
        f = open("/tmp/indextank-error.html", "w")
        f.write(str(result))
        g.cache.set("stop-indextank", True)

def run_changed(drain=False):
    """
        Run by `cron` (through `paster run`) on a schedule to send Things to
        IndexTank
    """
    def _run_changed(msgs, chan):
        if g.cache.get("stop-indextank"):
            print "discarding %d msgs" % len(msgs)
            return

        fullnames = set([x.body for x in msgs])
        things = Thing._by_fullname(fullnames, data=True, return_dict=False)
        things = [x for x in things if isinstance(x, indextank_indexed_types)]

        update_things = [x for x in things if not x._spam and not x._deleted]
        delete_things = [x for x in things if x._spam or x._deleted]

        if update_things:
            maps = maps_from_things(update_things)
            inject_maps(maps)
        if delete_things:
            for thing in delete_things:
                delete_thing(thing)

    amqp.handle_items('indextank_changes', _run_changed, limit=1000,
                      drain=drain)
