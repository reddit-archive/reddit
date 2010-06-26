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

from pylons import g, config

from r2.models import *
from r2.lib import amqp, indextank
from r2.lib.utils import in_chunks, progress

indextank_indexed_types = (Link,)

index = indextank.IndexTank(api_key = g.INDEXTANK_API_KEY,
                            index_code = g.INDEXTANK_IDX_CODE)

def maps_from_things(things):
    """We only know how to do links for now"""

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
                 num_comments = getattr(thing, "num_comments", 0),
                 sr_id = str(thing.sr_id))
        if thing.is_self and thing.selftext:
            d['selftext'] = thing.selftext
        elif not thing.is_self:
            d['url'] = thing.url
        maps.append(d)
    return maps

def to_boosts(ups, downs, num_comments):
    result = {}
    result[0] = ups
    result[1] = downs
    result[2] = num_comments
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
            if not ok:
                raise Exception(result)

        ok, result = index.add(fullname, d, boosts)
        if not ok:
            raise Exception(result)

def delete_thing(thing):
    ok, result = index.delete(thing._fullname)
    if not ok:
        raise Exception(result)

def inject(things):
    things = [x for x in things if isinstance(x, indextank_indexed_types)]

    update_things = [x for x in things if not x._spam and not x._deleted
                     and x.promoted is None
                     and getattr(x, 'sr_id') != -1]
    delete_things = [x for x in things if x._spam or x._deleted]

    if update_things:
        maps = maps_from_things(update_things)
        inject_maps(maps)
    if delete_things:
        for thing in delete_things:
            delete_thing(thing)

def rebuild_index(after_id = None):
    cls = Link

    # don't pull spam/deleted
    q = cls._query(sort=desc('_date'), data=True)

    if after_id:
        q._after(cls._byID(after_id))

    q = fetch_things2(q)

    q = progress(q, verbosity=1000, estimate=10000000, persec=True)
    for chunk in in_chunks(q):
        inject(chunk)

def run_changed(drain=False):
    """
        Run by `cron` (through `paster run`) on a schedule to send Things to
        IndexTank
    """
    def _run_changed(msgs, chan):
        fullnames = set([x.body for x in msgs])
        things = Thing._by_fullname(fullnames, data=True, return_dict=False)
        inject(things)

    amqp.handle_items('indextank_changes', _run_changed, limit=1000,
                      drain=drain)
