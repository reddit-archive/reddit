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
"""
    Module for communication reddit-level communication with
    Solr. Contains functions for indexing (`reindex_all`, `changed`)
    and searching (`search_things`). Uses pysolr (placed in r2.lib)
    for lower-level communication with Solr
"""

from __future__ import with_statement

from r2.models import *
from r2.models import thing_changes
from r2.lib.contrib import pysolr
from r2.lib.contrib.pysolr import SolrError
from r2.lib.utils import timeago, set_emptying_cache, IteratorChunker
from r2.lib.utils import psave, pload, unicode_safe
from r2.lib.cache import SelfEmptyingCache
from Queue import Queue
from threading import Thread
import time
from datetime import datetime, date
from time import strftime
from pylons import g,config

## Changes to the list of searchable languages will require changes to
## Solr's configuration (specifically, the fields that are searched)
searchable_langs    = set(['dk','nl','en','fi','fr','de','it','no','nn','pt',
                           'ru','es','sv','zh','ja','ko','cs','el','th'])

## Adding types is a matter of adding the class to indexed_types here,
## adding the fields from that type to search_fields below, and adding
## those fields to Solr's configuration
indexed_types       = (Subreddit, Link)

## Where to store the timestamp for the last time we ran. Used by
## `save_last_run` and `get_last_run`, which are used by `changed`
root                = config.current_conf()['pylons.paths'].get('root')
last_run_fname      = '%s/../data/solrsearch_changes.pickle' % root

class Field(object):
    """
       Describes a field of a Thing that is searchable by Solr. Used
       by `search_fields` below"
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
                           Field('hot', lambda t: int(t._hot*1000),
                                 is_number=True, reverse=True),
                           Field('points', lambda t: str(t._ups - t._downs),
                                 is_number=True, reverse=True)),
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
                           #ThingField('subreddit',Subreddit,'sr_id','name'),
                           ThingField('reddit',Subreddit,'sr_id','name'))}

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
                r = tokenize_things(batch)

                count += len(r)
                print ("Processing %s #%d(%s): %s"
                       % (cls.__name__, count, q.qsize(), r[0]['contents']))

                if indexer.isAlive():
                    q.put(r)
                else:
                    raise Exception("'tis a shame that I have but one thread to give")
        q.put("done")
        indexer.join()

        save_last_run(start_t)
    except object,e:
        if indexer.isAlive():
            q.put(e,timeout=30)
        raise e
    except KeyboardInterrupt,e: # turns out KeyboardInterrupts aren't objects. Who knew?
        if indexer.isAlive():
            q.put(e,timeout=30)
        raise e

def save_last_run(last_run=None):
    if not last_run:
        last_run=datetime.now()
    psave(last_run_fname,last_run)
def get_last_run():
    return pload(last_run_fname)
def changed(types=None,since=None,commit=True,optimize=False):
    """
        Run by `cron` (through `paster run`) on a schedule to update
        all Things that have been created or have changed since the
        last run. Things add themselves to a `thing_changes` table,
        which we read, find the Things, tokenise, and re-submit them
        to Solr
    """
    global indexed_types

    set_emptying_cache()

    start_t = datetime.now()

    if not types:
        types = indexed_types
    if not since:
        since = get_last_run()

    all_changed = []

    with SolrConnection(commit=commit,optimize=optimize) as s:
        for cls in types:
            changed = (x[0]
                       for x
                       in thing_changes.get_changed(cls,min_date = since))
            changed = IteratorChunker(changed)

            while not changed.done:
                chunk = changed.next_chunk(200)

                # chunk =:= [(Fullname,Date) | ...]
                chunk = cls._by_fullname(chunk,
                                         data=True, return_dict=False)
                chunk = [x for x in chunk if not x._spam and not x._deleted]

                # note: anything marked as spam or deleted is not
                # updated in the search database. Since these are
                # filtered out in the UI, that's probably fine.
                if len(chunk) > 0:
                    chunk  = tokenize_things(chunk)
                    s.add(chunk)

    save_last_run(start_t)

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
            s = "sort(asc)"
            swap_strings(s,'asc','desc')
            s -> "sort desc"

         uses 'tmp' as a replacment string, so don't use for anything
         very complicated
    """
    return s.replace(this,'tmp').replace(that,this).replace('tmp',that)

def search_things(q, sort = 'hot desc',
                  after = None,
                  subreddits = None,
                  authors = None,
                  num = 100, reverse = False,
                  timerange = None, langs = None,
                  types = None,
                  boost = []):
    """
        Takes a given query and returns a list of Things that match
        that query. See Builder for the use of `after`, `reverse`, and
        `num`. Queries on params are OR queries, except `timerange`
        and `types`
    """
    global searchable_langs
    global indexed_types

    if not q or not g.solr_url:
        return pysolr.Results([],0)

    # there are two parts to our query: what the user typed (parsed
    # with Solr's DisMax parser), and what we are adding to it. The
    # latter is called the "boost" (and is parsed using full Lucene
    # syntax), and it can be added to via the `boost` parameter (which
    # we have to copy since we append to it)
    boost = list(boost)

    # `score` refers to Solr's score (relevency to the search given),
    # not our score (sums of ups and downs).
    sort = "score desc, %s, date desc, fullname asc" % (sort,)
    if reverse:
        sort = swap_strings(sort,'asc','desc')

    if timerange:
        def time_to_searchstr(t):
            if isinstance(t, datetime):
                t = t.strftime('%Y-%m-%dT%H:%M:%S.000Z')
            elif isinstance(t, date):
                t = t.strftime('%Y-%m-%dT00:00:00.000Z')
            elif isinstance(t,str):
                t = t
            return t

        (fromtime, totime) = timerange
        fromtime = time_to_searchstr(fromtime)
        totime   = time_to_searchstr(totime)
        boost.append("+date:[%s TO %s]"
                     % (fromtime,totime))

    if subreddits:
        def subreddit_to_searchstr(sr):
            if isinstance(sr,Subreddit):
                return ('sr_id','%d' % sr.id)
            elif isinstance(sr,str) or isinstance(sr,unicode):
                return ('reddit',sr)
            else:
                return ('sr_id','%d' % sr)

        if isinstance(subreddits,list) or isinstance(subreddits,tuple):
            s_subreddits = map(subreddit_to_searchstr, subreddits)
        else:
            s_subreddits = (subreddit_to_searchstr(subreddits),)

        boost.append("(%s)^2" % combine_searchterms(s_subreddits))

    if authors:
        def author_to_searchstr(a):
            if isinstance(a,Account):
                return ('author_id','%d' % a.id)
            elif isinstance(a,str) or isinstance(a,unicode):
                return ('author',a)
            else:
                return ('author_id','%d' % a)

        if isinstance(authors,list) or isinstance(authors,tuple):
            s_authors = map(author_to_searchstr,authors)
        else:
            s_authors = map(author_to_searchstr,(authors,))

        boost.append('(%s)^2' % combine_searchterms(s_authors))

    # the set of languages is used to determine the fields to search,
    # named ('contents_%s' % lang), but 'contents' (which is split
    # only on whitespace) is always also searched. This means that
    # all_langs and schema.xml must be kept in synch
    default_fields = ['contents^1.5','contents_ws^3','site^1','author^1', 'reddit^1', 'url^1']
    if langs == None:
        # only search 'contents'
        fields = default_fields
    else:
        if langs == 'all':
            langs = searchable_langs
        fields = set([("%s^2" % lang_to_fieldname(lang)) for lang in langs]
                     + default_fields)

    if not types:
        types = indexed_types
        
    def type_to_searchstr(t):
         if isinstance(t,str):
            return ('type',t)
         else:
             return ('type',t.__name__.lower())
         
    s_types = map(type_to_searchstr,types)
    boost.append("+%s" % combine_searchterms(s_types))

    # everything else that solr needs to know
    solr_params = dict(fl = 'fullname', # the field(s) to return
                       qt = 'dismax',   # the query-handler (dismax supports 'bq' and 'qf')
                       # qb = '3',
                       bq = ' '.join(boost),
                       qf = ' '.join(fields),
                       mm = '50%')      # minimum number of clauses that should match

    with SolrConnection() as s:
        if after:
            # size of the pre-search to run in the case that we need
            # to search more than once. A bigger one can reduce the
            # number of searches that need to be run twice, but if
            # it's bigger than the default display size, it could
            # waste some
            PRESEARCH_SIZE = num

            # run a search and get back the number of hits, so that we
            # can re-run the search with that max_count.
            pre_search = s.search(q,sort,rows=PRESEARCH_SIZE,
                                  other_params = solr_params)

            if (PRESEARCH_SIZE >= pre_search.hits
                or pre_search.hits == len(pre_search.docs)):
                # don't run a second search if our pre-search found
                # all of the elements anyway
                search = pre_search
            else:
                # we have to run a second search, but we can limit the
                # duplicated transfer of the first few records since
                # we already have those from the pre_search
                second_search = s.search(q,sort,
                                         start=len(pre_search.docs),
                                         rows=pre_search.hits - len(pre_search.docs),
                                         other_params = solr_params)
                search = pysolr.Results(pre_search.docs + second_search.docs,
                                        pre_search.hits)

            fullname = after._fullname
            found_it = False
            for i, item in enumerate(search.docs):
                if item['fullname'] == fullname:
                    found_it = True
                    search.docs = search.docs[i+1:i+1+num]
                    break
            if not found_it:
                search.docs = search.docs[0:num]
        else:
            search = s.search(q,sort,rows=num,
                              other_params = solr_params)

    hits = search.hits
    things = Thing._by_fullname([i['fullname'] for i in search.docs],
                                data = True, return_dict = False)

    return pysolr.Results(things,hits)

