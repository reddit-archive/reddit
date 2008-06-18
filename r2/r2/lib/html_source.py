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
from HTMLParser import HTMLParser

_indent = '  '

def tagstr(tag):
    return '<span style="font-weight: bold;color:blue">%s</span>' % tag

def tagend(tag, line=0):
    if not line:
        return error(tag)
    return '<a href="#line_%d">%s</a>' % (line, tagstr(tag))

def error(strng):
    return '<span style="color:red; font-weight:bold">%s</span>' % strng

class HTMLValidationParser(HTMLParser):
    def __init__(self, *a, **kw):
        self.indent = '';
        HTMLParser.__init__(self, *a, **kw)
        self.processed_text = ''
        self.tagtracker = []
        self.error_line = 0
        self.line_number = 1

    def nextLine(self, text):
        self.processed_text += '<a id="line_%s" />' % self.line_number
        self.processed_text += text
        self.line_number += 1

    def handle_starttag(self, tag, attrs):
        self.tagtracker.append((tag.lower(), self.line_number))
        atts = ' '.join(['%s="%s"' %(x,y) for (x, y) in attrs])
        res =  "%s&lt;%s%s&gt;\n" % \
            (self.indent, tagstr(tag), atts and ' ' + atts or '')
        self.indent += _indent
        self.nextLine(res)

    def handle_endtag(self, tag):
        line = 0
        if self.tagtracker:
            if self.tagtracker[-1][0] == tag.lower():
                line = self.tagtracker[-1][1]
                self.tagtracker = self.tagtracker[:-1]
            else:
                self.error_line = self.line_number
                
        if(self.indent):
            self.indent = self.indent[:-len(_indent)]
        self.nextLine("%s&lt;/%s&gt;\n" % (self.indent, tagend(tag, line)))

    def handle_startendtag(self, tag, attrs):
        atts =  ' '.join(['%s="%s"' %(x,y) for (x, y) in attrs])
        res = "%s&lt;%s%s/&gt;\n" % \
            (self.indent, tagstr(tag), atts and ' ' + atts or '')
        self.nextLine(res)

    def handle_data(self, data):
        data2 = data = data.replace('\n', '')
        if data2.replace('\t', '').replace(' ', ''):
            self.nextLine(self.indent + data + '\n')

    def feed(self, text):
        HTMLParser.feed(self, text)
        pretext = ''
        if self.error_line:
            el = self.error_line
            if self.tagtracker:
                etag, etagl = self.tagtracker[-1]
                pretext =  '<p>Error on <a href="#line_%d">line %d</a>.  Unclosed %s tag on <a href="#line_%d">line %d</a></p>' % (el, el, etag, etagl, etagl)
            else:
                pretext =  '<p>Error on <a href="#line_%d">line %d</a>.  Extra closing tag</p>' % (el, el)
                

        return pretext + "<pre>" + self.processed_text + "</pre>"
