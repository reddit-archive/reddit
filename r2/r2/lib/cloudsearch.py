import cPickle as pickle
from datetime import datetime
import httplib
import json
from lxml import etree
from pylons import g, c
import random
import re
import time
import urllib

from r2.lib import amqp
from r2.lib.db.operators import desc
import r2.lib.utils as r2utils
from r2.models import Account, Link, Subreddit, Thing, \
    All, DefaultSR, MultiReddit, DomainSR, Friends, ModContribSR, \
    FakeSubreddit, NotFound


_CHUNK_SIZE = 4000000 # Approx. 4 MB, to stay under the 5MB limit
_VERSION_OFFSET = 13257906857
ILLEGAL_XML = re.compile(u'[\x00-\x08\x0b\x0c\x0e-\x1F\uD800-\uDFFF\uFFFE\uFFFF]')
USE_SAFE_GET = False


def _safe_xml_str(s, use_encoding="utf-8"):
    '''Replace invalid-in-XML unicode control characters with '?'.
    Also, coerces 's' to unicode
    
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


class CloudSearchHTTPError(httplib.HTTPException): pass
class InvalidQuery(Exception): pass


def _version():
    '''Cloudsearch documents don't update unless the sent "version" field
    is higher than the one currently indexed. As our documents don't have
    "versions" and could in theory be updated multiple times in one second,
    for now, use "tenths of a second since 12:00:00.00 1/1/2012" as the
    "version" - this will last approximately 13 years until bumping up against
    the version max of 2^32 for cloudsearch docs'''
    return int(time.time() * 10) - _VERSION_OFFSET


### Document Upload ###

def add_xml(thing, version, srs, accounts):
    '''Return an etree XML representation of the thing, suitable for
    sending to cloudsearch
    
    '''
    add = etree.Element("add", id=thing._fullname, version=str(version),
                        lang="en")
    
    account = accounts[thing.author_id]
    sr = srs[thing.sr_id]
    nsfw = sr.over_18 or thing.over_18 or Link._nsfw.findall(thing.title)
    
    fields = {"ups": max(0, thing._ups),
              "downs": max(0, thing._downs),
              "num_comments": max(0, getattr(thing, 'num_comments', 0)),
              "fullname": thing._fullname,
              "subreddit": sr.name,
              "reddit": sr.name,
              "title": thing.title,
              "timestamp": thing._date.strftime("%s"),
              "sr_id": thing.sr_id,
              "over18": 1 if nsfw else 0,
              "is_self": 1 if thing.is_self else 0,
              "author_fullname": account._fullname,
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
            fields['site'] = ' '.join(r2utils.UrlParser(thing.url).domain_permutations())
        except ValueError:
            # UrlParser couldn't handle thing.url, oh well
            pass
    
    for field_name, value in fields.iteritems():
        field = etree.SubElement(add, "field", name=field_name)
        field.text = _safe_xml_str(value)
    
    return add


def delete_xml(thing, version):
    '''Return the cloudsearch XML representation of
    "delete this from the index"
    
    '''
    delete = etree.Element("delete", id=thing._fullname, version=str(version))
    return delete


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


def xml_from_things(things):
    '''Generate a <batch> XML tree to send to cloudsearch for
    adding/updating/deleting the given things
    
    '''
    batch = etree.Element("batch")
    
    author_ids = [thing.author_id for thing in things
                  if hasattr(thing, 'author_id')]
    try:
        accounts = Account._byID(author_ids, data=True, return_dict=True)
    except NotFound:
        if USE_SAFE_GET:
            accounts = safe_get(Account._byID, author_ids, data=True,
                                return_dict=True)
        else:
            raise

    sr_ids = [thing.sr_id for thing in things if hasattr(thing, 'sr_id')]
    try:
        srs = Subreddit._byID(sr_ids, data=True, return_dict=True)
    except NotFound:
        if USE_SAFE_GET:
            srs = safe_get(Subreddit._byID, sr_ids, data=True, return_dict=True)
        else:
            raise
    
    version = _version()
    for thing in things:
        try:
            if thing._spam or thing._deleted:
                delete_node = delete_xml(thing, version)
                batch.append(delete_node)
            elif thing.promoted is None and getattr(thing, "sr_id", None) != -1:
                add_node = add_xml(thing, version, srs, accounts)
                batch.append(add_node)
        except (AttributeError, KeyError):
            # AttributeError may occur if a needed attribute is somehow missing
            #     from the DB
            # KeyError will occur for whichever items (if any) triggered the
            #     safe_get() call above, because the needed (but invalid)
            #     Account or Subreddit is missing from the srs or accounts
            #     dictionary
            # In either case, the sanest approach is to simply not index the
            # item. If it gets voted on later (or otherwise sent back to the
            # queue), perhaps it will have been fixed.
            pass
    return batch


def delete_ids(ids):
    '''Delete documents from the index. 'ids' should be a list of fullnames'''
    version = _version()
    deletes = [etree.Element("delete", id=id_, version=str(version)) for id_ in ids]
    batch = etree.Element("batch")
    batch.extend(deletes)
    return send_documents(batch)


def inject(things):
    '''Send things to cloudsearch. Return value is time elapsed, in seconds,
    of the communication with the cloudsearch endpoint
    
    '''
    xml_things = xml_from_things(things)
    
    cs_start = datetime.now(g.tz)
    if len(xml_things):
        print send_documents(xml_things)
    return (datetime.now(g.tz) - cs_start).total_seconds()


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
        # etree magic simultaneously removes the elements from the other tree
        right_half.append(xml[half:])
        for chunk in chunk_xml(left_half, depth=depth):
            yield chunk
        for chunk in chunk_xml(right_half, depth=depth):
            yield chunk


def send_documents(docs):
    '''Open a connection to the cloudsearch endpoint, and send the documents
    for indexing. Multiple requests are sent if a large number of documents
    are being sent (see chunk_xml())
    
    Raises CloudSearchHTTPError if the endpoint indicates a failure
    '''
    responses = []
    connection = httplib.HTTPConnection(g.CLOUDSEARCH_DOC_API, 80)
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
                raise CloudSearchHTTPError(response.status, response.reason,
                                           response.read())
    finally:
        connection.close()
    return responses


def _desired_things(items, types):
    '''Pull fullnames that represent instances of 'types' out of items'''
    # This will fail if the _type_id for some things is >36
    fullnames = set()
    type_ids = [r2utils.to36(type_._type_id) for type_ in types]
    for item in items:
        if item['fullname'][1] in type_ids:
            fullnames.add(item['fullname'])
    return fullnames


def _run_changed(msgs, chan):
    '''Consume the cloudsearch_changes queue, and print reporting information
    on how long it took and how many remain
    
    '''
    start = datetime.now(g.tz)
    
    changed = [pickle.loads(msg.body) for msg in msgs]
    
    # Only handle links to start with
    
    fullnames = _desired_things(changed, (Link,))
    things = Thing._by_fullname(fullnames, data=True, return_dict=False)
    
    cloudsearch_time = inject(things)
    
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
        global USE_SAFE_GET
        USE_SAFE_GET = True
    amqp.handle_items('cloudsearch_changes', _run_changed, min_size=min_size,
                      limit=limit, drain=drain, sleep_time=sleep_time,
                      verbose=verbose)


def _progress_key(item):
    return "%s/%s" % (item._id, item._date)


_REBUILD_INDEX_CACHE_KEY = "cloudsearch_cursor"


def rebuild_index(start_at=None, sleeptime=1, cls=Link, estimate=50000000,
                  chunk_size=1000):
    if start_at is _REBUILD_INDEX_CACHE_KEY:
        start_at = g.cache.get(start_at)
        if not start_at:
            raise ValueError("Told me to use '%s' key, but it's not set" %
                             _REBUILD_INDEX_CACHE_KEY)
    
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
        for x in range(5):
            try:
                inject(chunk)
            except httplib.HTTPException as err:
                print "Got  %s, sleeping %s secs" % (err, x)
                time.sleep(x)
                continue
            else:
                break
        else:
            raise err
        last_update = chunk[-1]
        g.cache.set(_REBUILD_INDEX_CACHE_KEY, last_update._fullname)
        time.sleep(sleeptime)


def test_run(start_link, count=1000):
    '''Inject `count` number of links, starting with `start_link`'''
    if isinstance(start_link, basestring):
        start_link = int(start_link, 36)
    links = Link._byID(range(start_link - count, start_link), data=True,
                       return_dict=False)
    return inject(links)


### Query Code ###
class Results(object):
    __slots__ = ["docs", "hits", "facets"]
    
    def __init__(self, docs, hits, facets):
        self.docs = docs
        self.hits = hits
        self.facets = facets
    
    def __repr__(self):
        return '%s(%r, %r, %r)' % (self.__class__.__name__,
                                   self.docs,
                                   self.hits,
                                   self.facets)


def _to_fn(cls, id_):
    '''Convert id_ to a fullname (equivalent to "link._fullname", but doesn't
    require an instance of the class)
    
    '''
    return (cls._type_prefix + r2utils.to36(cls._type_id) + '_' + 
            r2utils.to36(id_))


_SEARCH = "/2011-02-01/search?"
INVALID_QUERY_CODES = ('CS-UnknownFieldInMatchExpression',
                       'CS-InvalidMatchSetExpression',
                       'CS-IncorrectFieldTypeInMatchExpression')
def basic_query(query=None, bq=None, facets=("reddit",), facet_count=10,
                size=1000, start=0, rank="hot", return_fields=None,
                record_stats=False):
    path = _encode_query(query, bq, facets, facet_count, size, start, rank,
                         return_fields)
    timer = None
    if record_stats:
        timer = g.stats.get_timer("cloudsearch_timer")
        timer.start()
    connection = httplib.HTTPConnection(g.CLOUDSEARCH_SEARCH_API, 80)
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
        if timer:
            timer.stop()

    
    return json.loads(response)


def _encode_query(query, bq, facets, facet_count, size, start, rank,
                  return_fields):
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
    if facets:
        params["facet"] = ",".join(facets)
        for facet in facets:
            params["facet-%s-top-n" % facet] = facet_count
    if return_fields:
        params["return-fields"] = ",".join(return_fields)
    encoded_query = urllib.urlencode(params)
    path = _SEARCH + encoded_query
    return path


class CloudSearchQuery(object):
    '''Represents a search query sent to cloudsearch'''
    sorts = {'relevance': '-relevance',
             'top': '-top',
             'new': '-timestamp',
             }
    sorts_menu_mapping = {'relevance': 1,
                          'new': 2,
                          'top': 3,
                          }
    
    def __init__(self, query, sr, sort):
        self.query = query.encode("utf-8") if query else ''
        self.sr = sr
        self._sort = sort
        self.sort = self.sorts[sort]
        self.bq = ''
        self.results = None
    
    def run(self, after=None, reverse=False, num=1000, _update=False):
        if not self.query:
            return Results([], 0, {})
        
        results = self._run(_update=_update)
        
        docs, hits, facets = results.docs, results.hits, results.facets
        
        after_docs = r2utils.get_after(docs, after, num, reverse=reverse)
        
        self.results = Results(after_docs, hits, facets)
        return self.results
    
    @staticmethod
    def create_boolean_query(base_query, subreddit_query):
        '''Join a (user-entered) text query with the generated subreddit query
        
        Input:
            base_query: user input from the search textbox
            subreddit_query: output from _get_sr_restriction(sr)
        
        Test cases:
            base_query: simple, simple with quotes, boolean, boolean w/ parens
            subreddit_query: None, in parens '(or sr_id:1 sr_id:2 ...)',
                             without parens "author:'foo'"
        
        '''
        is_boolean_query = any([x in base_query for x in ":()"])
        
        query = base_query.strip()
        if not is_boolean_query:
            query = query.replace("\\", "")
            query = query.replace("'", "\\'")
            query = "(field text '%s')" % query
        
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
            friends = ["author_fullname:'%s'" % _to_fn(Account, id_) for id_ in friend_ids]
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
    
    def _run(self, start=0, num=1000, _update=False):
        '''Run the search against self.query'''
        subreddit_query = self._get_sr_restriction(self.sr)
        self.bq = self.create_boolean_query(self.query, subreddit_query)
        if g.sqlprinting:
            g.log.info("%s", self)
        return self._run_cached(self.bq, self.sort, start=start, num=num,
                                _update=_update)
    
    def __repr__(self):
        '''Return a string representation of this query'''
        result = ["<", self.__class__.__name__, "> query:", repr(self.query), " "]
        if self.bq:
            result.append(" bq:")
            result.append(repr(self.bq))
            result.append(" ")
        result.append("sort:")
        result.append(self.sort)
        return ''.join(result)
    
    @classmethod
    def _run_cached(cls, bq, sort="hot", start=0, num=1000, _update=False):
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
        response = basic_query(bq=bq, size=num, start=start, rank=sort,
                               record_stats=True)
        
        warnings = response['info'].get('messages', [])
        for warning in warnings:
            g.log.warn("%(code)s (%(severity)s): %(message)s" % warning)
        
        hits = response['hits']['found']
        docs = [doc['id'] for doc in response['hits']['hit']]
        facets = response['facets']
        for facet in facets.keys():
            values = facets[facet]['constraints']
            facets[facet] = values
        
        results = Results(docs, hits, facets)
        return results


def test_create_boolean_query():
    tests = [('steve holt', None),
             ('steve holt', '(or sr_id:1 sr_id:2 sr_id:3)'),
             ('steve holt', "author:'qgyh2'"),
             ("can't help myself", None),
             ("can't help myself", '(or sr_id:1 sr_id:2 sr_id:3)'),
             ("can't help myself", "author:'qgyh2'"),
             ("text:'steve holt'", None),
             ("text:'steve holt'", '(or sr_id:1 sr_id:2 sr_id:3)'),
             ("text:'steve holt'", "author:'qgyh2'"),
             ("(or text:'steve holt' text:'nintendo')", None),
             ("(or text:'steve holt' text:'nintendo')", '(or sr_id:1 sr_id:2 sr_id:3)'),
             ("(or text:'steve holt' text:'nintendo')", "author:'qgyh2'")]
    for test in tests:
        print "Trying: %r" % (test,)
        bq = CloudSearchQuery.create_boolean_query(*test)
        print "Query: %r" % bq
        basic_query(bq=bq, size=1)
