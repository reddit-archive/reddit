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
from r2.models import *
from filters import unsafe, websafe
from r2.lib.utils import vote_hash, UrlParser

from mako.filters import url_escape
import simplejson
import os.path
from copy import copy
import random
from pylons import i18n, g, c

def static(file):
    """
    Simple static file maintainer which automatically paths and
    versions files being served out of static.

    In the case of JS and CSS where g.uncompressedJS is set, the
    version of the file is set to be random to prevent caching and it
    mangles the path to point to the uncompressed versions.
    """
    
    # stip of "/static/" if already present
    fname = os.path.basename(file).split('?')[0]
    # if uncompressed, we are in devel mode so randomize the hash
    if g.uncompressedJS:
        v = str(random.random()).split(".")[-1]
    else:
        v = g.static_md5.get(fname, '')
    if v: v = "?v=" + v
    # don't mangle paths
    if os.path.dirname(file):
        return file + v

    if g.uncompressedJS:
        extension = file.split(".")[1:]
        if extension and extension[-1] in ("js", "css"):
            return os.path.join(c.site.static_path, extension[-1], file) + v
        
    return os.path.join(c.site.static_path, file) + v

def generateurl(context, path, **kw):
    if kw:
        return path + '?' + '&'.join(["%s=%s"%(k, url_escape(v)) \
                                      for k, v in kw.iteritems() if v])
    return path

def class_dict():
    t_cls = [Link, Comment, Message, Subreddit]
    l_cls = [Listing, OrganicListing]

    classes  = [('%s: %s') % ('t'+ str(cl._type_id), cl.__name__ ) for cl in t_cls] \
             + [('%s: %s') % (cl.__name__, cl._js_cls) for cl in l_cls]

    res = ', '.join(classes)
    return unsafe('{ %s }' % res)


def path_info():
    loc = dict(path = request.path,
               params = dict(request.get))
    
    return unsafe(simplejson.dumps(loc))
    

def replace_render(listing, item, style = None, display = True):
    style = style or c.render_style or 'html'
    rendered_item = item.render(style = style)

    # for string rendered items
    def string_replace(x, y):
        return rendered_item.replace(x, y)

    # for JSON responses
    def dict_replace(x, y):
        try:
            res = rendered_item['data']['content']
            rendered_item['data']['content'] = res.replace(x, y)
        except AttributeError:
            pass
        except TypeError:
            pass
        return rendered_item

    child_txt = ( hasattr(item, "child") and item.child )\
        and item.child.render(style = style) or ""

    # handle API calls differently from normal request: dicts not strings are passed around
    if isinstance(rendered_item, dict):
        replace_fn = dict_replace
        try:
            rendered_item['data']['child'] = child_txt
        except AttributeError:
            pass
        except TypeError:
            pass
    else:
        replace_fn = string_replace
        rendered_item = replace_fn(u"$child", child_txt)

    #only LinkListing has a show_nums attribute
    if listing: 
        if hasattr(listing, "show_nums"):
            if listing.show_nums:
                num_str = str(item.num) 
                if hasattr(listing, "num_margin"):
                    num_margin = listing.num_margin
                else:
                    num_margin = "%.2fex" % (len(str(listing.max_num))*1.1)
            else:
                num_str = ''
                num_margin = "0px"
    
            rendered_item = replace_fn(u"$numcolmargin", num_margin)
            rendered_item = replace_fn(u"$num", num_str)

        if hasattr(listing, "max_score"):
            mid_margin = len(str(listing.max_score)) 
            if hasattr(listing, "mid_margin"):
                mid_margin = listing.mid_margin
            elif mid_margin == 1:
                mid_margin = "15px"
            else:
                mid_margin = "%dex" % (mid_margin+1)

            rendered_item = replace_fn(u"$midcolmargin", mid_margin)

        # TODO: one of these things is not like the other.  We should & ->
        # $ elsewhere as it plays nicer with the websafe filter.
        rendered_item = replace_fn(u"$ListClass", listing._js_cls)

        #$votehash is only present when voting arrows are present
        if c.user_is_loggedin and u'$votehash' in rendered_item:
            hash = vote_hash(c.user, item, listing.vote_hash_type)
            rendered_item = replace_fn(u'$votehash', hash)
            
    rendered_item = replace_fn(u"$display", "" if display else "style='display:none'")
    return rendered_item

def get_domain(cname = False, subreddit = True, no_www = False):
    """
    returns the domain on the current subreddit, possibly including
    the subreddit part of the path, suitable for insertion after an
    "http://" and before a fullpath (i.e., something including the
    first '/') in a template.  The domain is updated to include the
    current port (request.port).  The effect of the arguments is:

     * no_www: if the domain ends up being g.domain, the default
       behavior is to prepend "www." to the front of it (for akamai).
       This flag will optionally disable it.

     * cname: whether to respect the value of c.cname and return
       c.site.domain rather than g.domain as the host name.

     * subreddit: if a cname is not used in the resulting path, flags
       whether or not to append to the domain the subreddit path (sans
       the trailing path).

    """
    domain = g.domain
    if not no_www and g.domain_prefix:
        domain = g.domain_prefix + "." + g.domain
    if cname and c.cname and c.site.domain:
        domain = c.site.domain
    if hasattr(request, "port") and request.port:
        domain += ":" + str(request.port)
    if (not c.cname or not cname) and subreddit:
        domain += c.site.path.rstrip('/')
    return domain

def dockletStr(context, type, browser):
    domain      = get_domain()

    # while site_domain will hold the (possibly) cnamed version
    site_domain = get_domain(True)

    if type == "serendipity!":
        return "http://"+site_domain+"/random"
    elif type == "reddit":
        return "javascript:location.href='http://"+site_domain+"/submit?url='+encodeURIComponent(location.href)+'&title='+encodeURIComponent(document.title)"
    else:
        return (("javascript:function b(){var u=encodeURIComponent(location.href);"
                 "var i=document.getElementById('redstat')||document.createElement('a');"
                 "var s=i.style;s.position='%(position)s';s.top='0';s.left='0';"
                 "s.zIndex='10002';i.id='redstat';"
                 "i.href='http://%(site_domain)s/submit?url='+u+'&title='+"
                 "encodeURIComponent(document.title);"
                 "var q=i.firstChild||document.createElement('img');"
                 "q.src='http://%(domain)s/d/%(type)s.png?v='+Math.random()+'&uh=%(modhash)s&u='+u;"
                 "i.appendChild(q);document.body.appendChild(i)};b()") %
                dict(position = "absolute" if browser == "ie" else "fixed",
                     domain = domain, site_domain = site_domain, type = type,
                     modhash = c.modhash if c.user else ''))



def add_sr(path, sr_path = True, nocname=False, force_hostname = False):
    """
    Given a path (which may be a full-fledged url or a relative path),
    parses the path and updates it to include the subreddit path
    according to the rules set by its arguments:

     * force_hostname: if True, force the url's hotname to be updated
       even if it is already set in the path, and subject to the
       c.cname/nocname combination.  If false, the path will still
       have its domain updated if no hostname is specified in the url.
    
     * nocname: when updating the hostname, overrides the value of
       c.cname to set the hotname to g.domain.  The default behavior
       is to set the hostname consistent with c.cname.

     * sr_path: if a cname is not used for the domain, updates the
       path to include c.site.path.
    """
    u = UrlParser(path)
    if sr_path and (nocname or not c.cname):
        u.path_add_subreddit(c.site)

    if not u.hostname or force_hostname:
        u.hostname = get_domain(cname = (c.cname and not nocname),
                                subreddit = False)

    if c.render_style == 'mobile':
        u.set_extension('mobile')

    return u.unparse()

def join_urls(*urls):
    """joins a series of urls together without doubles slashes"""
    if not urls:
        return
    
    url = urls[0]
    for u in urls[1:]:
        if not url.endswith('/'):
            url += '/'
        while u.startswith('/'):
            u = utils.lstrips(u, '/')
        url += u
    return url

def style_line(button_width = None, bgcolor = "", bordercolor = ""):
    style_line = ''
    bordercolor = c.bordercolor or bordercolor
    bgcolor     = c.bgcolor or bgcolor
    if bgcolor:
        style_line += "background-color: #%s;" % bgcolor
    if bordercolor:
        style_line += "border: 1px solid #%s;" % bordercolor
    if button_width:
        style_line += "width: %spx;" % button_width
    return style_line

def choose_width(link, width):
    if width:
        return width - 5
    else:
        if link:
            return 100 + (10 * (len(str(link._ups - link._downs))))
        else:
            return 110
