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

from r2.lib.db.thing import Thing, Relation, MultiRelation, thing_prefix
from r2.lib.utils import tup
from r2.lib.memoize import memoize
from r2.models import Link, Comment, Message, Subreddit, Account
from r2.models.vote import score_changes
from datetime import datetime

from pylons import g

class Report(MultiRelation('report',
                           Relation(Account, Link),
                           Relation(Account, Comment),
                           Relation(Account, Subreddit),
                           Relation(Account, Message)
                           )):

    _field = 'reported'

    @classmethod
    def new(cls, user, thing):
        from r2.lib.db import queries

        # check if this report exists already!
        rel = cls.rel(user, thing)
        q = rel._fast_query(user, thing, ['-1', '0', '1'])
        q = [ report for (tupl, report) in q.iteritems() if report ]
        if q:
            # stop if we've seen this before, so that we never get the
            # same report from the same user twice
            oldreport = q[0]
            g.log.debug("Ignoring duplicate report %s" % oldreport)
            return oldreport

        r = Report(user, thing, '0')
        if not thing._loaded:
            thing._load()

        # mark item as reported
        try:
            thing._incr(cls._field)
        except (ValueError, TypeError):
            g.log.error("%r has bad field %r = %r" % (thing, cls._field,
                         getattr(thing, cls._field, "(nonexistent)")))
            raise

        r._commit()

        if hasattr(thing, 'author_id'):
            author = Account._byID(thing.author_id, data=True)
            author._incr('reported')

        item_age = datetime.now(g.tz) - thing._date
        ignore_reports = getattr(thing, 'ignore_reports', False)
        if item_age.days < g.REPORT_AGE_LIMIT and not ignore_reports:
            # update the reports queue if it exists
            queries.new_report(thing, r)

            # if the thing is already marked as spam, accept the report
            if thing._spam:
                cls.accept(thing)
        else:
            g.log.debug("Ignoring report %s" % r)

        return r

    @classmethod
    def for_thing(cls, thing):
        rel = cls.rel(Account, thing.__class__)
        rels = rel._query(rel.c._thing2_id == thing._id)

        return list(rels)

    @classmethod
    def accept(cls, things, correct = True):
        from r2.lib.db import queries

        things = tup(things)

        things_by_cls = {}
        for thing in things:
            things_by_cls.setdefault(thing.__class__, []).append(thing)

        to_clear = []

        for thing_cls, cls_things in things_by_cls.iteritems():
            # look up all of the reports for each thing
            rel_cls = cls.rel(Account, thing_cls)
            thing_ids = [t._id for t in cls_things]
            rels = rel_cls._query(rel_cls.c._thing2_id == thing_ids)
            for r in rels:
                if r._name == '0':
                    r._name = '1' if correct else '-1'
                    r._commit()

            for thing in cls_things:
                if thing.reported > 0:
                    thing.reported = 0
                    thing._commit()
                    to_clear.append(thing)

        queries.clear_reports(to_clear, rels)

