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

import os
import base64
import traceback
import ConfigParser
import codecs

from urllib import unquote_plus
from urllib2 import urlopen, Request
from urlparse import urlparse, urlunparse
import signal
from copy import deepcopy
import cPickle as pickle
import re, math, random
import boto
from decimal import Decimal

from BeautifulSoup import BeautifulSoup, SoupStrainer

from time import sleep
from datetime import date, datetime, timedelta
from pylons import c, g
from pylons.i18n import ungettext, _
from r2.lib.filters import _force_unicode, _force_utf8
from mako.filters import url_escape
from r2.lib.contrib import ipaddress
from r2.lib.require import require, require_split
import snudown

from r2.lib.utils._utils import *

iters = (list, tuple, set)

def randstr(len, reallyrandom = False):
    """If reallyrandom = False, generates a random alphanumeric string
    (base-36 compatible) of length len.  If reallyrandom, add
    uppercase and punctuation (which we'll call 'base-93' for the sake
    of argument) and suitable for use as salt."""
    alphabet = 'abcdefghijklmnopqrstuvwxyz0123456789'
    if reallyrandom:
        alphabet += 'ABCDEFGHIJKLMNOPQRSTUVWXYZ!#$%&\()*+,-./:;<=>?@[\\]^_{|}~'
    return ''.join(random.choice(alphabet)
                   for i in range(len))

class Storage(dict):
    """
    A Storage object is like a dictionary except `obj.foo` can be used
    in addition to `obj['foo']`.

        >>> o = storage(a=1)
        >>> o.a
        1
        >>> o['a']
        1
        >>> o.a = 2
        >>> o['a']
        2
        >>> del o.a
        >>> o.a
        Traceback (most recent call last):
            ...
        AttributeError: 'a'

    """
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError, k:
            raise AttributeError, k

    def __setattr__(self, key, value):
        self[key] = value

    def __delattr__(self, key):
        try:
            del self[key]
        except KeyError, k:
            raise AttributeError, k

    def __repr__(self):
        return '<Storage ' + dict.__repr__(self) + '>'

storage = Storage

def storify(mapping, *requireds, **defaults):
    """
    Creates a `storage` object from dictionary `mapping`, raising `KeyError` if
    d doesn't have all of the keys in `requireds` and using the default
    values for keys found in `defaults`.

    For example, `storify({'a':1, 'c':3}, b=2, c=0)` will return the equivalent of
    `storage({'a':1, 'b':2, 'c':3})`.

    If a `storify` value is a list (e.g. multiple values in a form submission),
    `storify` returns the last element of the list, unless the key appears in
    `defaults` as a list. Thus:

        >>> storify({'a':[1, 2]}).a
        2
        >>> storify({'a':[1, 2]}, a=[]).a
        [1, 2]
        >>> storify({'a':1}, a=[]).a
        [1]
        >>> storify({}, a=[]).a
        []

    Similarly, if the value has a `value` attribute, `storify will return _its_
    value, unless the key appears in `defaults` as a dictionary.

        >>> storify({'a':storage(value=1)}).a
        1
        >>> storify({'a':storage(value=1)}, a={}).a
        <Storage {'value': 1}>
        >>> storify({}, a={}).a
        {}

    """
    def getvalue(x):
        if hasattr(x, 'value'):
            return x.value
        else:
            return x

    stor = Storage()
    for key in requireds + tuple(mapping.keys()):
        value = mapping[key]
        if isinstance(value, list):
            if isinstance(defaults.get(key), list):
                value = [getvalue(x) for x in value]
            else:
                value = value[-1]
        if not isinstance(defaults.get(key), dict):
            value = getvalue(value)
        if isinstance(defaults.get(key), list) and not isinstance(value, list):
            value = [value]
        setattr(stor, key, value)

    for (key, value) in defaults.iteritems():
        result = value
        if hasattr(stor, key):
            result = stor[key]
        if value == () and not isinstance(result, tuple):
            result = (result,)
        setattr(stor, key, result)

    return stor

class Enum(Storage):
    def __init__(self, *a):
        self.name = tuple(a)
        Storage.__init__(self, ((e, i) for i, e in enumerate(a)))
    def __contains__(self, item):
        if isinstance(item, int):
            return item in self.values()
        else:
            return Storage.__contains__(self, item)


class Results():
    def __init__(self, sa_ResultProxy, build_fn, do_batch=False):
        self.rp = sa_ResultProxy
        self.fn = build_fn
        self.do_batch = do_batch

    @property
    def rowcount(self):
        return self.rp.rowcount

    def _fetch(self, res):
        if self.do_batch:
            return self.fn(res)
        else:
            return [self.fn(row) for row in res]

    def fetchall(self):
        return self._fetch(self.rp.fetchall())

    def fetchmany(self, n):
        rows = self._fetch(self.rp.fetchmany(n))
        if rows:
            return rows
        else:
            raise StopIteration

    def fetchone(self):
        row = self.rp.fetchone()
        if row:
            if self.do_batch:
                row = tup(row)
                return self.fn(row)[0]
            else:
                return self.fn(row)
        else:
            raise StopIteration

def strip_www(domain):
    if domain.count('.') >= 2 and domain.startswith("www."):
        return domain[4:]
    else:
        return domain

def is_subdomain(subdomain, base):
    """Check if a domain is equal to or a subdomain of a base domain."""
    return subdomain == base or (subdomain is not None and subdomain.endswith('.' + base))

r_base_url = re.compile("(?i)(?:.+?://)?(?:www[\d]*\.)?([^#]*[^#/])/?")
def base_url(url):
    res = r_base_url.findall(url)
    return (res and res[0]) or url

r_domain = re.compile("(?i)(?:.+?://)?(?:www[\d]*\.)?([^/:#?]*)")
def domain(s):
    """
        Takes a URL and returns the domain part, minus www., if
        present
    """
    res = r_domain.findall(s)
    domain = (res and res[0]) or s
    return domain.lower()

r_path_component = re.compile(".*?/(.*)")
def path_component(s):
    """
        takes a url http://www.foo.com/i/like/cheese and returns
        i/like/cheese
    """
    res = r_path_component.findall(base_url(s))
    return (res and res[0]) or s

def get_title(url):
    """Fetches the contents of url and extracts (and utf-8 encodes)
       the contents of <title>"""
    if not url or not url.startswith(('http://', 'https://')):
        return None

    try:
        req = Request(url)
        if g.useragent:
            req.add_header('User-Agent', g.useragent)
        opener = urlopen(req, timeout=15)

        # determine the encoding of the response
        for param in opener.info().getplist():
            if param.startswith("charset="):
                param_name, sep, charset = param.partition("=")
                codec = codecs.getreader(charset)
                break
        else:
            codec = codecs.getreader("utf-8")

        with codec(opener, "ignore") as reader:
            # Attempt to find the title in the first 1kb
            data = reader.read(1024)
            title = extract_title(data)

            # Title not found in the first kb, try searching an additional 10kb
            if not title:
                data += reader.read(10240)
                title = extract_title(data)

        return title

    except:
        return None

def extract_title(data):
    """Tries to extract the value of the title element from a string of HTML"""
    bs = BeautifulSoup(data, convertEntities=BeautifulSoup.HTML_ENTITIES)
    if not bs:
        return

    title_bs = bs.html.head.title

    if not title_bs or not title_bs.string:
        return

    title = title_bs.string

    # remove end part that's likely to be the site's name
    # looks for last delimiter char between spaces in strings
    # delimiters: |, -, emdash, endash,
    #             left- and right-pointing double angle quotation marks
    reverse_title = title[::-1]
    to_trim = re.search(u'\s[\u00ab\u00bb\u2013\u2014|-]\s',
                        reverse_title,
                        flags=re.UNICODE)

    # only trim if it won't take off over half the title
    if to_trim and to_trim.end() < len(title) / 2:
        title = title[:-(to_trim.end())]

    # get rid of extraneous whitespace in the title
    title = re.sub(r'\s+', ' ', title, flags=re.UNICODE)

    return title.encode('utf-8').strip()

valid_schemes = ('http', 'https', 'ftp', 'mailto')
valid_dns = re.compile('\A[-a-zA-Z0-9]+\Z')
def sanitize_url(url, require_scheme = False):
    """Validates that the url is of the form

    scheme://domain/path/to/content#anchor?cruft

    using the python built-in urlparse.  If the url fails to validate,
    returns None.  If no scheme is provided and 'require_scheme =
    False' is set, the url is returned with scheme 'http', provided it
    otherwise validates"""

    if not url:
        return

    url = url.strip()
    if url.lower() == 'self':
        return url

    try:
        u = urlparse(url)
        # first pass: make sure a scheme has been specified
        if not require_scheme and not u.scheme:
            url = 'http://' + url
            u = urlparse(url)
    except ValueError:
        return

    if u.scheme and u.scheme in valid_schemes:
        # if there is a scheme and no hostname, it is a bad url.
        if not u.hostname:
            return
        if u.username is not None or u.password is not None:
            return
        labels = u.hostname.split('.')
        for label in labels:
            try:
                #if this succeeds, this portion of the dns is almost
                #valid and converted to ascii
                label = label.encode('idna')
            except TypeError:
                print "label sucks: [%r]" % label
                raise
            except UnicodeError:
                return
            else:
                #then if this success, this portion of the dns is really valid
                if not re.match(valid_dns, label):
                    return
        return url

def trunc_string(text, length):
    return text[0:length]+'...' if len(text)>length else text

# Truncate a time to a certain number of minutes
# e.g, trunc_time(5:52, 30) == 5:30
def trunc_time(time, mins, hours=None):
    if hours is not None:
        if hours < 1 or hours > 60:
            raise ValueError("Hours %d is weird" % mins)
        time = time.replace(hour = hours * (time.hour / hours))

    if mins < 1 or mins > 60:
        raise ValueError("Mins %d is weird" % mins)

    return time.replace(minute = mins * (time.minute / mins),
                        second = 0,
                        microsecond = 0)

def long_datetime(datetime):
    return datetime.astimezone(g.tz).ctime() + " " + str(g.tz)

def median(l):
    if l:
        s = sorted(l)
        i = len(s) / 2
        return s[i]

def query_string(dict):
    pairs = []
    for k,v in dict.iteritems():
        if v is not None:
            try:
                k = url_escape(_force_unicode(k))
                v = url_escape(_force_unicode(v))
                pairs.append(k + '=' + v)
            except UnicodeDecodeError:
                continue
    if pairs:
        return '?' + '&'.join(pairs)
    else:
        return ''

class UrlParser(object):
    """
    Wrapper for urlparse and urlunparse for making changes to urls.
    All attributes present on the tuple-like object returned by
    urlparse are present on this class, and are setable, with the
    exception of netloc, which is instead treated via a getter method
    as a concatenation of hostname and port.

    Unlike urlparse, this class allows the query parameters to be
    converted to a dictionary via the query_dict method (and
    correspondingly updated vi update_query).  The extension of the
    path can also be set and queried.

    The class also contains reddit-specific functions for setting,
    checking, and getting a path's subreddit.  It also can convert
    paths between in-frame and out of frame cname'd forms.

    """

    __slots__ = ['scheme', 'path', 'params', 'query',
                 'fragment', 'username', 'password', 'hostname',
                 'port', '_url_updates', '_orig_url', '_query_dict']

    valid_schemes = ('http', 'https', 'ftp', 'mailto')
    cname_get = "cnameframe"

    def __init__(self, url):
        u = urlparse(url)
        for s in self.__slots__:
            if hasattr(u, s):
                setattr(self, s, getattr(u, s))
        self._url_updates = {}
        self._orig_url    = url
        self._query_dict  = None

    def update_query(self, **updates):
        """
        Can be used instead of self.query_dict.update() to add/change
        query params in situations where the original contents are not
        required.
        """
        self._url_updates.update(updates)

    @property
    def query_dict(self):
        """
        Parses the `params' attribute of the original urlparse and
        generates a dictionary where both the keys and values have
        been url_unescape'd.  Any updates or changes to the resulting
        dict will be reflected in the updated query params
        """
        if self._query_dict is None:
            def _split(param):
                p = param.split('=')
                return (unquote_plus(p[0]),
                        unquote_plus('='.join(p[1:])))
            self._query_dict = dict(_split(p) for p in self.query.split('&')
                                    if p)
        return self._query_dict

    def path_extension(self):
        """
        Fetches the current extension of the path.
        """
        return self.path.split('/')[-1].split('.')[-1]

    def set_extension(self, extension):
        """
        Changes the extension of the path to the provided value (the
        "." should not be included in the extension as a "." is
        provided)
        """
        pieces = self.path.split('/')
        dirs = pieces[:-1]
        base = pieces[-1].split('.')
        base = '.'.join(base[:-1] if len(base) > 1 else base)
        if extension:
            base += '.' + extension
        dirs.append(base)
        self.path =  '/'.join(dirs)
        return self


    def unparse(self):
        """
        Converts the url back to a string, applying all updates made
        to the feilds thereof.

        Note: if a host name has been added and none was present
        before, will enforce scheme -> "http" unless otherwise
        specified.  Double-slashes are removed from the resultant
        path, and the query string is reconstructed only if the
        query_dict has been modified/updated.
        """
        # only parse the query params if there is an update dict
        q = self.query
        if self._url_updates or self._query_dict is not None:
            q = self._query_dict or self.query_dict
            q.update(self._url_updates)
            q = query_string(q).lstrip('?')

        # make sure the port is not doubly specified
        if self.port and ":" in self.hostname:
            self.hostname = self.hostname.split(':')[0]

        # if there is a netloc, there had better be a scheme
        if self.netloc and not self.scheme:
            self.scheme = "http"

        return urlunparse((self.scheme, self.netloc,
                           self.path.replace('//', '/'),
                           self.params, q, self.fragment))

    def path_has_subreddit(self):
        """
        utility method for checking if the path starts with a
        subreddit specifier (namely /r/ or /subreddits/).
        """
        return self.path.startswith(('/r/', '/subreddits/', '/reddits/'))

    def get_subreddit(self):
        """checks if the current url refers to a subreddit and returns
        that subreddit object.  The cases here are:

          * the hostname is unset or is g.domain, in which case it
            looks for /r/XXXX or /subreddits.  The default in this case
            is Default.
          * the hostname is a cname to a known subreddit.

        On failure to find a subreddit, returns None.
        """
        from pylons import g
        from r2.models import Subreddit, Sub, NotFound, DefaultSR
        try:
            if not self.hostname or self.hostname.startswith(g.domain):
                if self.path.startswith('/r/'):
                    return Subreddit._by_name(self.path.split('/')[2])
                elif self.path.startswith(('/subreddits/', '/reddits/')):
                    return Sub
                else:
                    return DefaultSR()
            elif self.hostname:
                return Subreddit._by_domain(self.hostname)
        except NotFound:
            pass
        return None

    def is_reddit_url(self, subreddit = None):
        """utility method for seeing if the url is associated with
        reddit as we don't necessarily want to mangle non-reddit
        domains

        returns true only if hostname is nonexistant, a subdomain of
        g.domain, or a subdomain of the provided subreddit's cname.
        """
        from pylons import g
        return (not self.hostname or
                is_subdomain(self.hostname, g.domain) or
                (subreddit and subreddit.domain and
                 is_subdomain(self.hostname, subreddit.domain)))

    def path_add_subreddit(self, subreddit):
        """
        Adds the subreddit's path to the path if another subreddit's
        prefix is not already present.
        """
        if not (self.path_has_subreddit()
                or self.path.startswith(subreddit.user_path)):
            self.path = (subreddit.user_path + self.path)
        return self

    @property
    def netloc(self):
        """
        Getter method which returns the hostname:port, or empty string
        if no hostname is present.
        """
        if not self.hostname:
            return ""
        elif getattr(self, "port", None):
            return self.hostname + ":" + str(self.port)
        return self.hostname

    def mk_cname(self, require_frame = True, subreddit = None, port = None):
        """
        Converts a ?cnameframe url into the corresponding cnamed
        domain if applicable.  Useful for frame-busting on redirect.
        """

        # make sure the url is indeed in a frame
        if require_frame and not self.query_dict.has_key(self.cname_get):
            return self

        # fetch the subreddit and make sure it
        subreddit = subreddit or self.get_subreddit()
        if subreddit and subreddit.domain:

            # no guarantee there was a scheme
            self.scheme = self.scheme or "http"

            # update the domain (preserving the port)
            self.hostname = subreddit.domain
            self.port = self.port or port

            # and remove any cnameframe GET parameters
            if self.query_dict.has_key(self.cname_get):
                del self._query_dict[self.cname_get]

            # remove the subreddit reference
            self.path = lstrips(self.path, subreddit.path)
            if not self.path.startswith('/'):
                self.path = '/' + self.path

        return self

    def is_in_frame(self):
        """
        Checks if the url is in a frame by determining if
        cls.cname_get is present.
        """
        return self.query_dict.has_key(self.cname_get)

    def put_in_frame(self):
        """
        Adds the cls.cname_get get parameter to the query string.
        """
        self.update_query(**{self.cname_get:random.random()})

    def __repr__(self):
        return "<URL %s>" % repr(self.unparse())

    def domain_permutations(self, fragments=False, subdomains=True):
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
        ret = set()
        if self.hostname:
            r = self.hostname.split('.')

            if subdomains:
                for x in xrange(len(r)-1):
                    ret.add('.'.join(r[x:len(r)]))

            if fragments:
                for x in r:
                    ret.add(x)

        return ret

    @classmethod
    def base_url(cls, url):
        u = cls(url)

        # strip off any www and lowercase the hostname:
        netloc = strip_www(u.netloc.lower())

        # http://code.google.com/web/ajaxcrawling/docs/specification.html
        fragment = u.fragment if u.fragment.startswith("!") else ""

        return urlunparse((u.scheme.lower(), netloc,
                           u.path, u.params, u.query, fragment))


def pload(fname, default = None):
    "Load a pickled object from a file"
    try:
        f = file(fname, 'r')
        d = pickle.load(f)
    except IOError:
        d = default
    else:
        f.close()
    return d

def psave(fname, d):
    "Save a pickled object into a file"
    f = file(fname, 'w')
    pickle.dump(d, f)
    f.close()

def unicode_safe(res):
    try:
        return str(res)
    except UnicodeEncodeError:
        try:
            return unicode(res).encode('utf-8')
        except UnicodeEncodeError:
            return res.decode('utf-8').encode('utf-8')

def decompose_fullname(fullname):
    """
        decompose_fullname("t3_e4fa") ->
            (Thing, 3, 658918)
    """
    from r2.lib.db.thing import Thing,Relation
    if fullname[0] == 't':
        type_class = Thing
    elif fullname[0] == 'r':
        type_class = Relation

    type_id36, thing_id36 = fullname[1:].split('_')

    type_id = int(type_id36,36)
    id      = int(thing_id36,36)

    return (type_class, type_id, id)

def cols(lst, ncols):
    """divides a list into columns, and returns the
    rows. e.g. cols('abcdef', 2) returns (('a', 'd'), ('b', 'e'), ('c',
    'f'))"""
    nrows = int(math.ceil(1.*len(lst) / ncols))
    lst = lst + [None for i in range(len(lst), nrows*ncols)]
    cols = [lst[i:i+nrows] for i in range(0, nrows*ncols, nrows)]
    rows = zip(*cols)
    rows = [filter(lambda x: x is not None, r) for r in rows]
    return rows

def fetch_things(t_class,since,until,batch_fn=None,
                 *query_params, **extra_query_dict):
    """
        Simple utility function to fetch all Things of class t_class
        (spam or not, but not deleted) that were created from 'since'
        to 'until'
    """

    from r2.lib.db.operators import asc

    if not batch_fn:
        batch_fn = lambda x: x

    query_params = ([t_class.c._date >= since,
                     t_class.c._date <  until,
                     t_class.c._spam == (True,False)]
                    + list(query_params))
    query_dict   = {'sort':  asc('_date'),
                    'limit': 100,
                    'data':  True}
    query_dict.update(extra_query_dict)

    q = t_class._query(*query_params,
                        **query_dict)

    orig_rules = deepcopy(q._rules)

    things = list(q)
    while things:
        things = batch_fn(things)
        for t in things:
            yield t
        q._rules = deepcopy(orig_rules)
        q._after(t)
        things = list(q)

def fetch_things2(query, chunk_size = 100, batch_fn = None, chunks = False):
    """Incrementally run query with a limit of chunk_size until there are
    no results left. batch_fn transforms the results for each chunk
    before returning."""

    assert query._sort, "you must specify the sort order in your query!"

    orig_rules = deepcopy(query._rules)
    query._limit = chunk_size
    items = list(query)
    done = False
    while items and not done:
        #don't need to query again at the bottom if we didn't get enough
        if len(items) < chunk_size:
            done = True

        after = items[-1]

        if batch_fn:
            items = batch_fn(items)

        if chunks:
            yield items
        else:
            for i in items:
                yield i

        if not done:
            query._rules = deepcopy(orig_rules)
            query._after(after)
            items = list(query)

def fix_if_broken(thing, delete = True, fudge_links = False):
    from r2.models import Link, Comment, Subreddit, Message

    # the minimum set of attributes that are required
    attrs = dict((cls, cls._essentials)
                 for cls
                 in (Link, Comment, Subreddit, Message))

    if thing.__class__ not in attrs:
        raise TypeError

    tried_loading = False
    for attr in attrs[thing.__class__]:
        try:
            # try to retrieve the attribute
            getattr(thing, attr)
        except AttributeError:
            # that failed; let's explicitly load it and try again

            if not tried_loading:
                tried_loading = True
                thing._load()

            try:
                getattr(thing, attr)
            except AttributeError:
                if not delete:
                    raise
                if isinstance(thing, Link) and fudge_links:
                    if attr == "sr_id":
                        thing.sr_id = 6
                        print "Fudging %s.sr_id to %d" % (thing._fullname,
                                                          thing.sr_id)
                    elif attr == "author_id":
                        thing.author_id = 8244672
                        print "Fudging %s.author_id to %d" % (thing._fullname,
                                                              thing.author_id)
                    else:
                        print "Got weird attr %s; can't fudge" % attr

                if not thing._deleted:
                    print "%s is missing %r, deleting" % (thing._fullname, attr)
                    thing._deleted = True

                thing._commit()

                if not fudge_links:
                    break


def find_recent_broken_things(from_time = None, to_time = None,
                              delete = False):
    """
        Occasionally (usually during app-server crashes), Things will
        be partially written out to the database. Things missing data
        attributes break the contract for these things, which often
        breaks various pages. This function hunts for and destroys
        them as appropriate.
    """
    from r2.models import Link, Comment
    from r2.lib.db.operators import desc
    from pylons import g

    from_time = from_time or timeago('1 hour')
    to_time = to_time or datetime.now(g.tz)

    for cls in (Link, Comment):
        q = cls._query(cls.c._date > from_time,
                       cls.c._date < to_time,
                       data=True,
                       sort=desc('_date'))
        for thing in fetch_things2(q):
            fix_if_broken(thing, delete = delete)


def timeit(func):
    "Run some function, and return (RunTimeInSeconds,Result)"
    before=time.time()
    res=func()
    return (time.time()-before,res)
def lineno():
    "Returns the current line number in our program."
    import inspect
    print "%s\t%s" % (datetime.now(),inspect.currentframe().f_back.f_lineno)

def IteratorFilter(iterator, fn):
    for x in iterator:
        if fn(x):
            yield x

def UniqueIterator(iterator, key = lambda x: x):
    """
    Takes an iterator and returns an iterator that returns only the
    first occurence of each entry
    """
    so_far = set()
    def no_dups(x):
        k = key(x)
        if k in so_far:
            return False
        else:
            so_far.add(k)
            return True

    return IteratorFilter(iterator, no_dups)

def modhash(user, rand = None, test = False):
    return user.name

def valid_hash(user, hash):
    return True

def check_cheating(loc):
    pass

def vote_hash(user, thing, note='valid'):
    return user.name

def valid_vote_hash(hash, user, thing):
    return True

def safe_eval_str(unsafe_str):
    return unsafe_str.replace('\\x3d', '=').replace('\\x26', '&')

rx_whitespace = re.compile('\s+', re.UNICODE)
rx_notsafe = re.compile('\W+', re.UNICODE)
rx_underscore = re.compile('_+', re.UNICODE)
def title_to_url(title, max_length = 50):
    """Takes a string and makes it suitable for use in URLs"""
    title = _force_unicode(title)           #make sure the title is unicode
    title = rx_whitespace.sub('_', title)   #remove whitespace
    title = rx_notsafe.sub('', title)       #remove non-printables
    title = rx_underscore.sub('_', title)   #remove double underscores
    title = title.strip('_')                #remove trailing underscores
    title = title.lower()                   #lowercase the title

    if len(title) > max_length:
        #truncate to nearest word
        title = title[:max_length]
        last_word = title.rfind('_')
        if (last_word > 0):
            title = title[:last_word]
    return title or "_"

def dbg(s):
    import sys
    sys.stderr.write('%s\n' % (s,))

def trace(fn):
    def new_fn(*a,**kw):
        ret = fn(*a,**kw)
        dbg("Fn: %s; a=%s; kw=%s\nRet: %s"
            % (fn,a,kw,ret))
        return ret
    return new_fn

def common_subdomain(domain1, domain2):
    if not domain1 or not domain2:
        return ""
    domain1 = domain1.split(":")[0]
    domain2 = domain2.split(":")[0]
    if len(domain1) > len(domain2):
        domain1, domain2 = domain2, domain1

    if domain1 == domain2:
        return domain1
    else:
        dom = domain1.split(".")
        for i in range(len(dom), 1, -1):
            d = '.'.join(dom[-i:])
            if domain2.endswith(d):
                return d
    return ""

def interleave_lists(*args):
    max_len = max(len(x) for x in args)
    for i in xrange(max_len):
        for a in args:
            if i < len(a):
                yield a[i]

def link_from_url(path, filter_spam = False, multiple = True):
    from pylons import c
    from r2.models import IDBuilder, Link, Subreddit, NotFound

    if not path:
        return

    try:
        links = Link._by_url(path, c.site)
    except NotFound:
        return [] if multiple else None

    return filter_links(tup(links), filter_spam = filter_spam,
                        multiple = multiple)

def filter_links(links, filter_spam = False, multiple = True):
    # run the list through a builder to remove any that the user
    # isn't allowed to see
    from pylons import c
    from r2.models import IDBuilder, Link, Subreddit, NotFound
    links = IDBuilder([link._fullname for link in links],
                      skip = False).get_items()[0]
    if not links:
        return

    if filter_spam:
        # first, try to remove any spam
        links_nonspam = [ link for link in links
                          if not link._spam ]
        if links_nonspam:
            links = links_nonspam

    # if it occurs in one or more of their subscriptions, show them
    # that one first
    subs = set(Subreddit.user_subreddits(c.user, limit = None))
    def cmp_links(a, b):
        if a.sr_id in subs and b.sr_id not in subs:
            return -1
        elif a.sr_id not in subs and b.sr_id in subs:
            return 1
        else:
            return cmp(b._hot, a._hot)
    links = sorted(links, cmp = cmp_links)

    # among those, show them the hottest one
    return links if multiple else links[0]

def url_links_builder(url, exclude=None, num=None, after=None, reverse=None,
                      count=None):
    from r2.lib.template_helpers import add_sr
    from r2.models import IDBuilder, Link, NotFound
    from operator import attrgetter

    if url.startswith('/'):
        url = add_sr(url, force_hostname=True)

    try:
        links = tup(Link._by_url(url, None))
    except NotFound:
        links = []

    links = [ link for link in links
                   if link._fullname != exclude ]
    links.sort(key=attrgetter('num_comments'), reverse=True)

    # don't show removed links in duplicates unless admin or mod
    # or unless it's your own post
    def include_link(link):
        return (not link._spam or
                (c.user_is_loggedin and
                    (link.author_id == c.user._id or
                        c.user_is_admin or
                        link.subreddit.is_moderator(c.user))))

    builder = IDBuilder([link._fullname for link in links], skip=True,
                        keep_fn=include_link, num=num, after=after,
                        reverse=reverse, count=count)

    return builder

class TimeoutFunctionException(Exception):
    pass

class TimeoutFunction:
    """Force an operation to timeout after N seconds. Works with POSIX
       signals, so it's not safe to use in a multi-treaded environment"""
    def __init__(self, function, timeout):
        self.timeout = timeout
        self.function = function

    def handle_timeout(self, signum, frame):
        raise TimeoutFunctionException()

    def __call__(self, *args):
        # can only be called from the main thread
        old = signal.signal(signal.SIGALRM, self.handle_timeout)
        signal.alarm(self.timeout)
        try:
            result = self.function(*args)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)
        return result

def make_offset_date(start_date, interval, future = True,
                     business_days = False):
    """
    Generates a date in the future or past "interval" days from start_date.

    Can optionally give weekends no weight in the calculation if
    "business_days" is set to true.
    """
    if interval is not None:
        interval = int(interval)
        if business_days:
            weeks = interval / 7
            dow = start_date.weekday()
            if future:
                future_dow = (dow + interval) % 7
                if dow > future_dow or future_dow > 4:
                    weeks += 1
            else:
                future_dow = (dow - interval) % 7
                if dow < future_dow or future_dow > 4:
                    weeks += 1
            interval += 2 * weeks;
        if future:
            return start_date + timedelta(interval)
        return start_date - timedelta(interval)
    return start_date

def to_date(d):
    if isinstance(d, datetime):
        return d.date()
    return d

def to_datetime(d):
    if isinstance(d, date):
        return datetime(d.year, d.month, d.day)
    return d

def in_chunks(it, size=25):
    chunk = []
    it = iter(it)
    try:
        while True:
            chunk.append(it.next())
            if len(chunk) >= size:
                yield chunk
                chunk = []
    except StopIteration:
        if chunk:
            yield chunk

def spaceout(items, targetseconds,
             minsleep = 0, die = False,
             estimate = None):
    """Given a list of items and a function to apply to them, space
       the execution out over the target number of seconds and
       optionally stop when we're out of time"""
    targetseconds = float(targetseconds)
    state = [1.0]

    if estimate is None:
        try:
            estimate = len(items)
        except TypeError:
            # if we can't come up with an estimate, the best we can do
            # is just enforce the minimum sleep time (and the max
            # targetseconds if die==True)
            pass

    mean = lambda lst: sum(float(x) for x in lst)/float(len(lst))
    beginning = datetime.now()

    for item in items:
        start = datetime.now()
        yield item
        end = datetime.now()

        took_delta = end - start
        took = (took_delta.days * 60 * 24
                + took_delta.seconds
                + took_delta.microseconds/1000000.0)
        state.append(took)
        if len(state) > 10:
            del state[0]

        if die and end > beginning + timedelta(seconds=targetseconds):
            # we ran out of time, ignore the rest of the iterator
            break

        if estimate is None:
            if minsleep:
                # we have no idea how many items we're going to get
                sleep(minsleep)
        else:
            sleeptime = max((targetseconds / estimate) - mean(state),
                            minsleep)
            if sleeptime > 0:
                sleep(sleeptime)

def progress(it, verbosity=100, key=repr, estimate=None, persec=True):
    """An iterator that yields everything from `it', but prints progress
       information along the way, including time-estimates if
       possible"""
    from itertools import islice
    from datetime import datetime
    import sys

    now = start = datetime.now()
    elapsed = start - start

    # try to guess at the estimate if we can
    if estimate is None:
        try:
            estimate = len(it)
        except:
            pass

    def timedelta_to_seconds(td):
        return td.days * (24*60*60) + td.seconds + (float(td.microseconds) / 1000000)
    def format_timedelta(td, sep=''):
        ret = []
        s = timedelta_to_seconds(td)
        if s < 0:
            neg = True
            s *= -1
        else:
            neg = False

        if s >= (24*60*60):
            days = int(s//(24*60*60))
            ret.append('%dd' % days)
            s -= days*(24*60*60)
        if s >= 60*60:
            hours = int(s//(60*60))
            ret.append('%dh' % hours)
            s -= hours*(60*60)
        if s >= 60:
            minutes = int(s//60)
            ret.append('%dm' % minutes)
            s -= minutes*60
        if s >= 1:
            seconds = int(s)
            ret.append('%ds' % seconds)
            s -= seconds

        if not ret:
            return '0s'

        return ('-' if neg else '') + sep.join(ret)
    def format_datetime(dt, show_date=False):
        if show_date:
            return dt.strftime('%Y-%m-%d %H:%M')
        else:
            return dt.strftime('%H:%M:%S')
    def deq(dt1, dt2):
        "Indicates whether the two datetimes' dates describe the same (day,month,year)"
        d1, d2 = dt1.date(), dt2.date()
        return (    d1.day   == d2.day
                and d1.month == d2.month
                and d1.year  == d2.year)

    sys.stderr.write('Starting at %s\n' % (start,))

    # we're going to islice it so we need to start an iterator
    it = iter(it)

    seen = 0
    while True:
        this_chunk = 0
        thischunk_started = datetime.now()

        # the simple bit: just iterate and yield
        for item in islice(it, verbosity):
            this_chunk += 1
            seen += 1
            yield item

        if this_chunk < verbosity:
            # we're done, the iterator is empty
            break

        now = datetime.now()
        elapsed = now - start
        thischunk_seconds = timedelta_to_seconds(now - thischunk_started)

        if estimate:
            # the estimate is based on the total number of items that
            # we've processed in the total amount of time that's
            # passed, so it should smooth over momentary spikes in
            # speed (but will take a while to adjust to long-term
            # changes in speed)
            remaining = ((elapsed/seen)*estimate)-elapsed
            completion = now + remaining
            count_str = ('%d/%d %.2f%%'
                         % (seen, estimate, float(seen)/estimate*100))
            completion_str = format_datetime(completion, not deq(completion,now))
            estimate_str = (' (%s remaining; completion %s)'
                            % (format_timedelta(remaining),
                               completion_str))
        else:
            count_str = '%d' % seen
            estimate_str = ''

        if key:
            key_str = ': %s' % key(item)
        else:
            key_str = ''

        # unlike the estimate, the persec count is the number per
        # second for *this* batch only, without smoothing
        if persec and thischunk_seconds > 0:
            persec_str = ' (%.1f/s)' % (float(this_chunk)/thischunk_seconds,)
        else:
            persec_str = ''

        sys.stderr.write('%s%s, %s%s%s\n'
                         % (count_str, persec_str,
                            format_timedelta(elapsed), estimate_str, key_str))

    now = datetime.now()
    elapsed = now - start
    elapsed_seconds = timedelta_to_seconds(elapsed)
    if persec and seen > 0 and elapsed_seconds > 0:
        persec_str = ' (@%.1f/sec)' % (float(seen)/elapsed_seconds)
    else:
        persec_str = ''
    sys.stderr.write('Processed %d%s items in %s..%s (%s)\n'
                     % (seen,
                        persec_str,
                        format_datetime(start, not deq(start, now)),
                        format_datetime(now, not deq(start, now)),
                        format_timedelta(elapsed)))

class Hell(object):
    def __str__(self):
        return "boom!"

class Bomb(object):
    @classmethod
    def __getattr__(cls, key):
        raise Hell()

    @classmethod
    def __setattr__(cls, key, val):
        raise Hell()

    @classmethod
    def __repr__(cls):
        raise Hell()

class SimpleSillyStub(object):
    """A simple stub object that does nothing when you call its methods."""
    def __nonzero__(self):
        return False

    def __getattr__(self, name):
        return self.stub

    def stub(self, *args, **kwargs):
        pass

def strordict_fullname(item, key='fullname'):
    """Sometimes we migrate AMQP queues from simple strings to pickled
    dictionaries. During the migratory period there may be items in
    the queue of both types, so this function tries to detect which
    the item is. It shouldn't really be used on a given queue for more
    than a few hours or days"""
    try:
        d = pickle.loads(item)
    except:
        d = {key: item}

    if (not isinstance(d, dict)
        or key not in d
        or not isinstance(d[key], str)):
        raise ValueError('Error trying to migrate %r (%r)'
                         % (item, d))

    return d

def thread_dump(*a):
    import sys, traceback
    from datetime import datetime

    sys.stderr.write('%(t)s Thread Dump @%(d)s %(t)s\n' % dict(t='*'*15,
                                                               d=datetime.now()))

    for thread_id, stack in sys._current_frames().items():
        sys.stderr.write('\t-- Thread ID: %s--\n' %  (thread_id,))

        for filename, lineno, fnname, line in traceback.extract_stack(stack):
            sys.stderr.write('\t\t%(filename)s(%(lineno)d): %(fnname)s\n'
                             % dict(filename=filename, lineno=lineno, fnname=fnname))
            sys.stderr.write('\t\t\t%(line)s\n' % dict(line=line))


def constant_time_compare(actual, expected):
    """
    Returns True if the two strings are equal, False otherwise

    The time taken is dependent on the number of characters provided
    instead of the number of characters that match.
    """
    actual_len   = len(actual)
    expected_len = len(expected)
    result = actual_len ^ expected_len
    if expected_len > 0:
        for i in xrange(actual_len):
            result |= ord(actual[i]) ^ ord(expected[i % expected_len])
    return result == 0


def extract_urls_from_markdown(md):
    "Extract URLs that will be hot links from a piece of raw Markdown."

    html = snudown.markdown(_force_utf8(md))
    links = SoupStrainer("a")

    for link in BeautifulSoup(html, parseOnlyThese=links):
        url = link.get('href')
        if url:
            yield url


def summarize_markdown(md):
    """Get the first paragraph of some Markdown text, potentially truncated."""

    first_graf, sep, rest = md.partition("\n\n")
    return first_graf[:500]


def find_containing_network(ip_ranges, address):
    """Find an IP network that contains the given address."""
    addr = ipaddress.ip_address(address)
    for network in ip_ranges:
        if addr in network:
            return network
    return None


def is_throttled(address):
    """Determine if an IP address is in a throttled range."""
    return bool(find_containing_network(g.throttles, address))


def parse_http_basic(authorization_header):
    """Parse the username/credentials out of an HTTP Basic Auth header.

    Raises RequirementException if anything is uncool.
    """
    auth_scheme, auth_token = require_split(authorization_header, 2)
    require(auth_scheme.lower() == "basic")
    try:
        auth_data = base64.b64decode(auth_token)
    except TypeError:
        raise RequirementException
    return require_split(auth_data, 2, ":")


def simple_traceback(limit):
    """Generate a pared-down traceback that's human readable but small.

    `limit` is how many frames of the stack to put in the traceback.

    """

    stack_trace = traceback.extract_stack(limit=limit)[:-2]
    return "\n".join(":".join((os.path.basename(filename),
                               function_name,
                               str(line_number),
                              ))
                     for filename, line_number, function_name, text
                     in stack_trace)


def weighted_lottery(weights, _random=random.random):
    """Randomly choose a key from a dict where values are weights.

    Weights should be non-negative numbers, and at least one weight must be
    non-zero. The probability that a key will be selected is proportional to
    its weight relative to the sum of all weights. Keys with zero weight will
    be ignored.

    Raises ValueError if weights is empty or contains a negative weight.
    """

    total = sum(weights.itervalues())
    if total <= 0:
        raise ValueError("total weight must be positive")

    r = _random() * total
    t = 0
    for key, weight in weights.iteritems():
        if weight < 0:
            raise ValueError("weight for %r must be non-negative" % key)
        t += weight
        if t > r:
            return key

    # this point should never be reached
    raise ValueError(
        "weighted_lottery messed up: r=%r, t=%r, total=%r" % (r, t, total))


def read_static_file_config(config_file):
    parser = ConfigParser.RawConfigParser()
    with open(config_file, "r") as cf:
        parser.readfp(cf)
    config = dict(parser.items("static_files"))

    s3 = boto.connect_s3(config["aws_access_key_id"],
                         config["aws_secret_access_key"])
    bucket = s3.get_bucket(config["bucket"])

    return bucket, config


class GoldPrice(object):
    """Simple price math / formatting type.

    Prices are assumed to be USD at the moment.

    """
    def __init__(self, decimal):
        self.decimal = Decimal(decimal)

    def __mul__(self, other):
        return type(self)(self.decimal * other)

    def __div__(self, other):
        return type(self)(self.decimal / other)

    def __str__(self):
        return "$%s" % self.decimal.quantize(Decimal("1.00"))

    def __repr__(self):
        return "%s(%s)" % (type(self).__name__, self)

    @property
    def pennies(self):
        return int(self.decimal * 100)


def config_gold_price(v, key=None, data=None):
    return GoldPrice(v)


def canonicalize_email(email):
    """Return the given email address without various localpart manglings.

    a.s.d.f+something@gmail.com --> asdf@gmail.com

    This is not at all RFC-compliant or correct. It's only intended to be a
    quick heuristic to remove commonly used mangling techniques.

    """

    if not email:
        return ""

    email = _force_utf8(email.lower())

    localpart, at, domain = email.partition("@")
    if not at or "@" in domain:
        return ""

    localpart = localpart.replace(".", "")
    localpart = localpart.partition("+")[0]

    return localpart + "@" + domain
