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
# All portions of the code written by CondeNet are Copyright (c) 2006-2008
# CondeNet, Inc. All Rights Reserved.
################################################################################
from __future__ import with_statement

from r2.models import *
from r2.lib.utils import sanitize_url, domain
from r2.lib.strings import string_dict

from pylons import g
from pylons.i18n import _

import re

import cssutils
from cssutils import CSSParser
from cssutils.css import CSSStyleRule
from cssutils.css import CSSValue, CSSValueList
from cssutils.css import CSSPrimitiveValue
from cssutils.css import cssproperties
from xml.dom import DOMException

msgs = string_dict['css_validator_messages']

custom_macros = {
    'num': r'[-]?\d+|[-]?\d*\.\d+',
    'percentage': r'{num}%',
    'length': r'0|{num}(em|ex|px|in|cm|mm|pt|pc)',
    'color': r'orangered|dimgray|lightgray|whitesmoke|pink',
}

custom_values = {
    '_height': r'{length}|{percentage}|auto|inherit',
    '_width': r'{length}|{percentage}|auto|inherit',
    '_overflow': r'visible|hidden|scroll|auto|inherit',
    'color': r'{color}',
    'background-color': r'{color}',
    'border-color': r'{color}',
    'background-position': r'(({percentage}|{length}){0,3})?\s*(top|center|left)?\s*(left|center|right)?',
    'opacity': r'{num}',
    'filter': r'alpha\(opacity={num}\)',
}

def _expand_macros(tokdict,macrodict):
    """ Expand macros in token dictionary """
    def macro_value(m):
        return '(?:%s)' % macrodict[m.groupdict()['macro']]
    for key, value in tokdict.items():
        while re.search(r'{[a-z][a-z0-9-]*}', value):
            value = re.sub(r'{(?P<macro>[a-z][a-z0-9-]*)}',
                           macro_value, value)
        tokdict[key] = value
    return tokdict
def _compile_regexes(tokdict):
    """ Compile all regular expressions into callable objects """
    for key, value in tokdict.items():
        tokdict[key] = re.compile('^(?:%s)$' % value, re.I).match
    return tokdict
_compile_regexes(_expand_macros(custom_values,custom_macros))

class ValidationReport(object):
    def __init__(self, original_text=''):
        self.errors        = []
        self.original_text = original_text.split('\n') if original_text else ''

    def __str__(self):
        "only for debugging"
        return "Report:\n" + '\n'.join(['\t' + str(x) for x in self.errors])

    def append(self,error):
        if hasattr(error,'line'):
            error.offending_line = self.original_text[error.line-1]
        self.errors.append(error)

class ValidationError(Exception):
    def __init__(self, message, obj = None, line = None):
        self.message  = message
        if obj is not None:
            self.obj  = obj
        # self.offending_line is the text of the actual line that
        #  caused the problem; it's set by the ValidationReport that
        #  owns this ValidationError

        if obj is not None and line is None and hasattr(self.obj,'_linetoken'):
            (_type1,_type2,self.line,_char) = obj._linetoken
        elif line is not None:
            self.line = line

    def __cmp__(self, other):
        if hasattr(self,'line') and not hasattr(other,'line'):
            return -1
        elif hasattr(other,'line') and not hasattr(self,'line'):
            return 1
        else:
            return cmp(self.line,other.line)


    def __str__(self):
        "only for debugging"
        line = (("(%d)" % self.line)
                if hasattr(self,'line') else '')
        obj = str(self.obj) if hasattr(self,'obj') else ''
        return "ValidationError%s: %s (%s)" % (line, self.message, obj)

local_urls = re.compile(r'^/static/[a-z./-]+$')
def valid_url(prop,value,report):
    url = value.getStringValue()
    if local_urls.match(url):
        pass
    elif domain(url) in g.allowed_css_linked_domains:
        pass
    else:
        report.append(ValidationError(msgs['broken_url']
                                      % dict(brokenurl = value.cssText),
                                      value))
    #elif sanitize_url(url) != url:
    #    report.append(ValidationError(msgs['broken_url']
    #                                  % dict(brokenurl = value.cssText),
    #                                  value))


def valid_value(prop,value,report):
    if not (value.valid and value.wellformed):
        if (value.wellformed
            and prop.name in cssproperties.cssvalues
            and cssproperties.cssvalues[prop.name](prop.value)):
            # it's actually valid. cssutils bug.
            pass
        elif (not value.valid
              and value.wellformed
              and prop.name in custom_values
              and custom_values[prop.name](prop.value)):
            # we're allowing it via our own custom validator
            value.valid = True

            # see if this suddenly validates the entire property
            prop.valid = True
            prop.cssValue.valid = True
            if prop.cssValue.cssValueType == CSSValue.CSS_VALUE_LIST:
                for i in range(prop.cssValue.length):
                    if not prop.cssValue.item(i).valid:
                        prop.cssValue.valid = False
                        prop.valid = False
                        break
	elif not (prop.name in cssproperties.cssvalues or prop.name in custom_values):
            error = (msgs['invalid_property']
                     % dict(cssprop = prop.name))
            report.append(ValidationError(error,value))
        else:
            error = (msgs['invalid_val_for_prop']
                     % dict(cssvalue = value.cssText,
                            cssprop  = prop.name))
            report.append(ValidationError(error,value))

    if value.primitiveType == CSSPrimitiveValue.CSS_URI:
        valid_url(prop,value,report)

error_message_extract_re = re.compile('.*\\[([0-9]+):[0-9]*:.*\\]$')
only_whitespace          = re.compile('^\s*$')
def validate_css(string):
    p = CSSParser(raiseExceptions = True)

    if not string or only_whitespace.match(string):
        return ('',ValidationReport())

    report = ValidationReport(string)
    
    # avoid a very expensive parse
    max_size_kb = 100;
    if len(string) > max_size_kb * 1024:
        report.append(ValidationError((msgs['too_big']
                                       % dict (max_size = max_size_kb))))
        return (string, report)

    try:
        parsed = p.parseString(string)
    except DOMException,e:
        # yuck; xml.dom.DOMException can't give us line-information
        # directly, so we have to parse its error message string to
        # get it
        line = None
        line_match = error_message_extract_re.match(e.message)
        if line_match:
            line = line_match.group(1)
            if line:
                line = int(line)
        error_message=  (msgs['syntax_error']
                         % dict(syntaxerror = e.message))
        report.append(ValidationError(error_message,e,line))
        return (None,report)

    for rule in parsed.cssRules:
        if rule.type == CSSStyleRule.IMPORT_RULE:
            report.append(ValidationError(msgs['no_imports'],rule))
        elif rule.type == CSSStyleRule.COMMENT:
            pass
        elif rule.type == CSSStyleRule.STYLE_RULE:
            style = rule.style
            for prop in style.getProperties():

                if prop.cssValue.cssValueType == CSSValue.CSS_VALUE_LIST:
                    for i in range(prop.cssValue.length):
                        valid_value(prop,prop.cssValue.item(i),report)
                    if not (prop.cssValue.valid and prop.cssValue.wellformed):
                        report.append(ValidationError(msgs['invalid_property_list']
                                                      % dict(proplist = prop.cssText),
                                                      prop.cssValue))
                elif prop.cssValue.cssValueType == CSSValue.CSS_PRIMITIVE_VALUE:
                    valid_value(prop,prop.cssValue,report)

                # cssutils bug: because valid values might be marked
                # as invalid, we can't trust cssutils to properly
                # label valid properties, so we're going to rely on
                # the value validation (which will fail if the
                # property is invalid anyway). If this bug is fixed,
                # we should uncomment this 'if'

                # a property is not valid if any of its values are
                # invalid, or if it is itself invalid. To get the
                # best-quality error messages, we only report on
                # whether the property is valid after we've checked
                # the values
                #if not (prop.valid and prop.wellformed):
                #    report.append(ValidationError(_('invalid property'),prop))
            
        else:
            report.append(ValidationError(msgs['unknown_rule_type']
                                          % dict(ruletype = rule.cssText),
                                          rule))

    return parsed,report

def builder_wrapper(thing):
    if c.user.pref_compress and isinstance(thing, Link):
        thing.__class__ = LinkCompressed
        thing.score_fmt = Score.points
    return Wrapped(thing)

def find_preview_comments(sr):
    comments = Comment._query(Comment.c.sr_id == c.site._id,
                              limit=25, data=True)
    comments = list(comments)
    if not comments:
        comments = Comment._query(limit=25, data=True)
        comments = list(comments)

    return comments

def find_preview_links(sr):
    from r2.lib.normalized_hot import get_hot

    # try to find a link to use, otherwise give up and return
    links = get_hot(c.site)
    if not links:
        sr = Subreddit._by_name(g.default_sr)
        if sr:
            links = get_hot(sr)

    return links

def rendered_link(id, res, links, media, compress):
    from pylons.controllers.util import abort

    try:
        render_style    = c.render_style

        c.render_style = 'html'

        with c.user.safe_set_attr:
            c.user.pref_compress = compress
            c.user.pref_media    = media

            b = IDBuilder([l._fullname for l in links],
                          num = 1, wrap = builder_wrapper)
            l = LinkListing(b, nextprev=False,
                            show_nums=True).listing().render(style='html')
            res._update(id, innerHTML=l)

    finally:
        c.render_style = render_style

def rendered_comment(id, res, comments):
    try:
        render_style    = c.render_style

        c.render_style = 'html'

        b = IDBuilder([x._fullname for x in comments],
                      num = 1)
        l = LinkListing(b, nextprev=False,
                        show_nums=False).listing().render(style='html')
        res._update('preview_comment', innerHTML=l)

    finally:
        c.render_style = render_style

class BadImage(Exception): pass

def clean_image(data,format):
    import Image
    from StringIO import StringIO

    try:
        in_file = StringIO(data)
        out_file = StringIO()

        im = Image.open(in_file)
        im = im.resize(im.size)

        im.save(out_file,format)
        ret = out_file.getvalue()
    except IOError,e:
        raise BadImage(e)
    finally:
        out_file.close()
        in_file.close()

    return ret
    
def save_header_image(sr, data):
    import tempfile
    from r2.lib import s3cp
    from md5 import md5

    hash = md5(data).hexdigest()

    try:
        f = tempfile.NamedTemporaryFile(suffix = '.png')
        f.write(data)
        f.flush()

        resource = g.s3_thumb_bucket + sr._fullname + '.png'
        s3cp.send_file(f.name, resource, 'image/png', 'public-read', None, False)
    finally:
        f.close()

    return 'http:/%s%s.png?v=%s' % (g.s3_thumb_bucket, sr._fullname, hash)

 


