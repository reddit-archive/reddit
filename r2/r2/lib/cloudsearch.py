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
# All portions of the code written by reddit are Copyright (c) 2006-2012 reddit
# Inc. All Rights Reserved.
###############################################################################

import cPickle as pickle
from datetime import datetime
import functools
import httplib
import json
from lxml import etree
from pylons import g, c
import re
import time
import urllib

import l2cs

from r2.lib import amqp, filters
from r2.lib.db.operators import desc
import r2.lib.utils as r2utils
from r2.models import (Account, Link, Subreddit, Thing, All, DefaultSR,
                       MultiReddit, DomainSR, Friends, ModContribSR,
                       FakeSubreddit, NotFound)


_CHUNK_SIZE = 4000000 # Approx. 4 MB, to stay under the 5MB limit
_VERSION_OFFSET = 13257906857
ILLEGAL_XML = re.compile(u'[\x00-\x08\x0b\x0c\x0e-\x1F\uD800-\uDFFF\uFFFE\uFFFF]')


def _safe_xml_str(s, use_encoding="utf-8"):
    '''Replace invalid-in-XML unicode control characters with '\uFFFD'.
    Also, coerces result to unicode
    
    '''
    if not isinstance(s, unicode):
        if isinstance(s, str):
            s = unicode(s, use_encoding, errors="replace")
        else:
            # ints will raise TypeError if the "errors" kwarg
            # is passed, but since it's not a str no problem
            s = unicode(s)
    s = ILLEGAL_XML.sub(u"\uFFFD", s)
    return s


def safe_get(get_fn, ids, return_dict=True, **kw):
    items = {}
    for i in ids:
        try:
            item = get_fn(i, **kw)
        except NotFound:
            g.log.info("%r failed for %r", get_fn, i)
        else:
            items[i] = item
    if return_dict:
        return items
    else:
        return items.values()


class CloudSearchHTTPError(httplib.HTTPException): pass
class InvalidQuery(Exception): pass


class CloudSearchUploader(object):
    use_safe_get = False
    types = ()
    
    def __init__(self, doc_api, things=None, version_offset=_VERSION_OFFSET):
        self.doc_api = doc_api
        self._version_offset = version_offset
        self.things = self.desired_things(things) if things else []
    
    @classmethod
    def desired_fullnames(cls, items):
        '''Pull fullnames that represent instances of 'types' out of items'''
        fullnames = set()
        type_ids = [type_._type_id for type_ in cls.types]
        for item in items:
            item_type = r2utils.decompose_fullname(item['fullname'])[1]
            if item_type in type_ids:
                fullnames.add(item['fullname'])
        return fullnames
    
    @classmethod
    def desired_things(cls, things):
        return [t for t in things if isinstance(t, cls.types)]
    
    def _version_tenths(self):
        '''Cloudsearch documents don't update unless the sent "version" field
        is higher than the one currently indexed. As our documents don't have
        "versions" and could in theory be updated multiple times in one second,
        for now, use "tenths of a second since 12:00:00.00 1/1/2012" as the
        "version" - this will last approximately 13 years until bumping up against
        the version max of 2^32 for cloudsearch docs'''
        return int(time.time() * 10) - self._version_offset
    
    def _version_seconds(self):
        return int(time.time()) - int(self._version_offset / 10)
    
    _version = _version_tenths
    
    def add_xml(self, thing, version):
        add = etree.Element("add", id=thing._fullname, version=str(version),
                            lang="en")
        
        for field_name, value in self.fields(thing).iteritems():
            field = etree.SubElement(add, "field", name=field_name)
            field.text = _safe_xml_str(value)
        
        return add
    
    def delete_xml(self, thing, version=None):
        '''Return the cloudsearch XML representation of
        "delete this from the index"
        
        '''
        version = str(version or self._version())
        delete = etree.Element("delete", id=thing._fullname, version=version)
        return delete
    
    def delete_ids(self, ids):
        '''Delete documents from the index.
        'ids' should be a list of fullnames
        
        '''
        version = self._version()
        deletes = [etree.Element("delete", id=id_, version=str(version))
                   for id_ in ids]
        batch = etree.Element("batch")
        batch.extend(deletes)
        return self.send_documents(batch)
    
    def xml_from_things(self):
        '''Generate a <batch> XML tree to send to cloudsearch for
        adding/updating/deleting the given things
        
        '''
        batch = etree.Element("batch")
        self.batch_lookups()
        version = self._version()
        for thing in self.things:
            try:
                if thing._spam or thing._deleted:
                    delete_node = self.delete_xml(thing, version)
                    batch.append(delete_node)
                elif self.should_index(thing):
                    add_node = self.add_xml(thing, version)
                    batch.append(add_node)
            except (AttributeError, KeyError):
                # AttributeError may occur if a needed attribute is somehow
                # missing from the DB
                # KeyError will occur for whichever items (if any) triggered
                #     the safe_get() call above, because the needed (but
                #     invalid) Account or Subreddit is missing from the srs or
                #     accounts dictionary
                # In either case, the sanest approach is to simply not index
                # the item. If it gets voted on later (or otherwise sent back
                # to the queue), perhaps it will have been fixed.
                pass
        return batch
    
    def should_index(self, thing):
        raise NotImplementedError
    
    def batch_lookups(self):
        pass
    
    def fields(self, thing):
        raise NotImplementedError
    
    def inject(self, quiet=False):
        '''Send things to cloudsearch. Return value is time elapsed, in seconds,
        of the communication with the cloudsearch endpoint
        
        '''
        xml_things = self.xml_from_things()
        
        cs_start = datetime.now(g.tz)
        if len(xml_things):
            sent = self.send_documents(xml_things)
            if not quiet:
                print sent
        return (datetime.now(g.tz) - cs_start).total_seconds()
    
    def send_documents(self, docs):
        '''Open a connection to the cloudsearch endpoint, and send the documents
        for indexing. Multiple requests are sent if a large number of documents
        are being sent (see chunk_xml())
        
        Raises CloudSearchHTTPError if the endpoint indicates a failure
        '''
        responses = []
        connection = httplib.HTTPConnection(self.doc_api, 80)
        chunker = chunk_xml(docs)
        try:
            for data in chunker:
                headers = {}
                headers['Content-Type'] = 'application/xml'
                # HTTPLib calculates Content-Length header automatically
                connection.request('POST', "/2011-02-01/documents/batch",
                                   data, headers)
                response = connection.getresponse()
                if 200 <= response.status < 300:
                    responses.append(response.read())
                else:
                    raise CloudSearchHTTPError(response.status,
                                               response.reason,
                                               response.read())
        finally:
            connection.close()
        return responses


class LinkUploader(CloudSearchUploader):
    types = (Link,)
    
    def __init__(self, doc_api, things=None, version_offset=_VERSION_OFFSET):
        super(LinkUploader, self).__init__(doc_api, things, version_offset)
        self.accounts = {}
        self.srs = {}
    
    def fields(self, thing):
        '''Return fields relevant to a Link search index'''
        account = self.accounts[thing.author_id]
        sr = self.srs[thing.sr_id]
        nsfw = sr.over_18 or thing.over_18 or Link._nsfw.findall(thing.title)
        
        fields = {"ups": max(0, thing._ups),
                  "downs": max(0, thing._downs),
                  "num_comments": max(0, getattr(thing, 'num_comments', 0)),
                  "fullname": thing._fullname,
                  "subreddit": sr.name,
                  "reddit": sr.name,
                  "title": thing.title,
                  "timestamp": int(time.mktime(thing._date.utctimetuple())),
                  "sr_id": thing.sr_id,
                  "over18": 1 if nsfw else 0,
                  "is_self": 1 if thing.is_self else 0,
                  "author_fullname": account._fullname,
                  "type_id": thing._type_id
                  }
        
        if account._deleted:
            fields['author'] = '[deleted]'
        else:
            fields['author'] = account.name
    
        if thing.is_self:
            fields['site'] = g.domain
            if thing.selftext:
                fields['selftext'] = thing.selftext
        else:
            fields['url'] = thing.url
            try:
                url = r2utils.UrlParser(thing.url)
                fields['site'] = list(url.domain_permutations())
            except ValueError:
                # UrlParser couldn't handle thing.url, oh well
                pass
        
        if thing.flair_css_class or thing.flair_text:
            fields['flair_css_class'] = thing.flair_css_class or ''
            fields['flair_text'] = thing.flair_text or ''
        
        return fields
    
    def batch_lookups(self):
        author_ids = [thing.author_id for thing in self.things
                      if hasattr(thing, 'author_id')]
        try:
            self.accounts = Account._byID(author_ids, data=True,
                                          return_dict=True)
        except NotFound:
            if self.use_safe_get:
                self.accounts = safe_get(Account._byID, author_ids, data=True,
                                         return_dict=True)
            else:
                raise
    
        sr_ids = [thing.sr_id for thing in self.things
                  if hasattr(thing, 'sr_id')]
        try:
            self.srs = Subreddit._byID(sr_ids, data=True, return_dict=True)
        except NotFound:
            if self.use_safe_get:
                self.srs = safe_get(Subreddit._byID, sr_ids, data=True,
                                    return_dict=True)
            else:
                raise
    
    def should_index(self, thing):
        return (thing.promoted is None and getattr(thing, "sr_id", None) != -1)


class SubredditUploader(CloudSearchUploader):
    types = (Subreddit,)
    _version = CloudSearchUploader._version_seconds
    
    def fields(self, thing):
        fields = {'name': thing.name,
                  'title': thing.title,
                  'type': thing.type,
                  'language': thing.lang,
                  'header_title': thing.header_title,
                  'description': thing.public_description,
                  'sidebar': thing.description,
                  'over18': thing.over_18,
                  'link_type': thing.link_type,
                  'activity': thing._downs,
                  'subscribers': thing._ups,
                  'type_id': thing._type_id
                  }
        return fields
    
    def should_index(self, thing):
        return getattr(thing, 'author_id', None) != -1


def chunk_xml(xml, depth=0):
    '''Chunk POST data into pieces that are smaller than the 20 MB limit.
    
    Ideally, this never happens (if chunking is necessary, would be better
    to avoid xml'ifying before testing content_length)'''
    data = etree.tostring(xml)
    content_length = len(data)
    if content_length < _CHUNK_SIZE:
        yield data
    else:
        depth += 1
        print "WARNING: Chunking (depth=%s)" % depth
        half = len(xml) / 2
        left_half = xml # for ease of reading
        right_half = etree.Element("batch")
        # etree magic simultaneously removes the elements from one tree
        # when they are appended to a different tree
        right_half.append(xml[half:])
        for chunk in chunk_xml(left_half, depth=depth):
            yield chunk
        for chunk in chunk_xml(right_half, depth=depth):
            yield chunk


def _run_changed(msgs, chan):
    '''Consume the cloudsearch_changes queue, and print reporting information
    on how long it took and how many remain
    
    '''
    start = datetime.now(g.tz)
    
    changed = [pickle.loads(msg.body) for msg in msgs]
    
    fullnames = set()
    fullnames.update(LinkUploader.desired_fullnames(changed))
    fullnames.update(SubredditUploader.desired_fullnames(changed))
    things = Thing._by_fullname(fullnames, data=True, return_dict=False)
    
    link_uploader = LinkUploader(g.CLOUDSEARCH_DOC_API, things=things)
    subreddit_uploader = SubredditUploader(g.CLOUDSEARCH_SUBREDDIT_DOC_API,
                                           things=things)
    
    link_time = link_uploader.inject()
    subreddit_time = subreddit_uploader.inject()
    cloudsearch_time = link_time + subreddit_time
    
    totaltime = (datetime.now(g.tz) - start).total_seconds()
    
    print ("%s: %d messages in %.2fs seconds (%.2fs secs waiting on "
           "cloudsearch); %d duplicates, %s remaining)" %
           (start, len(changed), totaltime, cloudsearch_time,
            len(changed) - len(things),
            msgs[-1].delivery_info.get('message_count', 'unknown')))


def run_changed(drain=False, min_size=500, limit=1000, sleep_time=10,
                use_safe_get=False, verbose=False):
    '''Run by `cron` (through `paster run`) on a schedule to send Things to
        Amazon CloudSearch
    
    '''
    if use_safe_get:
        CloudSearchUploader.use_safe_get = True
    amqp.handle_items('cloudsearch_changes', _run_changed, min_size=min_size,
                      limit=limit, drain=drain, sleep_time=sleep_time,
                      verbose=verbose)


def _progress_key(item):
    return "%s/%s" % (item._id, item._date)


_REBUILD_INDEX_CACHE_KEY = "cloudsearch_cursor_%s"


def rebuild_link_index(start_at=None, sleeptime=1, cls=Link,
                       uploader=LinkUploader, doc_api='CLOUDSEARCH_DOC_API',
                       estimate=50000000, chunk_size=1000):
    cache_key = _REBUILD_INDEX_CACHE_KEY % uploader.__name__.lower()
    doc_api = getattr(g, doc_api)
    uploader = uploader(doc_api)
    
    if start_at is _REBUILD_INDEX_CACHE_KEY:
        start_at = g.cache.get(cache_key)
        if not start_at:
            raise ValueError("Told me to use '%s' key, but it's not set" %
                             cache_key)
    
    q = cls._query(cls.c._deleted == (True, False),
                   sort=desc('_date'), data=True)
    if start_at:
        after = cls._by_fullname(start_at)
        assert isinstance(after, cls)
        q._after(after)
    q = r2utils.fetch_things2(q, chunk_size=chunk_size)
    q = r2utils.progress(q, verbosity=1000, estimate=estimate, persec=True,
                         key=_progress_key)
    for chunk in r2utils.in_chunks(q, size=chunk_size):
        uploader.things = chunk
        for x in range(5):
            try:
                uploader.inject()
            except httplib.HTTPException as err:
                print "Got %s, sleeping %s secs" % (err, x)
                time.sleep(x)
                continue
            else:
                break
        else:
            raise err
        last_update = chunk[-1]
        g.cache.set(cache_key, last_update._fullname)
        time.sleep(sleeptime)


rebuild_subreddit_index = functools.partial(rebuild_link_index,
                                            cls=Subreddit,
                                            uploader=SubredditUploader,
                                            doc_api='CLOUDSEARCH_SUBREDDIT_DOC_API',
                                            estimate=200000,
                                            chunk_size=1000)


def test_run_link(start_link, count=1000):
    '''Inject `count` number of links, starting with `start_link`'''
    if isinstance(start_link, basestring):
        start_link = int(start_link, 36)
    links = Link._byID(range(start_link - count, start_link), data=True,
                       return_dict=False)
    uploader = LinkUploader(g.CLOUDSEARCH_DOC_API, things=links)
    return uploader.inject()


def test_run_srs(*sr_names):
    '''Inject Subreddits by name into the index'''
    srs = Subreddit._by_name(sr_names).values()
    uploader = SubredditUploader(g.CLOUDSEARCH_SUBREDDIT_DOC_API, things=srs)
    return uploader.inject()


### Query Code ###
class Results(object):
    def __init__(self, docs, hits, facets):
        self.docs = docs
        self.hits = hits
        self._facets = facets
        self._subreddits = []
    
    def __repr__(self):
        return '%s(%r, %r, %r)' % (self.__class__.__name__,
                                   self.docs,
                                   self.hits,
                                   self._facets)
    
    @property
    def subreddit_facets(self):
        '''Filter out subreddits that the user isn't allowed to see'''
        if not self._subreddits and 'reddit' in self._facets:
            sr_facets = [(sr['value'], sr['count']) for sr in
                         self._facets['reddit']]

            # look up subreddits
            srs_by_name = Subreddit._by_name([name for name, count
                                              in sr_facets])

            sr_facets = [(srs_by_name[name], count) for name, count
                         in sr_facets if name in srs_by_name]

            # filter by can_view
            self._subreddits = [(sr, count) for sr, count in sr_facets
                                if sr.can_view(c.user)]

        return self._subreddits


_SEARCH = "/2011-02-01/search?"
INVALID_QUERY_CODES = ('CS-UnknownFieldInMatchExpression',
                       'CS-IncorrectFieldTypeInMatchExpression',
                       'CS-InvalidMatchSetExpression',)
DEFAULT_FACETS = {"reddit": {"count":20}}
def basic_query(query=None, bq=None, faceting=None, size=1000,
                start=0, rank="-relevance", return_fields=None, record_stats=False,
                search_api=None):
    if search_api is None:
        search_api = g.CLOUDSEARCH_SEARCH_API
    if faceting is None:
        faceting = DEFAULT_FACETS
    path = _encode_query(query, bq, faceting, size, start, rank, return_fields)
    timer = None
    if record_stats:
        timer = g.stats.get_timer("cloudsearch_timer")
        timer.start()
    connection = httplib.HTTPConnection(search_api, 80)
    try:
        connection.request('GET', path)
        resp = connection.getresponse()
        response = resp.read()
        if record_stats:
            g.stats.action_count("event.search_query", resp.status)
        if resp.status >= 300:
            try:
                reasons = json.loads(response)
            except ValueError:
                pass
            else:
                messages = reasons.get("messages", [])
                for message in messages:
                    if message['code'] in INVALID_QUERY_CODES:
                        raise InvalidQuery(resp.status, resp.reason, message,
                                           path, reasons)
            raise CloudSearchHTTPError(resp.status, resp.reason, path,
                                       response)
    finally:
        connection.close()
        if timer is not None:
            timer.stop()
    
    return json.loads(response)


basic_link = functools.partial(basic_query, size=10, start=0,
                               rank="-relevance",
                               return_fields=['title', 'reddit',
                                              'author_fullname'],
                               record_stats=False,
                               search_api=g.CLOUDSEARCH_SEARCH_API)


basic_subreddit = functools.partial(basic_query,
                                    faceting=None,
                                    size=10, start=0,
                                    rank="-activity",
                                    return_fields=['title', 'reddit',
                                                   'author_fullname'],
                                    record_stats=False,
                                    search_api=g.CLOUDSEARCH_SUBREDDIT_SEARCH_API)


def _encode_query(query, bq, faceting, size, start, rank, return_fields):
    if not (query or bq):
        raise ValueError("Need query or bq")
    params = {}
    if bq:
        params["bq"] = bq
    else:
        params["q"] = query
    params["results-type"] = "json"
    params["size"] = size
    params["start"] = start
    params["rank"] = rank
    if faceting:
        params["facet"] = ",".join(faceting.iterkeys())
        for facet, options in faceting.iteritems():
            params["facet-%s-top-n" % facet] = options.get("count", 20)
            if "sort" in options:
                params["facet-%s-sort" % facet] = options["sort"]
    if return_fields:
        params["return-fields"] = ",".join(return_fields)
    encoded_query = urllib.urlencode(params)
    path = _SEARCH + encoded_query
    return path


class CloudSearchQuery(object):
    '''Represents a search query sent to cloudsearch'''
    search_api = None
    sorts = {}
    sorts_menu_mapping = {}
    known_syntaxes = ("cloudsearch", "lucene", "plain")
    default_syntax = "plain"
    lucene_parser = None
    
    def __init__(self, query, sr=None, sort=None, syntax=None, raw_sort=None,
                 faceting=None):
        if syntax is None:
            syntax = self.default_syntax
        elif syntax not in self.known_syntaxes:
            raise ValueError("Unknown search syntax: %s" % syntax)
        self.query = filters._force_unicode(query or u'')
        self.converted_data = None
        self.syntax = syntax
        self.sr = sr
        self._sort = sort
        if raw_sort:
            self.sort = raw_sort
        else:
            self.sort = self.sorts[sort]
        self.faceting = faceting
        self.bq = u''
        self.results = None
    
    def run(self, after=None, reverse=False, num=1000, _update=False):
        if not self.query:
            return Results([], 0, {})
        
        results = self._run(_update=_update)
        
        docs, hits, facets = results.docs, results.hits, results._facets
        
        after_docs = r2utils.get_after(docs, after, num, reverse=reverse)
        
        self.results = Results(after_docs, hits, facets)
        return self.results
    
    def _run(self, start=0, num=1000, _update=False):
        '''Run the search against self.query'''
        q = None
        if self.syntax == "cloudsearch":
            self.bq = self.customize_query(self.query)
        elif self.syntax == "lucene":
            bq = l2cs.convert(self.query, self.lucene_parser)
            self.converted_data = {"syntax": "cloudsearch",
                                   "converted": bq}
            self.bq = self.customize_query(bq)
        elif self.syntax == "plain":
            q = self.query.encode('utf-8')
        if g.sqlprinting:
            g.log.info("%s", self)
        return self._run_cached(q, self.bq.encode('utf-8'), self.sort,
                                self.faceting, start=start, num=num,
                                _update=_update)
    
    def customize_query(self, bq):
        return bq
    
    def __repr__(self):
        '''Return a string representation of this query'''
        result = ["<", self.__class__.__name__, "> query:",
                  repr(self.query), " "]
        if self.bq:
            result.append(" bq:")
            result.append(repr(self.bq))
            result.append(" ")
        result.append("sort:")
        result.append(self.sort)
        return ''.join(result)
    
    @classmethod
    def _run_cached(cls, query, bq, sort="relevance", faceting=None, start=0,
                    num=1000, _update=False):
        '''Query the cloudsearch API. _update parameter allows for supposed
        easy memoization at later date.
        
        Example result set:
        
        {u'facets': {u'reddit': {u'constraints':
                                    [{u'count': 114, u'value': u'politics'},
                                    {u'count': 42, u'value': u'atheism'},
                                    {u'count': 27, u'value': u'wtf'},
                                    {u'count': 19, u'value': u'gaming'},
                                    {u'count': 12, u'value': u'bestof'},
                                    {u'count': 12, u'value': u'tf2'},
                                    {u'count': 11, u'value': u'AdviceAnimals'},
                                    {u'count': 9, u'value': u'todayilearned'},
                                    {u'count': 9, u'value': u'pics'},
                                    {u'count': 9, u'value': u'funny'}]}},
         u'hits': {u'found': 399,
                   u'hit': [{u'id': u't3_11111'},
                            {u'id': u't3_22222'},
                            {u'id': u't3_33333'},
                            {u'id': u't3_44444'},
                            ...
                            ],
                   u'start': 0},
         u'info': {u'cpu-time-ms': 10,
                   u'messages': [{u'code': u'CS-InvalidFieldOrRankAliasInRankParameter',
                                  u'message': u"Unable to create score object for rank '-hot'",
                                  u'severity': u'warning'}],
                   u'rid': u'<hash>',
                   u'time-ms': 9},
                   u'match-expr': u"(label 'my query')",
                   u'rank': u'-text_relevance'}
        
        '''
        response = basic_query(query=query, bq=bq, size=num, start=start,
                               rank=sort, search_api=cls.search_api,
                               faceting=faceting, record_stats=True)
        
        warnings = response['info'].get('messages', [])
        for warning in warnings:
            g.log.warn("%(code)s (%(severity)s): %(message)s" % warning)
        
        hits = response['hits']['found']
        docs = [doc['id'] for doc in response['hits']['hit']]
        facets = response.get('facets', {})
        for facet in facets.keys():
            values = facets[facet]['constraints']
            facets[facet] = values
        
        results = Results(docs, hits, facets)
        return results


class LinkSearchQuery(CloudSearchQuery):
    search_api = g.CLOUDSEARCH_SEARCH_API
    sorts = {'relevance': '-relevance',
             'hot': '-hot2',
             'top': '-top',
             'new': '-timestamp',
             'comments': '-num_comments',
             }
    sorts_menu_mapping = {'relevance': 1,
                          'hot': 2,
                          'new': 3,
                          'top': 4,
                          'comments': 5,
                          }
    
    lucene_parser = l2cs.make_parser(int_fields=['timestamp'],
                                     yesno_fields=['over18', 'is_self',
                                                   'nsfw', 'self'])
    known_syntaxes = ("cloudsearch", "lucene", "plain")
    default_syntax = "lucene"
    
    def customize_query(self, bq):
        subreddit_query = self._get_sr_restriction(self.sr)
        return self.create_boolean_query(bq, subreddit_query)
    
    @classmethod
    def create_boolean_query(cls, query, subreddit_query):
        '''Join a (user-entered) text query with the generated subreddit query
        
        Input:
            base_query: user input from the search textbox
            subreddit_query: output from _get_sr_restriction(sr)
        
        Test cases:
            base_query: simple, simple with quotes, boolean, boolean w/ parens
            subreddit_query: None, in parens '(or sr_id:1 sr_id:2 ...)',
                             without parens "author:'foo'"
        
        '''
        if subreddit_query:
            bq = "(and %s %s)" % (query, subreddit_query)
        else:
            bq = query
        return bq
    
    @staticmethod
    def _get_sr_restriction(sr):
        '''Return a cloudsearch appropriate query string that restricts
        results to only contain results from self.sr
        
        '''
        bq = []
        if (not sr) or sr == All or isinstance(sr, DefaultSR):
            return None
        elif isinstance(sr, MultiReddit):
            bq = ["(or"]
            for sr_id in sr.sr_ids:
                bq.append("sr_id:%s" % sr_id)
            bq.append(")")
        elif isinstance(sr, DomainSR):
            bq = ["site:'%s'" % sr.domain]
        elif sr == Friends:
            if not c.user_is_loggedin or not c.user.friends:
                return None
            bq = ["(or"]
            # The query limit is roughly 8k bytes. Limit to 200 friends to
            # avoid getting too close to that limit
            friend_ids = c.user.friends[:200]
            friends = ["author_fullname:'%s'" %
                       Account._fullname_from_id36(r2utils.to36(id_))
                       for id_ in friend_ids]
            bq.extend(friends)
            bq.append(")")
        elif isinstance(sr, ModContribSR):
            bq = ["(or"]
            for sr_id in sr.sr_ids:
                bq.append("sr_id:%s" % sr_id)
            bq.append(")")
        elif not isinstance(sr, FakeSubreddit):
            bq = ["sr_id:%s" % sr._id]
        
        return ' '.join(bq)


class SubredditSearchQuery(CloudSearchQuery):
    search_api = g.CLOUDSEARCH_SUBREDDIT_SEARCH_API
    sorts = {'relevance': '-activity',
             None: '-activity',
             }
    sorts_menu_mapping = {'relevance': 1,
                          }
    
    known_syntaxes = ("plain",)
    default_syntax = "plain"
