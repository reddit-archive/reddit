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
from account import *
from link import *
from vote import *
from report import *
from pylons import i18n, request, g

from r2.lib.wrapped import Wrapped
from r2.lib import utils
from r2.lib.db import operators
from r2.lib.cache import sgm

from copy import deepcopy, copy

class Listing(object):
    # class used in Javascript to manage these objects
    _js_cls = "Listing"

    def __init__(self, builder, nextprev = True, next_link = True,
                 prev_link = True, vote_hash_type = 'valid', **kw):
        self.builder = builder
        self.nextprev = nextprev
        self.next_link = True
        self.prev_link = True
        self.next = None
        self.prev = None
        self.max_num = 1
        self.vote_hash_type = vote_hash_type

    @property
    def max_score(self):
        scores = [x.score for x in self.things if hasattr(x, 'score')]
        return max(scores) if scores else 0

    def get_items(self, *a, **kw):
        """Wrapper around builder's get_items that caches the rendering."""
        builder_items = self.builder.get_items(*a, **kw)

        #render cache
        #fn to render non-boring items
        fullnames = {}
        for i in self.builder.item_iter(builder_items):
            rs = c.render_style
            key = i.cache_key(i)
            if key:
                fullnames[key + rs + c.lang] = i

        def render_items(names):
            r = {}
            for i in names:
                item = fullnames[i]
                r[i] = item.render()
            return r

        rendered_items = sgm(cache, fullnames, render_items, 'render_',
                             time = g.page_cache_time)

        #replace the render function
        for k, v in rendered_items.iteritems():
            def make_fn(v):
                default = c.render_style
                default_render = fullnames[k].render
                def r(style = default):
                    if style != c.render_style:
                        return default_render(style = style)
                    return v
                return r
            fullnames[k].render = make_fn(v)
        
        return builder_items

    def listing(self):
        self.things, prev, next, bcount, acount = self.get_items()

        self.max_num = max(acount, bcount)

        if self.nextprev and self.prev_link and prev and bcount > 1:
            p = request.get.copy()
            p.update({'after':None, 'before':prev._fullname, 'count':bcount})
            self.prev = (request.path + utils.query_string(p))
        if self.nextprev and self.next_link and next:
            p = request.get.copy()
            p.update({'after':next._fullname, 'before':None, 'count':acount})
            self.next = (request.path + utils.query_string(p))
        #TODO: need name for template -- must be better way
        return Wrapped(self)

class LinkListing(Listing):
    def __init__(self, *a, **kw):
        Listing.__init__(self, *a, **kw)

        self.show_nums = kw.get('show_nums', False)

class NestedListing(Listing):
    def __init__(self, *a, **kw):
        Listing.__init__(self, *a, **kw)

        self.nested = kw.get('nested', True)
        self.num = kw.get('num', g.num_comments)
        self.parent_name = kw.get('parent_name')
        
    def listing(self):
        ##TODO use the local builder with the render cache. this may
        ##require separating the builder's get_items and tree-building
        ##functionality
        wrapped_items = self.get_items(num = self.num, nested = True)

        self.things = wrapped_items

        #make into a tree thing
        return Wrapped(self)

class OrganicListing(Listing):
    # class used in Javascript to manage these objects
    _js_cls = "OrganicListing"

    def __init__(self, *a, **kw):
        kw['vote_hash_type'] = kw.get('vote_hash_type', 'organic')
        Listing.__init__(self, *a, **kw)
        self.nextprev   = False
        self.show_nums  = True
        self._max_num   = kw.get('max_num', 0)
        self._max_score = kw.get('max_score', 0)
        self.org_links  = kw.get('org_links', [])
        self.visible_link = kw.get('visible_link', '')

    @property
    def max_score(self):
        return self._max_score
    
    def listing(self):
        res = Listing.listing(self)
        # override score fields
        res.max_num = self._max_num
        res.max_score = self._max_score
        for t in res.things:
            t.num = ""
        return res
