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
# All portions of the code written by CondeNet are Copyright (c) 2006-2009
# CondeNet, Inc. All Rights Reserved.
################################################################################
from pylons import c

import cgi
import urllib
import re
from wrapped import Templated, CacheStub

SC_OFF = "<!-- SC_OFF -->"
SC_ON = "<!-- SC_ON -->"



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

#TODO is this fast?
r_url = re.compile('(?<![\(\[])(http://[^\s\'\"\]\)]+)')
jscript_url = re.compile('<a href="(?!http|ftp|mailto|/).*</a>', re.I | re.S)
img = re.compile('<img.*?>', re.I | re.S)
href_re = re.compile('<a href="([^"]+)"', re.I)
code_re = re.compile('<code>([^<]+)</code>')
a_re    = re.compile('>([^<]+)</a>')
fix_url = re.compile('&lt;(http://[^\s\'\"\]\)]+)&gt;')

#TODO markdown should be looked up in batch?
#@memoize('markdown')
def safemarkdown(text, nofollow=False, target=None):
    from contrib.markdown import markdown
    if text:
        # increase escaping of &, < and > once
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        #wrap urls in "<>" so that markdown will handle them as urls
        text = r_url.sub(r'<\1>', text)
        try:
            text = markdown(text)
        except RuntimeError:
            text = "<p><em>Comment Broken</em></p>"
        #remove images
        text = img.sub('', text)
        #wipe malicious javascript
        text = jscript_url.sub('', text)
        def href_handler(m):
            url = m.group(1).replace('&amp;', '&')
            link = '<a href="%s"' % url

            if target:
                link += ' target="%s"' % target
            elif c.cname:
                link += ' target="_top"'

            if nofollow:
                link += ' rel="nofollow"'
            return link
        def code_handler(m):
            l = m.group(1)
            return '<code>%s</code>' % l.replace('&amp;','&')
        #unescape double escaping in links
        def inner_a_handler(m):
            l = m.group(1)
            return '>%s</a>' % l.replace('&amp;','&')
        # remove the "&" escaping in urls
        text = href_re.sub(href_handler, text)
        text = code_re.sub(code_handler, text)
        text = a_re.sub(inner_a_handler, text)
        text = fix_url.sub(r'\1', text)
        return SC_OFF + '<div class="md">' + text + '</div>' + SC_ON


def keep_space(text):
    text = websafe(text)
    for i in " \n\r\t":
        text=text.replace(i,'&#%02d;' % ord(i))
    return unsafe(text)


def unkeep_space(text):
    return text.replace('&#32;', ' ').replace('&#10;', '\n').replace('&#09;', '\t')
