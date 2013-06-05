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

import cgi
import os
import urllib
import re

from collections import Counter

import snudown
from cStringIO import StringIO

from xml.sax.handler import ContentHandler
from lxml.sax import saxify
import lxml.etree
from BeautifulSoup import BeautifulSoup, Tag

from pylons import g, c

from wrapped import Templated, CacheStub

SC_OFF = "<!-- SC_OFF -->"
SC_ON = "<!-- SC_ON -->"

MD_START = '<div class="md">'
MD_END = '</div>'

WIKI_MD_START = '<div class="md wiki">'
WIKI_MD_END = '</div>'

custom_img_url = re.compile(r'\A%%([a-zA-Z0-9\-]+)%%$')

def python_websafe(text):
    return text.replace('&', "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

def python_websafe_json(text):
    return text.replace('&', "&amp;").replace("<", "&lt;").replace(">", "&gt;")

try:
    from Cfilters import uwebsafe as c_websafe, uspace_compress, \
        uwebsafe_json as c_websafe_json
    def spaceCompress(text):
        try:
            text = unicode(text, 'utf-8')
        except TypeError:
            text = unicode(text)
        return uspace_compress(text)
except ImportError:
    c_websafe      = python_websafe
    c_websafe_json = python_websafe_json
    _between_tags1 = re.compile('> +')
    _between_tags2 = re.compile(' +<')
    _spaces = re.compile('[\s]+')
    _ignore = re.compile('(' + SC_OFF + '|' + SC_ON + ')', re.S | re.I)
    def spaceCompress(content):
        res = ''
        sc = True
        for p in _ignore.split(content):
            if p == SC_ON:
                sc = True
            elif p == SC_OFF:
                sc = False
            elif sc:
                p = _spaces.sub(' ', p)
                p = _between_tags1.sub('>', p)
                p = _between_tags2.sub('<', p)
                res += p
            else:
                res += p

        return res

class _Unsafe(unicode): pass

def _force_unicode(text):
    if text == None:
        return u''

    if isinstance(text, unicode):
        return text

    try:
        text = unicode(text, 'utf-8')
    except UnicodeDecodeError:
        text = unicode(text, 'latin1')
    except TypeError:
        text = unicode(text)
    return text

def _force_utf8(text):
    return str(_force_unicode(text).encode('utf8'))

def unsafe(text=''):
    return _Unsafe(_force_unicode(text))

def websafe_json(text=""):
    return c_websafe_json(_force_unicode(text))

def mako_websafe(text = ''):
    if text.__class__ == _Unsafe:
        return text
    elif isinstance(text, Templated):
        return _Unsafe(text.render())
    elif isinstance(text, CacheStub):
        return _Unsafe(text)
    elif text is None:
        return ""
    elif text.__class__ != unicode:
        text = _force_unicode(text)
    return c_websafe(text)

def websafe(text=''):
    if text.__class__ != unicode:
        text = _force_unicode(text)
    #wrap the response in _Unsafe so make_websafe doesn't unescape it
    return _Unsafe(c_websafe(text))


valid_link_schemes = (
    '/',
    '#',
    'http://',
    'https://',
    'ftp://',
    'mailto:',
    'steam://',
    'irc://',
    'ircs://',
    'news://',
    'mumble://',
    'ssh://',
    'git://',
    'ts3server://',
)

class SouptestSaxHandler(ContentHandler):
    def __init__(self, ok_tags):
        self.ok_tags = ok_tags

    def startElementNS(self, tagname, qname, attrs):
        if qname not in self.ok_tags:
            raise ValueError('HAX: Unknown tag: %r' % qname)

        for (ns, name), val in attrs.items():
            if ns is not None:
                raise ValueError('HAX: Unknown namespace? Seriously? %r' % ns)

            if name not in self.ok_tags[qname]:
                raise ValueError('HAX: Unknown attribute-name %r' % name)

            if qname == 'a' and name == 'href':
                lv = val.lower()
                if not any(lv.startswith(scheme) for scheme in valid_link_schemes):
                    raise ValueError('HAX: Unsupported link scheme %r' % val)

markdown_ok_tags = {
    'div': ('class'),
    'a': set(('href', 'title', 'target', 'nofollow', 'rel')),
    'img': set(('src', 'alt')),
    }

markdown_boring_tags =  ('p', 'em', 'strong', 'br', 'ol', 'ul', 'hr', 'li',
                         'pre', 'code', 'blockquote', 'center',
                          'sup', 'del', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',)

markdown_user_tags = ('table', 'th', 'tr', 'td', 'tbody',
                     'tbody', 'thead', 'tr', 'tfoot', 'caption')

for bt in markdown_boring_tags:
    markdown_ok_tags[bt] = ('id', 'class')

for bt in markdown_user_tags:
    markdown_ok_tags[bt] = ('colspan', 'rowspan', 'cellspacing', 'cellpadding', 'align', 'scope')

markdown_xhtml_dtd_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'contrib/dtds/xhtml.dtd')

markdown_dtd = '<!DOCTYPE div- SYSTEM "file://%s">' % markdown_xhtml_dtd_path

def markdown_souptest(text, nofollow=False, target=None, renderer='reddit'):
    if not text:
        return text
    
    if renderer == 'reddit':
        smd = safemarkdown(text, nofollow=nofollow, target=target)
    elif renderer == 'wiki':
        smd = wikimarkdown(text)

    # Prepend a DTD reference so we can load up definitions of all the standard
    # XHTML entities (&nbsp;, etc.).
    smd_with_dtd = markdown_dtd + smd

    s = StringIO(smd_with_dtd)
    parser = lxml.etree.XMLParser(load_dtd=True)
    tree = lxml.etree.parse(s, parser)
    handler = SouptestSaxHandler(markdown_ok_tags)
    saxify(tree, handler)

    return smd

#TODO markdown should be looked up in batch?
#@memoize('markdown')
def safemarkdown(text, nofollow=False, wrap=True, **kwargs):
    if not text:
        return None

    # this lets us skip the c.cname lookup (which is apparently quite
    # slow) if target was explicitly passed to this function.
    target = kwargs.get("target", None)
    if "target" not in kwargs and c.cname:
        target = "_top"

    text = snudown.markdown(_force_utf8(text), nofollow, target)

    if wrap:
        return SC_OFF + MD_START + text + MD_END + SC_ON
    else:
        return SC_OFF + text + SC_ON

def wikimarkdown(text, include_toc=True, target=None):
    from r2.lib.cssfilter import legacy_s3_url
    
    def img_swap(tag):
        name = tag.get('src')
        name = custom_img_url.search(name)
        name = name and name.group(1)
        if name and c.site.images.has_key(name):
            url = c.site.images[name]
            url = legacy_s3_url(url, c.site)
            tag['src'] = url
        else:
            tag.extract()
    
    nofollow = True
    
    text = snudown.markdown(_force_utf8(text), nofollow, target,
                            renderer=snudown.RENDERER_WIKI)
    
    # TODO: We should test how much of a load this adds to the app
    soup = BeautifulSoup(text.decode('utf-8'))
    images = soup.findAll('img')
    
    if images:
        [img_swap(image) for image in images]
    
    if include_toc:
        tocdiv = generate_table_of_contents(soup, prefix="wiki")
        if tocdiv:
            soup.insert(0, tocdiv)
    
    text = str(soup)
    
    return SC_OFF + WIKI_MD_START + text + WIKI_MD_END + SC_ON

title_re = re.compile('[^\w.-]')
header_re = re.compile('^h[1-6]$')
def generate_table_of_contents(soup, prefix):
    header_ids = Counter()
    headers = soup.findAll(header_re)
    if not headers:
        return
    tocdiv = Tag(soup, "div", [("class", "toc")])
    parent = Tag(soup, "ul")
    parent.level = 0
    tocdiv.append(parent)
    level = 0
    previous = 0
    for header in headers:
        contents = u''.join(header.findAll(text=True))
        
        # In the event of an empty header, skip
        if not contents:
            continue
        
        # Convert html entities to avoid ugly header ids
        aid = unicode(BeautifulSoup(contents, convertEntities=BeautifulSoup.XML_ENTITIES))
        # Prefix with PREFIX_ to avoid ID conflict with the rest of the page
        aid = u'%s_%s' % (prefix, aid.replace(" ", "_").lower())
        # Convert down to ascii replacing special characters with hex
        aid = str(title_re.sub(lambda c: '.%X' % ord(c.group()), aid))
        
        # Check to see if a tag with the same ID exists
        id_num = header_ids[aid] + 1
        header_ids[aid] += 1
        # Only start numbering ids with the second instance of an id
        if id_num > 1:
            aid = '%s%d' % (aid, id_num)
        
        header['id'] = aid
        
        li = Tag(soup, "li", [("class", aid)])
        a = Tag(soup, "a", [("href", "#%s" % aid)])
        a.string = contents
        li.append(a)
        
        thislevel = int(header.name[-1])
        
        if previous and thislevel > previous:
            newul = Tag(soup, "ul")
            newul.level = thislevel
            parent.append(newul)
            parent = newul
            level += 1
        elif level and thislevel < previous:
            while level and parent.level > thislevel:
                parent = parent.findParent("ul")
                level -= 1
        
        previous = thislevel
        parent.append(li)
    
    return tocdiv


def keep_space(text):
    text = websafe(text)
    for i in " \n\r\t":
        text=text.replace(i,'&#%02d;' % ord(i))
    return unsafe(text)


def unkeep_space(text):
    return text.replace('&#32;', ' ').replace('&#10;', '\n').replace('&#09;', '\t')
