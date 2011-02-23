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
from __future__ import with_statement

from r2.models import *
from r2.lib.utils import sanitize_url, domain, randstr
from r2.lib.strings import string_dict
from r2.lib.pages.things import wrap_links

from pylons import g, c
from pylons.i18n import _
from mako import filters

import os
import tempfile
from r2.lib import s3cp
from md5 import md5
from r2.lib.contrib.nymph import optimize_png

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
    'int': r'[-]?\d+',
    'w': r'\s*',
    
    # From: http://www.w3.org/TR/2008/WD-css3-color-20080721/#svg-color
    'x11color': r'aliceblue|antiquewhite|aqua|aquamarine|azure|beige|bisque|black|blanchedalmond|blue|blueviolet|brown|burlywood|cadetblue|chartreuse|chocolate|coral|cornflowerblue|cornsilk|crimson|cyan|darkblue|darkcyan|darkgoldenrod|darkgray|darkgreen|darkgrey|darkkhaki|darkmagenta|darkolivegreen|darkorange|darkorchid|darkred|darksalmon|darkseagreen|darkslateblue|darkslategray|darkslategrey|darkturquoise|darkviolet|deeppink|deepskyblue|dimgray|dimgrey|dodgerblue|firebrick|floralwhite|forestgreen|fuchsia|gainsboro|ghostwhite|gold|goldenrod|gray|green|greenyellow|grey|honeydew|hotpink|indianred|indigo|ivory|khaki|lavender|lavenderblush|lawngreen|lemonchiffon|lightblue|lightcoral|lightcyan|lightgoldenrodyellow|lightgray|lightgreen|lightgrey|lightpink|lightsalmon|lightseagreen|lightskyblue|lightslategray|lightslategrey|lightsteelblue|lightyellow|lime|limegreen|linen|magenta|maroon|mediumaquamarine|mediumblue|mediumorchid|mediumpurple|mediumseagreen|mediumslateblue|mediumspringgreen|mediumturquoise|mediumvioletred|midnightblue|mintcream|mistyrose|moccasin|navajowhite|navy|oldlace|olive|olivedrab|orange|orangered|orchid|palegoldenrod|palegreen|paleturquoise|palevioletred|papayawhip|peachpuff|peru|pink|plum|powderblue|purple|red|rosybrown|royalblue|saddlebrown|salmon|sandybrown|seagreen|seashell|sienna|silver|skyblue|slateblue|slategray|slategrey|snow|springgreen|steelblue|tan|teal|thistle|tomato|turquoise|violet|wheat|white|whitesmoke|yellow|yellowgreen',
    'csscolor': r'(maroon|red|orange|yellow|olive|purple|fuchsia|white|lime|green|navy|blue|aqua|teal|black|silver|gray|ActiveBorder|ActiveCaption|AppWorkspace|Background|ButtonFace|ButtonHighlight|ButtonShadow|ButtonText|CaptionText|GrayText|Highlight|HighlightText|InactiveBorder|InactiveCaption|InactiveCaptionText|InfoBackground|InfoText|Menu|MenuText|Scrollbar|ThreeDDarkShadow|ThreeDFace|ThreeDHighlight|ThreeDLightShadow|ThreeDShadow|Window|WindowFrame|WindowText)|#[0-9a-f]{3}|#[0-9a-f]{6}|rgb\({w}{int}{w},{w}{int}{w},{w}{int}{w}\)|rgb\({w}{num}%{w},{w}{num}%{w},{w}{num}%{w}\)',
    'color': '{x11color}|{csscolor}',
    
    'single-text-shadow': r'({color}\s+)?{length}\s+{length}(\s+{length})?|{length}\s+{length}(\s+{length})?(\s+{color})?',

    'box-shadow-pos': r'{length}\s+{length}(\s+{length})?',
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

nonstandard_values = {
    # http://www.w3.org/TR/css3-background/#border-top-right-radius
    '-moz-border-radius': r'(({length}|{percentage}){w}){1,2}',
    '-moz-border-radius-topleft': r'(({length}|{percentage}){w}){1,2}',
    '-moz-border-radius-topright': r'(({length}|{percentage}){w}){1,2}',
    '-moz-border-radius-bottomleft': r'(({length}|{percentage}){w}){1,2}',
    '-moz-border-radius-bottomright': r'(({length}|{percentage}){w}){1,2}',
    '-webkit-border-radius': r'(({length}|{percentage}){w}){1,2}',
    '-webkit-border-top-left-radius': r'(({length}|{percentage}){w}){1,2}',
    '-webkit-border-top-right-radius': r'(({length}|{percentage}){w}){1,2}',
    '-webkit-border-bottom-left-radius': r'(({length}|{percentage}){w}){1,2}',
    '-webkit-border-bottom-right-radius': r'(({length}|{percentage}){w}){1,2}',
    'border-radius': r'(({length}|{percentage}){w}){1,2}',
    'border-radius-topleft': r'(({length}|{percentage}){w}){1,2}',
    'border-radius-topright': r'(({length}|{percentage}){w}){1,2}',
    'border-radius-bottomleft': r'(({length}|{percentage}){w}){1,2}',
    'border-radius-bottomright': r'(({length}|{percentage}){w}){1,2}',
    
    # http://www.w3.org/TR/css3-text/#text-shadow
    'text-shadow': r'none|({single-text-shadow}{w},{w})*{single-text-shadow}',
    
    # http://www.w3.org/TR/css3-background/#the-box-shadow
    # (This description doesn't support multiple shadows)
    'box-shadow': 'none|(?:({box-shadow-pos}\s+)?{color}|({color}\s+?){box-shadow-pos})',
}
custom_values.update(nonstandard_values);

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
        tokdict[key] = re.compile('\A(?:%s)\Z' % value, re.I).match
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

# local urls should be in the static directory
local_urls = re.compile(r'\A/static/[a-z./-]+\Z')
# substitutable urls will be css-valid labels surrounded by "%%"
custom_img_urls = re.compile(r'%%([a-zA-Z0-9\-]+)%%')
def valid_url(prop,value,report):
    """
    checks url(...) arguments in CSS, ensuring that the contents are
    officially sanctioned.  Sanctioned urls include:
     * anything in /static/
     * image labels %%..%% for images uploaded on /about/stylesheet
     * urls with domains in g.allowed_css_linked_domains
    """
    try:
        url = value.getStringValue()
    except IndexError:
        g.log.error("Problem validating [%r]" % value)
        raise
    # local urls are allowed
    if local_urls.match(url):
        t_url = None
        while url != t_url:
            t_url, url = url, filters.url_unescape(url)
        # disallow path trickery
        if "../" in url:
            report.append(ValidationError(msgs['broken_url']
                                          % dict(brokenurl = value.cssText),
                                          value))
    # custom urls are allowed, but need to be transformed into a real path
    elif custom_img_urls.match(url):
        name = custom_img_urls.match(url).group(1)
        # the label -> image number lookup is stored on the subreddit
        if c.site.images.has_key(name):
            num = c.site.images[name]
            value._setCssText("url(http://%s/%s_%d.png?v=%s)"
                              % (g.s3_thumb_bucket, c.site._fullname, num,
                                 randstr(36)))
        else:
            # unknown image label -> error
            report.append(ValidationError(msgs['broken_url']
                                          % dict(brokenurl = value.cssText),
                                          value))
    # allowed domains are ok
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

error_message_extract_re = re.compile('.*\\[([0-9]+):[0-9]*:.*\\]\Z')
only_whitespace          = re.compile('\A\s*\Z')
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

    if '\\' in string:
        report.append(ValidationError(_("if you need backslashes, you're doing it wrong")))

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
    links = get_hot([c.site])
    if not links:
        sr = Subreddit._by_name(g.default_sr)
        if sr:
            links = get_hot([sr])

    if links:
        links = links[:25]
        links = Link._by_fullname(links, data=True, return_dict=False)

    return links

def rendered_link(links, media, compress):
    with c.user.safe_set_attr:
        c.user.pref_compress = compress
        c.user.pref_media    = media
        links = wrap_links(links, show_nums = True, num = 1)
        return links.render(style = "html")

def rendered_comment(comments):
    return wrap_links(comments, num = 1).render(style = "html")

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
    
def save_sr_image(sr, data, resource = None):
    """
    uploades image data to s3 as a PNG and returns its new url.  Urls
    will be of the form:
      http://${g.s3_thumb_bucket}/${sr._fullname}[_${num}].png?v=${md5hash}
    [Note: g.s3_thumb_bucket begins with a "/" so the above url is valid.]
    """
    hash = md5(data).hexdigest()

    f = tempfile.NamedTemporaryFile(suffix = '.png',delete=False)
    try:
        f.write(data)
        f.close()

        optimize_png(f.name, g.png_optimizer)
        contents = open(f.name).read()

        if resource is not None:
            resource = "_%s" % resource
        else:
            resource = ""
        fname = resource = sr._fullname + resource + ".png"

        s3cp.send_file(g.s3_thumb_bucket, fname, contents, 'image/png')

    finally:
        os.unlink(f.name)

    return 'http://%s/%s?v=%s' % (g.s3_thumb_bucket, 
                                  resource.split('/')[-1], hash)

 


