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
from pylons import c

import cgi
import urllib
import re

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
    _ignore = re.compile('(' + MD_START + '.*?' + MD_END + ')', re.S | re.I)
    def spaceCompress(content):
        res = ''
        for p in _ignore.split(content):
            if not p.startswith(MD_START) and not p.endswith(MD_END):
                p = _spaces.sub(' ', p)
                p = _between_tags1.sub('>', p)
                p = _between_tags2.sub('<', p)
            res += p
        return res

class _Unsafe(unicode): pass

def _force_unicode(text):
    try:
        text = unicode(text, 'utf-8')
    except TypeError:
        text = unicode(text)
    return text

def unsafe(text=''):
    return _Unsafe(_force_unicode(text))

def websafe_json(text=""):
    return c_websafe_json(_force_unicode(text))

def websafe(text=''):
    if text.__class__ == _Unsafe:
        return text
    elif text.__class__ != unicode:
        text = _force_unicode(text)
    return c_websafe(text)

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
href_re = re.compile('<a href="([^"]+)"', re.I | re.S)
code_re = re.compile('<code>([^<]+)</code>')


#TODO markdown should be looked up in batch?
#@memoize('markdown')
def safemarkdown(text):
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
        #wipe malicious javascript
        text = jscript_url.sub('', text)
        def href_handler(m):
            return '<a href="%s"' % m.group(1).replace('&amp;', '&')
        def code_handler(m):
            l = m.group(1)
            return '<code>%s</code>' % l.replace('&amp;','&')
        # remove the "&" escaping in urls
        text = href_re.sub(href_handler, text)
        text = code_re.sub(code_handler, text)
        return MD_START + text + MD_END


def keep_space(text):
    return unsafe(websafe(text).replace(' ', '&#32;').replace('\n', '&#10;').replace('\t', '&#09;'))


def unkeep_space(text):
    return text.replace('&#32;', ' ').replace('&#10;', '\n').replace('&#09;', '\t')
