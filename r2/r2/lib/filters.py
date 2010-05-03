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
from BeautifulSoup import BeautifulSoup

from pylons import c

import cgi
import urllib
import re
from wrapped import Templated, CacheStub

SC_OFF = "<!-- SC_OFF -->"
SC_ON = "<!-- SC_ON -->"

MD_START = '<div class="md">'
MD_END = '</div>'


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

from mako.filters import url_escape
def edit_comment_filter(text = ''):
    try:
        text = unicode(text, 'utf-8')
    except TypeError:
        text = unicode(text)
    return url_escape(text)

def markdown_souptest(text, nofollow=False, target=None, lang=None):
    ok_tags  = {
        'div': ('class'),
        'a': ('href', 'title', 'target', 'nofollow'),
        }

    boring_tags = ( 'p', 'em', 'strong', 'br', 'ol', 'ul', 'hr', 'li',
                    'pre', 'code', 'blockquote',
                    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', )

    for bt in boring_tags:
        ok_tags[bt] = ()

    smd = safemarkdown (text, nofollow, target, lang)
    soup = BeautifulSoup(smd)

    for tag in soup.findAll():
        if not tag.name in ok_tags:
            raise ValueError("<%s> tag found in markdown!" % tag.name)
        ok_attrs = ok_tags[tag.name]
        for k,v in tag.attrs:
            if not k in ok_attrs:
                raise ValueError("<%s %s='%s'> attr found in markdown!"
                                 % (tag.name, k,v))
            if tag.name == 'a' and k == 'href':
                lv = v.lower()
                if lv.startswith("http:"):
                    pass
                elif lv.startswith("https:"):
                    pass
                elif lv.startswith("ftp:"):
                    pass
                elif lv.startswith("mailto:"):
                    pass
                elif lv.startswith("/"):
                    pass
                else:
                    raise ValueError("Link to '%s' found in markdown!" % v)


#TODO markdown should be looked up in batch?
#@memoize('markdown')
def safemarkdown(text, nofollow=False, target=None, lang=None):
    from r2.lib.c_markdown import c_markdown
    from r2.lib.py_markdown import py_markdown
    from pylons import g

    from contrib.markdown import markdown

    if c.user.pref_no_profanity:
        text = profanity_filter(text)

    if not text:
        return None

    if c.cname and not target:
        target = "_top"

    if lang is None:
        # TODO: lang should respect g.markdown_backend
        lang = "py"

    try:
        if lang == "c":
            text = c_markdown(text, nofollow, target)
        elif lang == "py":
            text = py_markdown(text, nofollow, target)
        else:
            raise ValueError("weird lang")
    except RuntimeError:
        text = "<p><em>Comment Broken</em></p>"

    return SC_OFF + MD_START + text + MD_END + SC_ON


def keep_space(text):
    text = websafe(text)
    for i in " \n\r\t":
        text=text.replace(i,'&#%02d;' % ord(i))
    return unsafe(text)


def unkeep_space(text):
    return text.replace('&#32;', ' ').replace('&#10;', '\n').replace('&#09;', '\t')


def profanity_filter(text):
    from pylons import g

    def _profane(m):
        x = m.group(1)
        return ''.join(u"\u2731" for i in xrange(len(x)))

    if g.profanities:
        try:
            return g.profanities.sub(_profane, text)
        except UnicodeDecodeError:
            return text
    return text
