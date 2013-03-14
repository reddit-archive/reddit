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

from __future__ import with_statement

from r2.models import *
from r2.lib.utils import sanitize_url, strip_www, randstr
from r2.lib.strings import string_dict
from r2.lib.pages.things import wrap_links

from pylons import g, c
from pylons.i18n import _
from mako import filters

import os
import tempfile
from r2.lib import s3cp

from r2.lib.media import upload_media

from r2.lib.template_helpers import s3_https_if_secure

import re
from urlparse import urlparse

import cssutils
from cssutils import CSSParser
from cssutils.css import CSSStyleRule
from cssutils.css import CSSValue, CSSValueList
from cssutils.css import CSSPrimitiveValue
from cssutils.css import cssproperties
from xml.dom import DOMException

msgs = string_dict['css_validator_messages']

browser_prefixes = ['o','moz','webkit','ms','khtml','apple','xv']

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

    'bg-gradient': r'none|{color}|[a-z-]*-gradient\([^;]*\)',
    'bg-gradients': r'{bg-gradient}(?:,\s*{bg-gradient})*',

    'border-radius': r'(({length}|{percentage}){w}){1,2}',
    
    'single-text-shadow': r'({color}\s+)?{length}\s+{length}(\s+{length})?|{length}\s+{length}(\s+{length})?(\s+{color})?',

    'box-shadow-pos': r'{length}\s+{length}(\s+{length})?(\s+{length})?',
}

custom_values = {
    '_height': r'{length}|{percentage}|auto|inherit',
    '_width': r'{length}|{percentage}|auto|inherit',
    '_overflow': r'visible|hidden|scroll|auto|inherit',
    'color': r'{color}',
    'border-color': r'{color}',
    'opacity': r'^0?\.?[0-9]*|1\.0*|1|0',
    'filter': r'alpha\(opacity={num}\)',
    
    'background': r'{bg-gradients}',
    'background-image': r'{bg-gradients}',
    'background-color': r'{color}',
    'background-position': r'(({percentage}|{length}){0,3})?\s*(top|center|left)?\s*(left|center|right)?',
    
    # http://www.w3.org/TR/css3-background/#border-top-right-radius
    'border-radius': r'{border-radius}',
    'border-top-right-radius': r'{border-radius}',
    'border-bottom-right-radius': r'{border-radius}',
    'border-bottom-left-radius': r'{border-radius}',
    'border-top-left-radius': r'{border-radius}',

    # old mozilla style (for compatibility with existing stylesheets)
    'border-radius-topright': r'{border-radius}',
    'border-radius-bottomright': r'{border-radius}',
    'border-radius-bottomleft': r'{border-radius}',
    'border-radius-topleft': r'{border-radius}',
    
    # http://www.w3.org/TR/css3-text/#text-shadow
    'text-shadow': r'none|({single-text-shadow}{w},{w})*{single-text-shadow}',
    
    # http://www.w3.org/TR/css3-background/#the-box-shadow
    # (This description doesn't support multiple shadows)
    'box-shadow': 'none|(?:({box-shadow-pos}\s+)?{color}|({color}\s+?){box-shadow-pos})',
}

def _build_regex_prefix(prefixes):
    return re.compile("|".join("^-"+p+"-" for p in prefixes))

prefix_regex = _build_regex_prefix(browser_prefixes)

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

def legacy_s3_url(url, site):
    if isinstance(url, int): # legacy url, needs to be generated
        bucket = g.s3_old_thumb_bucket
        baseurl = "http://%s" % (bucket)
        if g.s3_media_direct:
            baseurl = "http://%s/%s" % (s3_direct_url, bucket)
        url = "%s/%s_%d.png"\
                % (baseurl, site._fullname, url)
    url = s3_https_if_secure(url)
    return url

# local urls should be in the static directory
local_urls = re.compile(r'\A/static/[a-z./-]+\Z')
# substitutable urls will be css-valid labels surrounded by "%%"
custom_img_urls = re.compile(r'%%([a-zA-Z0-9\-]+)%%')
valid_url_schemes = ('http', 'https')
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
            url = c.site.images[name]
            url = legacy_s3_url(url, c.site)
            value._setCssText("url(%s)"%url)
        else:
            # unknown image label -> error
            report.append(ValidationError(msgs['broken_url']
                                          % dict(brokenurl = value.cssText),
                                          value))
    else:
        try:
            u = urlparse(url)
            valid_scheme = u.scheme and u.scheme in valid_url_schemes
            valid_domain = u.netloc in g.allowed_css_linked_domains
        except ValueError:
            u = False

        # allowed domains are ok
        if not (u and valid_scheme and valid_domain):
            report.append(ValidationError(msgs['broken_url']
                                          % dict(brokenurl = value.cssText),
                                          value))
    #elif sanitize_url(url) != url:
    #    report.append(ValidationError(msgs['broken_url']
    #                                  % dict(brokenurl = value.cssText),
    #                                  value))


def strip_browser_prefix(prop):
    t = prefix_regex.split(prop, maxsplit=1)
    return t[len(t) - 1]

def valid_value(prop,value,report):
    prop_name = strip_browser_prefix(prop.name) # Remove browser-specific prefixes eg: -moz-border-radius becomes border-radius
    if not (value.valid and value.wellformed):
        if (value.wellformed
            and prop_name in cssproperties.cssvalues
            and cssproperties.cssvalues[prop_name](prop.value)):
            # it's actually valid. cssutils bug.
            pass
        elif (not value.valid
              and value.wellformed
              and prop_name in custom_values
              and custom_values[prop_name](prop.value)):
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
        elif not (prop_name in cssproperties.cssvalues or prop_name in custom_values):
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
        return ('', report)

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
    from r2.lib.db.queries import get_sr_comments, get_all_comments

    comments = get_sr_comments(c.site)
    comments = list(comments)
    if not comments:
        comments = get_all_comments()
        comments = list(comments)

    return Thing._by_fullname(comments[:25], data=True, return_dict=False)

def find_preview_links(sr):
    from r2.lib.normalized_hot import get_hot

    # try to find a link to use, otherwise give up and return
    links = get_hot([c.site])
    if not links:
        links = get_hot(Subreddit.default_subreddits(ids=False))

    if links:
        links = links[:25]
        links = Link._by_fullname(links, data=True, return_dict=False)

    return links

def rendered_link(links, media, compress):
    with c.user.safe_set_attr:
        c.user.pref_compress = compress
        c.user.pref_media    = media
    links = wrap_links(links, show_nums = True, num = 1)
    delattr(c.user, 'pref_compress')
    delattr(c.user, 'pref_media') 
    return links.render(style = "html")

def rendered_comment(comments):
    return wrap_links(comments, num = 1).render(style = "html")

class BadImage(Exception):
    def __init__(self, error = None):
        self.error = error

def save_sr_image(sr, data, suffix = '.png'):
    try:
        return upload_media(data, file_type = suffix)
    except Exception as e:
        raise BadImage(e)

