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
from r2.models import *
from filters import unsafe, websafe
from r2.lib.utils import vote_hash

from mako.filters import url_escape
import simplejson
import os.path
from copy import copy
from urlparse import urlparse, urlunparse

from pylons import i18n, g, c

def contextualize(func):
    def _contextualize(context, *a, **kw):
        return func(*a, **kw)
    return _contextualize

def print_context(context):
    print context.keys()
    return ''

def print_me(context, t):
    print t
    return ''

def static(file):
    # stip of "/static/" if already present
    fname = os.path.basename(file).split('?')[0]
    v = g.static_md5.get(fname, '')
    if v: v = "?v=" + v
    if os.path.dirname(file):
        return file + v
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
                    num_margin = "%5.2fex" % (len(str(listing.max_num))*1.1)
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
        if u'$votehash' in rendered_item:
            hash = vote_hash(c.user, item, listing.vote_hash_type)
            rendered_item = replace_fn(u'$votehash', hash)
            
    rendered_item = replace_fn(u"$display", "" if display else "style='display:none'")
    return rendered_item

from pylons import c as cur
def dockletStr(context, type, browser):
    if type == "serendipity!":
        return "http://"+cur.domain+"/random"
    elif type == "reddit":
        return "javascript:location.href='http://"+cur.domain+"/submit?url='+encodeURIComponent(location.href)+'&title='+encodeURIComponent(document.title)"
    else:
        f = "fixed"
        if browser == "ie": f = "absolute"
        return "javascript:function b(){var u=encodeURIComponent(location.href);var i=document.getElementById('redstat')||document.createElement('a');var s=i.style;s.position='%s';s.top='0';s.left='0';s.zIndex='10002';i.id='redstat';i.href='http://%s/submit?url='+u+'&title='+encodeURIComponent(document.title);var q=i.firstChild||document.createElement('img');q.src='http://%s/d/%s'+Math.random()+'?uh=%s&u='+u;i.appendChild(q);document.body.appendChild(i)};b()" % \
            (f, cur.domain, cur.domain, type, 
             c.modhash if cur.user else '')



def reddit_link(path, url = False, get = False):
    if url or get:
        (scheme, netloc, path, params, query, fragment) = urlparse(path)
        if url:
            #noslash fixes /reddits/
            noslash = c.site.path.rstrip('/')
            #if it's a relative path, don't include the sitename
            if path.startswith('/') and not path.startswith(noslash):
                path = c.site.path + path[1:]
        else:
            newparam = "r=" + url_escape(c.site.name)
            if query:
                query += "&" + newparam
            else:
                query = newparam
        return urlunparse((scheme, netloc, path, params, query, fragment))
    return path

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
