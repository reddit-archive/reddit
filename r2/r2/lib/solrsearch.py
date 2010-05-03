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
    Module for communication reddit-level communication with
    Solr. Contains functions for indexing (`reindex_all`, `run_changed`)
    and searching (`search_things`). Uses pysolr (placed in r2.lib)
    for lower-level communication with Solr
"""

from __future__ import with_statement

from Queue import Queue
from threading import Thread
import time
from datetime import datetime, date
from time import strftime

from pylons import g, config

from r2.models import *
from r2.lib.contrib import pysolr
from r2.lib.contrib.pysolr import SolrError
from r2.lib.utils import timeago
from r2.lib.utils import unicode_safe, tup
from r2.lib.cache import SelfEmptyingCache
from r2.lib import amqp

## Changes to the list of searchable languages will require changes to
## Solr's configuration (specifically, the fields that are searched)
searchable_langs    = set(['dk','nl','en','fi','fr','de','it','no','nn','pt',
                           'ru','es','sv','zh','ja','ko','cs','el','th'])

## Adding types is a matter of adding the class to indexed_types here,
## adding the fields from that type to search_fields below, and adding
## those fields to Solr's configuration
indexed_types = (Subreddit, Link)


class Field(object):
    """
       Describes a field of a Thing that is searchable by Solr. Used
       by `search_fields` below
    """
    def __init__(self, name, thing_attr_func = None, store = True,
                 tokenize=False, is_number=False, reverse=False,
                 is_date = False):
        self.name = name
        self.thing_attr_func = self.make_extractor(thing_attr_func)

    def make_extractor(self,thing_attr_func):
        if not thing_attr_func:
            return self.make_extractor(self.name)
        elif isinstance(thing_attr_func,str):
            return (lambda x: getattr(x,thing_attr_func))
        else:
            return thing_attr_func

    def extract_from(self,thing):
        return self.thing_attr_func(thing)

class ThingField(Field):
    """
        ThingField('field_name',Author,'author_id','name')
        is like:
          Field(name, lambda x: Author._byID(x.author_id,data=True).name)
        but faster because lookups are done in batch
    """
    def __init__(self,name,cls,id_attr,lu_attr_name):
        self.name = name

        self.cls          = cls          # the class of the looked-up object
        self.id_attr      = id_attr      # the attr of the source obj used to find the dest obj
        self.lu_attr_name = lu_attr_name # the attr of the dest class that we want to return

    def __str__(self):
        return ("<ThingField: (%s,%s,%s,%s)>"
                % (self.name,self.cls,self.id_attr,self.lu_attr_name))

def domain_permutations(s):
    """
      Takes a domain like `www.reddit.com`, and returns a list of ways
      that a user might search for it, like:
      * www
      * reddit
      * com
      * www.reddit.com
      * reddit.com
      * com
    """
    ret = []
    r = s.split('.')

    for x in xrange(len(r)):
        ret.append('.'.join(r[x:len(r)]))
    for x in r:
        ret.append(x)

    return set(ret)

# Describes the fields of Thing objects and subclasses that are passed
# to Solr for indexing. All must have a 'contents' field, since that
# will be used for language-agnostic searching, and will be copied
# into contents_en, contents_eo, et (see `tokenize_things` for a
# discussion of multi-language search. The 'boost' field is a
# solr-magic field that ends up being an attribute on the <doc>
# message (rather than a field), and is used to do an index-time boost
# (this magic is done in pysolr.dor_to_elemtree)
search_fields={Thing:     (Field('fullname', '_fullname'),
                           Field('date', '_date',   is_date = True, reverse=True),
                           Field('lang'),
                           Field('ups',   '_ups',   is_number=True, reverse=True),
                           Field('downs', '_downs', is_number=True, reverse=True),
                           Field('spam','_spam'),
                           Field('deleted','_deleted'),
                           Field('hot', lambda t: t._hot*1000, is_number=True, reverse=True),
                           Field('controversy', '_controversy', is_number=True, reverse=True),
                           Field('points', lambda t: (t._ups - t._downs), is_number=True, reverse=True)),
               Subreddit: (Field('contents',
                                 lambda s: ' '.join([unicode_safe(s.name),
                                                     unicode_safe(s.title),
                                                     unicode_safe(s.description),
                                                     unicode_safe(s.firsttext)]),
                                 tokenize = True),
                           Field('boost', '_downs'),
                           #Field('title'),
                           #Field('firsttext'),
                           #Field('description'),
                           #Field('over_18'),
                           #Field('sr_type','type'),
                           ),
               Link:      (Field('contents','title', tokenize = True),
                           Field('boost', lambda t: int(t._hot*1000),
                                 # yes, it's a copy of 'hot'
                                 is_number=True, reverse=True),
                           Field('author_id'),
                           ThingField('author',Account,'author_id','name'),
                           ThingField('subreddit',Subreddit,'sr_id','name'),
                           #ThingField('reddit',Subreddit,'sr_id','name'),
                           Field('sr_id'),
                           Field('url', tokenize = True),
                           #Field('domain',
                           #      lambda l: domain_permutations(domain(l.url))),
                           Field('site',
                                 lambda l: domain_permutations(domain(l.url))),
                           #Field('is_self','is_self'),
                           ),
               Comment:   (Field('contents', 'body', tokenize = True),
                           Field('boost', lambda t: int(t._hot*1000),
                                 # yes, it's a copy of 'hot'
                                 is_number=True, reverse=True),
                           ThingField('author',Account,'author_id','name'),
                           ThingField('subreddit',Subreddit,'sr_id','name'))}
                           #ThingField('reddit',Subreddit,'sr_id','name'))}

def tokenize_things(things,return_dict=False):
    """
        Here, we take a list of things, and return a list of
        dictionaries of fields, which will be sent to Solr. We take
        the `search_fields` dictionary above, and look for all classes
        for which each Thing is an instance (that is, a Comment will
        pick up fields for Thing as well as Comment), and extract the
        given fields. All tokenised Things are expected to have a
        'contents' attribute. That field is then copied to
        contents_XX, where XX is your two-letter language code, which
        becomes your default search field. Those language-specific
        fields are also set up with the proper language-stemming and
        tokenisers on Solr's end (in config/schema.xml), which allows
        for language-specific searching
    """
    global search_fields

    batched_classes = {}
    ret = {}
    for thing in things:
        try:
            t = {'type': []}
            for cls in ((thing.__class__,) + thing.__class__.__bases__):
                t['type'].append(cls.__name__.lower())
                
                if cls in search_fields:
                    for field in search_fields[cls]:
                        if field.__class__ == Field:
                            try:
                                val = field.extract_from(thing)
                                if val != None and val != '':
                                    t[field.name] = val
                            except AttributeError,e:
                                print e

                        elif field.__class__ == ThingField:
                            if not field.cls in batched_classes:
                                batched_classes[field.cls] = []
                            batched_classes[field.cls].append((thing,field))

            # copy 'contents' to ('contents_%s' % lang) and contents_ws
            t[lang_to_fieldname(thing.lang)] = t['contents']
            t['contents_ws'] = t['contents']

            ret[thing._fullname] = t
        except AttributeError,e:
            print e
        except KeyError,e:
            print e

    # batched_classes should now be a {cls: [(Thing,ThingField)]}.
    # This ugliness is to make it possible to batch Thing lookups, as
    # they were accounting for most of the indexing time
    for cls in batched_classes:
        ids = set()
        for (thing,field) in batched_classes[cls]:
            # extract the IDs
            try:
                id = getattr(thing,field.id_attr)
                ids.add(id)
            except AttributeError,e:
                print e
        found_batch = cls._byID(ids,data=True,return_dict=True)

        for (thing,field) in batched_classes[cls]:
            try:
                id = getattr(thing,field.id_attr)
                ret[thing._fullname][field.name] = (
                    getattr(found_batch[id],field.lu_attr_name))
            except AttributeError,e:
                print e
            except KeyError,e:
                print e

    return ret if return_dict else ret.values()

def lang_to_fieldname(l):
    """
        Returns the field-name for the given language, or `contents`
        if it isn't found
    """
    global searchable_langs

    code = l[:2]

    if code in searchable_langs:
        return ("contents_%s" % code)
    else:
        return "contents"

def tokenize(thing):
    return tokenize_things([thing])

def index_things(s=None,things=[]):
    "Sends the given Things to Solr to be indexed"
    tokenized = tokenize_things(things)

    if s:
        s.add(tokenized)
    else:
        with SolrConnection(commit=True) as s:
            s.add(tokenize_things(things))

def fetch_batches(t_class,size,since,until):
    """
        Convenience function to fetch all Things of class t_class with
        _date from `since` to `until`, returning them in batches of
        `size`. TODO: move to lib/utils, and merge to be the backend
        of `fetch_things`
    """
    q=t_class._query(t_class.c._date >= since,
                     t_class.c._spam == (True,False),
                     t_class.c._deleted == (True,False),
                     t_class.c._date <  until,
                     sort  = desc('_date'),
                     limit = size,
                     data  = True)
    orig_rules = deepcopy(q._rules)

    things = list(q)
    while things:
        yield things

        q._rules = deepcopy(orig_rules)
        q._after(things[len(things)-1])
        things = list(q)

solr_queue=Queue()
for i in range(20):
    solr_queue.put(pysolr.Solr(g.solr_url))
class SolrConnection(object):
    """
        Represents a connection to Solr, properly limited to N
        concurrent connections. Used like

            with SolrConnection() as s:
                s.add(things)
    """
    def __init__(self,commit=False,optimize=False):
        self.commit   = commit
        self.optimize = optimize
    def __enter__(self):
        self.conn = solr_queue.get()
        return self.conn
    def __exit__(self, _type, _value, _tb):
        if self.commit:
            self.conn.commit()
        if self.optimize:
            self.conn.optimize()
        solr_queue.task_done()
        solr_queue.put(self.conn)

def indexer_worker(q,delete_all_first=False):
    """
        The thread for mass-indexing that connects to Solr and submits
        tokenised objects
    """
    with SolrConnection(commit=True,optimize=True) as s:
        count = 0

        if delete_all_first:
            s.delete(q='*:*')

        t = q.get()
        while t != "done":
            # if it's not a list or a dictionary, I don't know how to
            # handle it, so die. It's probably an exception pushed in
            # by the handler in my parent
            if not (isinstance(t,list) and isinstance(t[0],dict)):
                raise t
            count += len(t)
            s.add(t)
            if count > 25000:
                print "Committing... (q:%d)" % (q.qsize(),)
                s.commit()
                count = 0
            q.task_done()

            t=q.get()
        q.task_done()

def reindex_all(types = None, delete_all_first=False):
    """
        Called from `paster run` to totally re-index everything in the
        database. Spawns a thread to connect to Solr, and sends it
        tokenised Things
    """
    global indexed_types

    start_t = datetime.now()

    if not types:
        types = indexed_types

    # We don't want the default thread-local cache (which is just a
    # dict) to grow un-bounded (normally, we'd use
    # utils.set_emptying_cache, except that that preserves memcached,
    # and we don't even want to get memcached for total indexing,
    # because it would dump out more recent stuff)
    g.cache.caches = (SelfEmptyingCache(),) # + g.cache.caches[1:]

    count = 0
    q=Queue(100)
    indexer=Thread(target=indexer_worker,
                   args=(q,delete_all_first))
    indexer.start()

    try:
        for cls in types:
            for batch in fetch_batches(cls,1000,
                                       timeago("50 years"),
                                       start_t):
                r = tokenize_things([ x for x in batch
                                      if not x._spam and not x._deleted ])

                count += len(r)
                print ("Processing %s #%d(%s): %s"
                       % (cls.__name__, count, q.qsize(), r[0]['contents']))

                if indexer.isAlive():
                    q.put(r)
                else:
                    raise Exception("'tis a shame that I have but one thread to give")
        q.put("done")
        indexer.join()

    except object,e:
        if indexer.isAlive():
            q.put(e,timeout=30)
        raise e
    except KeyboardInterrupt,e: # turns out KeyboardInterrupts aren't objects. Who knew?
        if indexer.isAlive():
            q.put(e,timeout=30)
        raise e


def combine_searchterms(terms):
    """
        Convenience function to take a list like
            [ sr_id:1, sr_id:2 sr_id:3 subreddit:reddit.com ]
        and turn it into
            sr_id:(1 2 3) OR subreddit:reddit.com
    """
    combined = {}

    for (name,val) in terms:
        combined[name] = combined.get(name,[]) + [val]

    ret = []

    for (name,vals) in combined.iteritems():
        if len(vals) == 1:
            ret.append("%s:%s" % (name,vals[0]))
        else:
            ret.append("%s:(%s)" % (name," ".join(vals)))

    if len(ret) > 1:
        ret = "(%s)" % " OR ".join(ret)
    else:
        ret = " ".join(ret)

    return ret

def swap_strings(s,this,that):
    """
        Just swaps substrings, like:
            s = "hot asc"
            s = swap_strings(s,'asc','desc')
            s == "hot desc"

         uses 'tmp' as a replacment string, so don't use for anything
         very complicated
    """
    return s.replace(this,'tmp').replace(that,this).replace('tmp',that)

class SearchQuery(object):
    def __init__(self, q, sort, fields = [], subreddits = [], authors = [], 
                 types = [], timerange = None, spam = False, deleted = False):

        self.q = q
        self.fields = fields
        self.sort = sort
        self.subreddits = subreddits
        self.authors = authors
        self.types = types
        self.spam = spam
        self.deleted = deleted

        if timerange in ['hour','week','day','month','year']:
            self.timerange = (timeago("1 %s" % timerange),"NOW")
        elif timerange == 'all' or timerange is None:
            self.timerange = None
        else:
            self.timerange = timerange

    def __repr__(self):
        attrs = [ "***q=%s***" % self.q ]

        if self.subreddits is not None:
            attrs.append("srs=" + '+'.join([ "%d" % s
                                             for s in self.subreddits ]))

        if self.authors is not None:
            attrs.append("authors=" + '+'.join([ "%d" % s
                                                 for s in self.authors ]))

        if self.timerange is not None:
            attrs.append("timerange=%s" % str(self.timerange))

        if self.sort is not None:
            attrs.append("sort=%r" % self.sort)

        return "<%s(%s)>" % (self.__class__.__name__, ", ".join(attrs))

    def run(self, after = None, num = 100, reverse = False):
        if not self.q:
            return pysolr.Results([],0)

        if not g.solr_url:
            raise SolrError("g.solr_url is not set")

        # there are two parts to our query: what the user typed
        # (parsed with Solr's DisMax parser), and what we are adding
        # to it. The latter is called the "boost" (and is parsed using
        # full Lucene syntax), and it can be added to via the `boost`
        # parameter
        boost = []

        if not self.spam:
            boost.append("-spam:true")
        if not self.deleted:
            boost.append("-deleted:true")

        if self.timerange:
            def time_to_searchstr(t):
                if isinstance(t, datetime):
                    t = t.strftime('%Y-%m-%dT%H:%M:%S.000Z')
                elif isinstance(t, date):
                    t = t.strftime('%Y-%m-%dT00:00:00.000Z')
                elif isinstance(t,str):
                    t = t
                return t

            (fromtime, totime) = self.timerange
            fromtime = time_to_searchstr(fromtime)
            totime   = time_to_searchstr(totime)
            boost.append("+date:[%s TO %s]"
                         % (fromtime,totime))

        if self.subreddits:
            def subreddit_to_searchstr(sr):
                if isinstance(sr,Subreddit):
                    return ('sr_id','%d' % sr.id)
                elif isinstance(sr,str) or isinstance(sr,unicode):
                    return ('subreddit',sr)
                else:
                    return ('sr_id','%d' % sr)

            s_subreddits = map(subreddit_to_searchstr, tup(self.subreddits))

            boost.append("+(%s)" % combine_searchterms(s_subreddits))

        if self.authors:
            def author_to_searchstr(a):
                if isinstance(a,Account):
                    return ('author_id','%d' % a.id)
                elif isinstance(a,str) or isinstance(a,unicode):
                    return ('author',a)
                else:
                    return ('author_id','%d' % a)

            s_authors = map(author_to_searchstr,tup(self.authors))

            boost.append('+(%s)^2' % combine_searchterms(s_authors))


        def type_to_searchstr(t):
            if isinstance(t,str):
                return ('type',t)
            else:
                return ('type',t.__name__.lower())
         
        s_types = map(type_to_searchstr,self.types)
        boost.append("+%s" % combine_searchterms(s_types))

        q,solr_params = self.solr_params(self.q,boost)

        search = self.run_search(q, self.sort, solr_params,
                                 reverse, after, num)
        return search

    @classmethod
    def run_search(cls, q, sort, solr_params, reverse, after, num):
        "returns pysolr.Results(docs=[fullname()],hits=int())"

        if reverse:
            sort = swap_strings(sort,'asc','desc')

        if after:
            # size of the pre-search to run in the case that we need
            # to search more than once. A bigger one can reduce the
            # number of searches that need to be run twice, but if
            # it's bigger than the default display size, it could
            # waste some
            PRESEARCH_SIZE = num

            # run a search and get back the number of hits, so that we
            # can re-run the search with that max_count.
            pre_search = cls.run_search_cached(q, sort, 0, PRESEARCH_SIZE,
                                               solr_params)

            if (PRESEARCH_SIZE >= pre_search.hits
                or pre_search.hits == len(pre_search.docs)):
                # don't run a second search if our pre-search found
                # all of the elements anyway
                search = pre_search
            else:
                # now that we know how many to request, we can request
                # the whole lot
                search = cls.run_search_cached(q, sort, 0,
                                               pre_search.hits,
                                               solr_params, max=True)

            search.docs = get_after(search.docs, after._fullname, num)
        else:
            search = cls.run_search_cached(q, sort, 0, num, solr_params)

        return search

    @staticmethod
    def run_search_cached(q, sort, start, rows, other_params, max=False):
        "Run the search, first trying the best available cache"

        # first, try to see if we've cached the result for the entire
        # dataset for that query, returning the requested slice of it
        # if so. If that's not available, try the cache for the
        # partial result requested (passing the actual search along to
        # solr if both of those fail)
        full_key = 'solrsearch_%s' % ','.join(('%r' % r)
                                              for r in (q,sort,other_params))
        part_key = "%s,%d,%d" % (full_key, start, rows)

        full_cached = g.cache.get(full_key)
        if full_cached:
            res = pysolr.Results(hits = full_cached.hits,
                                 docs = full_cached.docs[start:start+rows])
        else:
            part_cached = g.cache.get(part_key)
            if part_cached:
                res = part_cached
            else:
                with SolrConnection() as s:
                    g.log.debug(("Searching q = %r; sort = %r,"
                                 + " start = %r, rows = %r,"
                                 + " params = %r, max = %r")
                                % (q,sort,start,rows,other_params,max))

                    res = s.search(q, sort, start = start, rows = rows,
                                   other_params = other_params)

                g.cache.set(full_key if max else part_key,
                            res, time = g.solr_cache_time)

        # extract out the fullname in the 'docs' field, since that's
        # all we care about
        res = pysolr.Results(docs = [ i['fullname'] for i in res.docs ],
                             hits = res.hits)

        return res

    def solr_params(self,*k,**kw):
        raise NotImplementedError

class UserSearchQuery(SearchQuery):
    "Base class for queries that use the dismax parser"
    def __init__(self, q, mm, sort=None, fields=[], langs=None, **kw):
        default_fields = ['contents^1.5','contents_ws^3'] + fields

        if langs is None:
            fields = default_fields
        else:
            if langs == 'all':
                langs = searchable_langs
            fields = set([("%s^2" % lang_to_fieldname(lang)) for lang in langs]
                         + default_fields)

        # minimum match. See http://lucene.apache.org/solr/api/org/apache/solr/util/doc-files/min-should-match.html
        self.mm = mm

        SearchQuery.__init__(self, q, sort, fields = fields, **kw)

    def solr_params(self, q, boost):
        return q, dict(fl = 'fullname',
                       qt = 'dismax',
                       bq = ' '.join(boost),
                       qf = ' '.join(self.fields),
                       mm = self.mm)

class LinkSearchQuery(UserSearchQuery):
    def __init__(self, q, mm = None, **kw):
        additional_fields = ['site^1','author^1', 'subreddit^1', 'url^1']

        if mm is None:
            mm = '4<75%'

        UserSearchQuery.__init__(self, q, mm = mm, fields = additional_fields,
                                 types=[Link], **kw)

class RelatedSearchQuery(LinkSearchQuery):
    def __init__(self, q, ignore = [], **kw):
        self.ignore = set(ignore) if ignore else set()

        LinkSearchQuery.__init__(self, q, mm = '3<100% 5<60% 8<50%', **kw)

    def run(self, *k, **kw):
        search = LinkSearchQuery.run(self, *k, **kw)
        search.docs = [ x for x in search.docs if x not in self.ignore ]
        return search

class SubredditSearchQuery(UserSearchQuery):
    def __init__(self, q, **kw):
        # note that 'downs' is a measure of activity on subreddits
        UserSearchQuery.__init__(self, q, mm = '75%', sort = 'downs desc',
                                 types=[Subreddit], **kw)

class DomainSearchQuery(SearchQuery):
    def __init__(self, domain, **kw):
        q = '+site:%s' % domain

        SearchQuery.__init__(self, q = q, fields=['site'],types=[Link], **kw)

    def solr_params(self, q, boost):
        q = q + ' ' + ' '.join(boost)
        return q, dict(fl='fullname',
                       qt='standard')

def get_after(fullnames, fullname, num):
    for i, item in enumerate(fullnames):
        if item == fullname:
            return fullnames[i+1:i+num+1]
    else:
        return fullnames[:num]


def run_commit(optimize=False):
    with SolrConnection(commit=True, optimize=optimize) as s:
        pass


def run_changed(drain=False):
    """
        Run by `cron` (through `paster run`) on a schedule to update
        all Things that have been created or have changed since the
        last run. Note: unlike many queue-using functions, this one is
        run from cron and totally drains the queue before terminating
    """
    def _run_changed(msgs, chan):
        print "changed: Processing %d items" % len(msgs)

        fullnames = set([x.body for x in msgs])
        things = Thing._by_fullname(fullnames, data=True, return_dict=False)
        things = [x for x in things if isinstance(x, indexed_types)]

        update_things = [x for x in things if not x._spam and not x._deleted]
        delete_things = [x for x in things if x._spam or x._deleted]

        with SolrConnection() as s:
            if update_things:
                tokenized = tokenize_things(update_things)
                s.add(tokenized)
            if delete_things:
                for i in delete_things:
                    s.delete(id=i._fullname)

    amqp.handle_items('searchchanges_q', _run_changed, limit=1000,
                      drain=drain)
