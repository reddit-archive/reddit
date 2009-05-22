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
from utils import to36, tup, iters
from wrapped import Wrapped
from mako.template import Template
from r2.lib.filters import spaceCompress, safemarkdown
import time, pytz
from pylons import c

def api_type(subtype = ''):
    return 'api-' + subtype if subtype else 'api'

def is_api(subtype = ''):
    return c.render_style and c.render_style.startswith(api_type(subtype))
    
def get_api_subtype():
    if is_api() and c.render_style.startswith('api-'):
        return c.render_style[4:]

def make_typename(typ):
    return 't%s' % to36(typ._type_id)

def make_fullname(typ, _id):
    return '%s_%s' % (make_typename(typ), to36(_id))

def mass_part_render(thing, **kw):
    return dict([(k, spaceCompress(thing.part_render(v)).strip(' ')) \
                 for k, v in kw.iteritems()])

class JsonTemplate(Template):
    def __init__(self): pass

    def render(self, thing = None, *a, **kw):
        return {}

class TableRowTemplate(JsonTemplate):
    def cells(self, thing):
        raise NotImplementedError
    
    def css_id(self, thing):
        return ""

    def css_class(self, thing):
        return ""

    def render(self, thing = None, *a, **kw):
        return {"id": self.css_id(thing),
                "css_class": self.css_class(thing),
                "cells": self.cells(thing)}

class UserItemJsonTemplate(TableRowTemplate):
    def cells(self, thing):
        cells = []
        for cell in thing.cells:
            r = Wrapped.part_render(thing, 'cell_type', cell)
            cells.append(spaceCompress(r))
        return cells

    def css_id(self, thing):
        return thing.user._fullname

    def css_class(self, thing):
        return "thing"


class ThingJsonTemplate(JsonTemplate):
    _data_attrs_ = dict(id           = "_id36",
                        name         = "_fullname",
                        created      = "created",
                        created_utc  = "created_utc")

    @classmethod
    def data_attrs(cls, **kw):
        d = cls._data_attrs_.copy()
        d.update(kw)
        return d
    
    def points(self, wrapped):
        """
        Generates the JS-style point triplet for votable elements
        (stored on the vl var on the JS side).
        """
        score = wrapped.score
        likes = wrapped.likes
        base_score = score-1 if likes else score if likes is None else score+1
        base_score = [base_score + x for x in range(-1, 2)]
        return [wrapped.score_fmt(s) for s in base_score]
        
    
    def kind(self, wrapped):
        """
        Returns a string literal which identifies the type of this
        thing.  For subclasses of Thing, it will be 't's + kind_id.
        """
        _thing = wrapped.lookups[0] if isinstance(wrapped, Wrapped) else wrapped
        return make_typename(_thing.__class__)

    def rendered_data(self, thing):
        """
        Called only when get_api_type is non-None (i.e., a JSON
        request has been made with partial rendering of the object to
        be returned)

        Canonical Thing data representation for JS, which is currently
        a dictionary of three elements (translated into a JS Object
        when sent out).  The elements are:

         * id : Thing _fullname of thing.
         * vl : triplet of scores (up, none, down) from self.score
         * content : rendered  representation of the thing by
           calling replace_render on it using the style of get_api_subtype().
        """
        from r2.lib.template_helpers import replace_render
        listing = thing.listing if hasattr(thing, "listing") else None
        return dict(id = thing._fullname,
                    #vl = self.points(thing),
                    content = spaceCompress(
                        replace_render(listing, thing,
                                       style=get_api_subtype())))

    def raw_data(self, thing):
        """
        Complement to rendered_data.  Called when a dictionary of
        thing data attributes is to be sent across the wire.
        """
        def strip_data(x):
            if isinstance(x, dict):
                return dict((k, strip_data(v)) for k, v in x.iteritems())
            elif isinstance(x, iters):
                return [strip_data(y) for y in x]
            elif isinstance(x, Wrapped):
                return x.render()
            else:
                return x
        
        return dict((k, strip_data(self.thing_attr(thing, v)))
                    for k, v in self._data_attrs_.iteritems())
            
    def thing_attr(self, thing, attr):
        """
        For the benefit of subclasses, to lookup attributes which may
        require more work than a simple getattr (for example, 'author'
        which has to be gotten from the author_id attribute on most
        things).
        """
        if attr == "author":
            return thing.author.name
        elif attr == "created":
            return time.mktime(thing._date.timetuple())
        elif attr == "created_utc":
            return time.mktime(thing._date.astimezone(pytz.UTC).timetuple())
        return getattr(thing, attr) if hasattr(thing, attr) else None

    def data(self, thing):
        if get_api_subtype():
            return self.rendered_data(thing)
        else:
            return self.raw_data(thing)
        
    def render(self, thing = None, action = None, *a, **kw):
        return dict(kind = self.kind(thing), data = self.data(thing))
        
class SubredditJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = ThingJsonTemplate.data_attrs(subscribers  = "score",
                                                title        = "title",
                                                url          = "path",
                                                description  = "description")

class LinkJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = ThingJsonTemplate.data_attrs(ups          = "upvotes",
                                                downs        = "downvotes",
                                                score        = "score",
                                                saved        = "saved",
                                                clicked      = "clicked",
                                                hidden       = "hidden",
                                                likes        = "likes",
                                                domain       = "domain",
                                                title        = "title",
                                                url          = "url",
                                                author       = "author", 
                                                thumbnail    = "thumbnail",
                                                media        = "media_object",
                                                num_comments = "num_comments",
                                                subreddit    = "subreddit",
                                                subreddit_id = "subreddit_id")
    
    def thing_attr(self, thing, attr):
        if attr == 'subreddit':
            return thing.subreddit.name
        elif attr == 'subreddit_id':
            return thing.subreddit._fullname
        return ThingJsonTemplate.thing_attr(self, thing, attr)
                          
    def rendered_data(self, thing):
        d = ThingJsonTemplate.rendered_data(self, thing)
        d['sr'] = thing.subreddit._fullname
        return d



class CommentJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = ThingJsonTemplate.data_attrs(ups          = "upvotes",
                                                downs        = "downvotes",
                                                replies      = "child",
                                                body         = "body",
                                                body_html    = "body_html",
                                                likes        = "likes",
                                                author       = "author", 
                                                link_id      = "link_id",
                                                parent_id    = "parent_id",
                                                )

    def thing_attr(self, thing, attr):
        from r2.models import Comment, Link
        if attr == 'link_id':
            return make_fullname(Link, thing.link_id)
        elif attr == "parent_id":
            try:
                return make_fullname(Comment, thing.parent_id)
            except AttributeError:
                return make_fullname(Link, thing.link_id)
        elif attr == "body_html":
            return safemarkdown(thing.body)
        return ThingJsonTemplate.thing_attr(self, thing, attr)

    def kind(self, wrapped):
        from r2.models import Comment
        return make_typename(Comment)

    def rendered_data(self, wrapped):
        from r2.models import Comment, Link
        try:
            parent_id = wrapped.parent_id
        except AttributeError:
            parent_id = make_fullname(Link, wrapped.link_id)
        else:
            parent_id = make_fullname(Comment, parent_id)
        d = ThingJsonTemplate.rendered_data(self, wrapped)
        d.update(mass_part_render(wrapped, contentHTML = 'commentBody',
                                  contentTxt = 'commentText'))
        d['parent'] = parent_id
        d['link'] = make_fullname(Link, wrapped.link_id)
        return d

class MoreCommentJsonTemplate(CommentJsonTemplate):
    _data_attrs_ = dict(id           = "_id36",
                        name         = "_fullname")
    def points(self, wrapped):
        return []

    def kind(self, wrapped):
        return "more"

class MessageJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = ThingJsonTemplate.data_attrs(new          = "new",
                                                subject      = "subject",
                                                body         = "body",
                                                body_html    = "body_html",
                                                author       = "author",
                                                dest         = "dest",
                                                was_comment  = "was_comment",
                                                context      = "context", 
                                                created      = "created")

    def thing_attr(self, thing, attr):
        if attr == "was_comment":
            return hasattr(thing, "was_comment")
        elif attr == "context":
            return ("" if not hasattr(thing, "was_comment")
                    else thing.permalink + "?context=3")
        elif attr == "dest":
            return thing.to.name
        elif attr == "body_html":
            return safemarkdown(thing.body)
        return ThingJsonTemplate.thing_attr(self, thing, attr)

    def rendered_data(self, wrapped):
        from r2.models import Message
        try:
            parent_id = wrapped.parent_id
        except AttributeError:
            parent_id = None
        else:
            parent_id = make_fullname(Message, parent_id)
        d = ThingJsonTemplate.rendered_data(self, wrapped)
        d['parent'] = parent_id
        return d


class RedditJsonTemplate(JsonTemplate):
    def render(self, thing = None, *a, **kw):
        return thing.content().render() if thing else {}

class PanestackJsonTemplate(JsonTemplate):
    def render(self, thing = None, *a, **kw):
        res = [t.render() for t in thing.stack if t] if thing else []
        res = [x for x in res if x]
        if not res:
            return {}
        return res if len(res) > 1 else res[0] 

class NullJsonTemplate(JsonTemplate):
    def render(self, thing = None, *a, **kw):
        return None

class ListingJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = dict(children = "things")
    
    def points(self, w):
        return []

    def rendered_data(self, thing):
        from r2.lib.template_helpers import replace_render
        res = []
        for a in thing.things:
            a.listing = thing
            r = replace_render(thing, a, style = 'api')
            if isinstance(r, str):
                r = spaceCompress(r)
            res.append(r)
        return res
    
    def kind(self, wrapped):
        return "Listing"

    def render(self, *a, **kw):
        res = ThingJsonTemplate.render(self, *a, **kw)
        return res

class OrganicListingJsonTemplate(ListingJsonTemplate):
    def kind(self, wrapped):
        return "OrganicListing"

class TrafficJsonTemplate(JsonTemplate):
    def render(self, thing, *a, **kw):
        res = {}
        for ival in ("hour", "day", "month"):
            if hasattr(thing, ival + "_data"):
                res[ival] = [[time.mktime(date.timetuple())] + list(data)
                             for date, data in getattr(thing, ival+"_data")]
        return res
