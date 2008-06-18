# "The contents of this file are subject to the Common Public Attribution
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
# All portions of the code written by CondeNet are Copyright (c) 2006-2008
# CondeNet, Inc. All Rights Reserved.
################################################################################
import sqlalchemy as sa

from r2.lib.db import tdb_sql as tdb
from r2.lib.db.operators import desc
from r2.lib.db.thing import Thing, Relation, NotFound, MultiRelation,\
     thing_prefix

from r2.lib.utils import tup, Storage
from link import Link, Comment, Message, Subreddit
from account import Account
from vote import score_changes
from r2.lib.memoize import memoize, clear_memo

from r2.config import cache
from r2.lib.cache import sgm
import datetime
import thing_changes as tc
from admintools import admintools


class Report(MultiRelation('report',
                           Relation(Account, Link),
                           Relation(Account, Comment),
                           Relation(Account, Subreddit),
                           Relation(Account, Message)
                           )):

    _field = 'reported'
    @property
    def _user(self): return self._thing1

    @property
    def _thing(self): return self._thing2
    
    @classmethod
    def new(cls, user, thing):
        # check if this report exists already!
        rel = cls.rel(user, thing)
        oldreport = list(rel._query(rel.c._thing1_id == user._id,
                                    rel.c._thing2_id == thing._id,
                                    data = True))

        # stop if we've seen this before, so that we never get the
        # same report from the same user twice
        if oldreport: return oldreport[0]

        r = Report(user, thing, '0', amount = 0)
        if not thing._loaded: thing._load()

        # mark item as reported
        thing._incr(cls._field)

        # mark author as reported
        aid = thing.author_id
        author = Account._byID(aid)
        author._incr(cls._field)
        
        # mark user as having made a report
        user._incr('report_made')
        
        r._commit()

        admintools.report(thing)

        # if the thing is already marked as spam, accept the report
        if thing._spam:
            cls.accept(r)
        else:
            # set the report amount to 0, updating the cache in the process
            cls.set_amount(r, 0)
        return r


    @classmethod
    def set_amount(cls, r, amount):
        old_amount = int(r._name)
        if old_amount != amount:
            r._name = str(amount)
            r._commit()
            
        #update the cache for the amount = 0 and amount = None cases
        rel = cls.rels[(r._thing1.__class__, r._thing2.__class__)]
        for a in set((old_amount, amount, None)):
            # clear memoizing around this thing's author
            if not r._thing2._loaded: r._thing2._load()
            clear_memo('report._by_author', cls, r._thing2.author_id,
                       amount = a)

            for t in (r._thing1, r._thing2):
                thing_key = cls._cache_prefix(rel, t.__class__,
                                              amount = a) + str(t._id)
                v = cache.get(thing_key)
                if v is not None:
                    if a == old_amount and old_amount != amount and r._id in v:
                        v.remove(r._id)
                    elif r._id not in v:
                        v.append(r._id)
                    cache.set(thing_key, v)


    @classmethod
    def accept(cls, r, correct = True):
        ''' sets the various reporting fields, but does nothing to
        the corresponding spam fields (handled by unreport)'''
        amount = 1 if correct else -1
        oldamount = int(r._name)

        # do nothing if nothing has changed
        if amount == oldamount: return

        up_change, down_change = score_changes(amount, oldamount)
        
        # update the user who made the report
        r._thing1._incr('report_correct', up_change)
        r._thing1._incr('report_ignored', down_change)

        # update the amount
        cls.set_amount(r, amount)

        # update the thing's number of reports only if we made no
        # decision prior to this
        if oldamount == 0:
            # update the author and thing field
            if getattr(r._thing2, Report._field) > 0:
                r._thing2._incr(Report._field, -1)
            aid = r._thing2.author_id
            author = Account._byID(aid)
            if getattr(author, Report._field) > 0:
                author._incr(Report._field, -1)

            admintools.report(r._thing2, -1)

    
    @classmethod
    @memoize('report._by_author')
    def _by_author_cache(cls, author_id, amount = None):
        res = {}
        for types, rel in cls.rels.iteritems():
            # grab the proper thing table
            thing_type = types[1]
            thing_dict = tdb.types_id[thing_type._type_id]
            dtable, table = thing_dict.data_table

            # and the proper relationship table
            rel_table = tdb.rel_types_id[rel._type_id].rel_table[0]
            rel_dtable = tdb.rel_types_id[rel._type_id].rel_table[-1]

            where = [dtable.c.key == 'author_id',
                     sa.func.substring(dtable.c.value, 1, 1000) == author_id,
                     dtable.c.thing_id == rel_table.c.thing2_id]
            if amount is not None:
                where.extend([rel_table.c.name == str(amount),
                              rel_table.c.rel_id == rel_dtable.c.thing_id])

            s = sa.select([rel_table.c.rel_id],
                          sa.and_(*where))
            rids = [x[0] for x in s.execute().fetchall()]
            if rids: res[types] = rids
        return res

    @classmethod
    def _by_author(cls, author, amount = None):
        res = []
        rdict = cls._by_author_cache(author._id, amount = amount)
        for types, rids in rdict.iteritems():
            res.extend(cls.rels[types]._byID(rids, data=True,
                                             return_dict = False))
        return res


    @classmethod
    def fastreported(cls, users, things, amount = None):
        if amount is None:
            amount = ('1', '0', '-1')
        res = cls._fast_query(users, things, amount)
        res = dict((tuple(k[:2]), v) for k, v in res.iteritems() if v)
        return res

    @classmethod
    def reported(cls, users = None, things = None,
                 return_dict=True, amount = None):

        # nothing given, nothing to give back
        if not users and not things:
            return {} if return_dict else []

        if users: users = tup(users)
        if things: things = tup(things)

        # if both are given, we can use fast_query
        if users and things:
            return cls.fastreported(users, things)

        # type_dict stores id keyed on (type, rel_key) 
        type_dict = {}

        # if users, we have to search all the rel types on thing1_id
        if users:
            db_key = '_thing1_id'
            uid = [t._id for t in users]
            for key in cls.rels.keys():
                type_dict[(Account, key)] = uid

        # if things, we have to search only on types present in the list
        if things:
            db_key = '_thing2_id'
            for t in things:
                key = (t.__class__, (Account, t.__class__))
                type_dict.setdefault(key, []).append(t._id)

        def db_func(rel, db_key, amount):
            def _db_func(ids):
                q = rel._query(getattr(rel.c, db_key) == ids,
                               data = True)
                if amount is not None:
                    q._filter(rel.c._name == str(amount))
                r_ids = {}
                
                # fill up the report listing from the query
                for r in q:
                    key = getattr(r, db_key)
                    r_ids.setdefault(key, []).append(r._id)

                # add blanks where no results were returned
                for i in ids:
                    if i not in r_ids:
                        r_ids[i] = []
                    
                return r_ids
            return _db_func
        
        rval = []
        for (thing_class, rel_key), ids in type_dict.iteritems():
            rel = cls.rels[rel_key]
            prefix = cls._cache_prefix(rel, thing_class, amount=amount)

            # load from cache
            res = sgm(cache, ids, db_func(rel, db_key, amount), prefix)

            # append *objects* to end of list
            res1 = []
            for x in res.values(): res1.extend(x)
            if res1:
                rval.extend(rel._byID(res1, data=True, return_dict=False))

        if return_dict:
            return dict(((r._thing1, r._thing2, cls._field), r) for r in rval)
        return rval

            
    @classmethod
    def _cache_prefix(cls, rel, t_class, amount = None):
        # encode the amount keyword on the prefix
        prefix = thing_prefix(rel.__name__) + '_' + \
                 thing_prefix(t_class.__name__)
        if amount is not None:
            prefix += ("_amount_%d" % amount)
        return prefix
        
    @classmethod
    def get_reported_authors(cls, time = None, sort = None):
        reports = {}
        for t_cls in (Link, Comment, Message):
            q = t_cls._query(t_cls.c._spam == False,
                             t_cls.c.reported > 0,
                             data = True)
            q._sort = desc("_date")
            if time:
                q._filter(time)
            reports.update(Report.reported(things = list(q), amount = 0))

        # at this point, we have a full list of reports made on the interval specified
        # build up an author to report list
        authors = Account._byID([k[1].author_id 
                                 for k, v in reports.iteritems()],
                                data = True) if reports else []

        # and build up a report on each author
        author_rep = {}
        for (tattler, thing, amount), r in reports.iteritems():
            aid = thing.author_id
            if not author_rep.get(aid):
                author_rep[aid] = Storage(author = authors[aid])
                author_rep[aid].num_reports = 1
                author_rep[aid].acct_correct = tattler.report_correct
                author_rep[aid].acct_wrong = tattler.report_ignored
                author_rep[aid].most_recent = r._date
                author_rep[aid].reporters = set([tattler])
            else:
                author_rep[aid].num_reports += 1
                author_rep[aid].acct_correct += tattler.report_correct
                author_rep[aid].acct_wrong += tattler.report_ignored
                if author_rep[aid].most_recent < r._date:
                    author_rep[aid].most_recent = r._date
                author_rep[aid].reporters.add(tattler)
                
        authors = author_rep.values()
        if sort == "hot":
            def report_hotness(a):
                return a.acct_correct / max(a.acct_wrong + a.acct_correct,1)
            def better_reporter(a, b):
                q = report_hotness(b) - report_hotness(a)
                if q == 0:
                    return b.acct_correct - a.acct_correct
                else:
                    return 1 if q > 0 else -1
            authors.sort(better_reporter)
        if sort == "top":
            authors.sort(lambda x, y: y.num_reports - x.num_reports)
        elif sort == "new":
            def newer_reporter(a, b):
                t = b.most_recent - a.most_recent
                t0 = datetime.timedelta(0)
                return 1 if t > t0 else -1 if t < t0 else 0
            authors.sort(newer_reporter)
        return authors
            
    @classmethod
    def get_reporters(cls, time = None, sort = None):
        query = cls._query(cls.c._name == '0', eager_load = False,
                           data = False, thing_data = False)
        if time:
            query._filter(time)
        query._sort = desc("_date")

        account_dict = {}
        min_report_time = {}
        for r in query:
            account_dict[r._thing1_id] = account_dict.get(r._thing1_id, 0) + 1
            if min_report_time.get(r._thing1_id):
                min_report_time[r._thing1_id] = min(min_report_time[r._thing1_id], r._date)
            else:
                min_report_time[r._thing1_id] = r._date
            
        # grab users in chunks of 50
        c_size = 50
        accounts = account_dict.keys()
        accounts = [Account._byID(accounts[i:i+c_size], return_dict = False, data = True)
                    for i in xrange(0, len(accounts), c_size)]
        accts = []
        for a in accounts:
            accts.extend(a)

        if sort == "hot" or sort == "top":
            def report_hotness(a):
                return a.report_correct / max(a.report_ignored + a.report_correct,1)
            def better_reporter(a, b):
                q = report_hotness(b) - report_hotness(a)
                if q == 0:
                    return b.report_correct - a.report_correct
                else:
                    return 1 if q > 0 else -1
            accts.sort(better_reporter)
        elif sort == "new":
            def newer_reporter(a, b):
                t = (min_report_time[b._id] - min_report_time[a._id])
                t0 = datetime.timedelta(0)
                return 1 if t > t0 else -1 if t < t0 else 0
            accts.sort(newer_reporter)
            
        return accts


# def karma_whack(author, cls, dir):
#     try:
#         field = 'comment_karma' if cls == Comment else 'link_karma'
#         # get karma scale (ignore negative) -> user karma times 10%
#         karma = max(getattr(author, field) * .1, 1)
        
#         # set the scale by the number of times this guy has been marked as a spammer
#         scale = max(author.spammer+1, 1)
        
#         # the actual hit is the min of the two
#         hit = min(karma, scale) * ( 1 if dir > 0 else -1 )
        
#         author._incr(field, int(hit))
#     except AttributeError:
#         pass
    

def unreport(things, correct=False, auto = False, banned_by = ''):
    things = tup(things)

    # load authors (to set the spammer flag)
    try:
        aids = set(t.author_id for t in things)
    except AttributeError:
        aids = None

    authors = Account._byID(tuple(aids), data=True) if aids else {}


    # load all reports (to set their amount to be +/-1)
    reports = Report.reported(things=things, amount = 0)

    # mark the reports as finalized:
    for r in reports.values(): Report.accept(r, correct)

    amount = 1 if correct else -1

    spammer = {}
    for t in things:
        # clean up inconsistencies
        if getattr(t, Report._field) != 0:
            setattr(t, Report._field, 0)
            t._commit()
            # flag search indexer that something has changed
            tc.changed(t)
            
        # update the spam flag
        if t._spam != correct and hasattr(t, 'author_id'):
            # tally the spamminess of the author
            spammer[t.author_id] = spammer.get(t.author_id,0) + amount
            #author = authors.get(t.author_id)
            #if author:
            #    karma_whack(author, t.__class__, -amount)

    #will be empty if the items didn't have authors
    for s, v in spammer.iteritems():
        if authors[s].spammer + v >= 0:
            authors[s]._incr('spammer', v)
            
    # mark all as spam
    admintools.spam(things, amount = amount, auto = auto, banned_by = banned_by)

def unreport_account(user, correct = True, types = (Link, Comment, Message),
                     auto = False, banned_by = ''):
    for typ in types:
        thing_dict = tdb.types_id[typ._type_id]
        dtable, table = thing_dict.data_table
        
        by_user_query = sa.and_(table.c.thing_id == dtable.c.thing_id,
                                dtable.c.key == 'author_id',
                                sa.func.substring(dtable.c.value, 1, 1000) == user._id)

        s = sa.select(["count(*)"],
                      sa.and_(by_user_query, table.c.spam == (not correct)))

        # update the author's spamminess
        count = s.execute().fetchone()[0] * (1 if correct else -1)

        if user.spammer + count >= 0:
            user._incr('spammer', count)
            
        #for i in xrange(count if count > 0 else -count):
        #    karma_whack(user, typ, -count)

        things= list(typ._query(typ.c.author_id == user._id,
                                typ.c._spam == (not correct),
                                data = False, limit=300))
        admintools.spam(things, amount = 1 if correct else -1,
                        mark_as_spam = False,
                        auto = auto, banned_by = banned_by)
        

        u = """UPDATE %(table)s SET spam='%(spam)s' FROM %(dtable)s
        WHERE %(table)s.thing_id = %(dtable)s.thing_id
        AND %(dtable)s.key = 'author_id'
        AND substring(%(dtable)s.value, 1, 1000) = %(author_id)s"""
        u = u % dict(spam = 't' if correct else 'f',
                     table = table.name,
                     dtable = dtable.name,
                     author_id = user._id)
        table.engine.execute(u)
        
        # grab a list of all the things we just blew away and update the cache
        s = sa.select([table.c.thing_id], by_user_query)
        tids = [t[0] for t in s.execute().fetchall()]
        keys = [thing_prefix(typ.__name__, i) for i in tids]
        cache.delete_multi(keys)

                           
    # mark the reports as finalized:
    reports = Report._by_author(user, amount = 0)
    for r in reports: Report.accept(r, correct)
    
def whack(user, correct = True, auto = False, ban_user = False, banned_by = ''):
    unreport_account(user, correct = correct,
                     auto = auto, banned_by = banned_by)
    if ban_user:
        user._spam = True
        user._commit()
