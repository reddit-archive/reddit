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
from utils import to36, tup, iters
from wrapped import Wrapped, StringTemplate, CacheStub, CachedVariable, Templated
from mako.template import Template
from r2.lib.filters import spaceCompress, safemarkdown
import time, pytz
from pylons import c, g
from pylons.i18n import _

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


class ObjectTemplate(StringTemplate):
    def __init__(self, d):
        self.d = d

    def update(self, kw):
        def _update(obj):
            if isinstance(obj, (str, unicode)):
                return StringTemplate(obj).finalize(kw)
            elif isinstance(obj, dict):
                return dict((k, _update(v)) for k, v in obj.iteritems())
            elif isinstance(obj, (list, tuple)):
                return map(_update, obj)
            elif isinstance(obj, CacheStub) and kw.has_key(obj.name):
                return kw[obj.name]
            else:
                return obj
        res = _update(self.d)
        return ObjectTemplate(res)

    def finalize(self, kw = {}):
        return self.update(kw).d
    
class JsonTemplate(Template):
    def __init__(self): pass

    def render(self, thing = None, *a, **kw):
        return ObjectTemplate({})

class TakedownJsonTemplate(JsonTemplate):
    def render(self, thing = None, *a, **kw):
        return thing.explanation

class TableRowTemplate(JsonTemplate):
    def cells(self, thing):
        raise NotImplementedError
    
    def css_id(self, thing):
        return ""

    def css_class(self, thing):
        return ""

    def render(self, thing = None, *a, **kw):
        return ObjectTemplate(dict(id = self.css_id(thing),
                                   css_class = self.css_class(thing),
                                   cells = self.cells(thing)))

class UserItemHTMLJsonTemplate(TableRowTemplate):
    def cells(self, thing):
        cells = []
        for cell in thing.cells:
            thing.name = cell
            r = thing.part_render('cell_type', style = "html")
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
         * content : rendered  representation of the thing by
           calling render on it using the style of get_api_subtype().
        """
        res =  dict(id = thing._fullname,
                    content = thing.render(style=get_api_subtype()))
        return res
        
    def raw_data(self, thing):
        """
        Complement to rendered_data.  Called when a dictionary of
        thing data attributes is to be sent across the wire.
        """
        return dict((k, self.thing_attr(thing, v))
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
        if attr == "author_flair_text":
            if thing.author.flair_enabled_in_sr(thing.subreddit._id):
                return getattr(thing.author,
                               'flair_%s_text' % (thing.subreddit._id),
                               None)
            else:
                return None
        if attr == "author_flair_css_class":
            if thing.author.flair_enabled_in_sr(thing.subreddit._id):
                return getattr(thing.author,
                               'flair_%s_css_class' % (thing.subreddit._id),
                               None)
            else:
                return None
        elif attr == "created":
            return time.mktime(thing._date.timetuple())
        elif attr == "created_utc":
            return (time.mktime(thing._date.astimezone(pytz.UTC).timetuple())
                    - time.timezone)
        elif attr == "child":
            return CachedVariable("childlisting")

        if attr in ["num_reports", "banned_by", "approved_by"]:
            if c.user_is_loggedin and thing.subreddit.is_moderator(c.user):
                if attr == "num_reports":
                    return thing.reported
                ban_info = getattr(thing, "ban_info", {})
                if attr == "banned_by":
                    return ban_info.get("banner") if ban_info.get('moderator_banned') else True
                elif attr == "approved_by":
                    return ban_info.get("unbanner")

        return getattr(thing, attr, None)

    def data(self, thing):
        if get_api_subtype():
            return self.rendered_data(thing)
        else:
            return self.raw_data(thing)

    def render(self, thing = None, action = None, *a, **kw):
        return ObjectTemplate(dict(kind = self.kind(thing),
                                   data = self.data(thing)))

class SubredditJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = ThingJsonTemplate.data_attrs(subscribers  = "_ups",
                                                title        = "title",
                                                url          = "path",
                                                over18       = "over_18",
                                                description  = "description",
                                                display_name = "name",
                                                header_img   = "header",
                                                header_size  = "header_size",
                                                header_title = "header_title")

    def thing_attr(self, thing, attr):
        # Don't reveal revenue information via /r/lounge's subscribers
        if (attr == "_ups" and g.lounge_reddit
            and thing.name == g.lounge_reddit):
            return 0
        else:
            return ThingJsonTemplate.thing_attr(self, thing, attr)

class IdentityJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = ThingJsonTemplate.data_attrs(name = "name",
                                                link_karma = "safe_karma",
                                                comment_karma = "comment_karma",
                                                is_gold = "gold"
                                                )

class AccountJsonTemplate(IdentityJsonTemplate):
    _data_attrs_ = IdentityJsonTemplate.data_attrs(has_mail = "has_mail",
                                                  has_mod_mail = "has_mod_mail",
                                                  is_mod = "is_mod",
                                                  )

    def thing_attr(self, thing, attr):
        from r2.models import Subreddit
        if attr == "has_mail":
            if c.user_is_loggedin and thing._id == c.user._id:
                return bool(c.have_messages)
            return None
        if attr == "has_mod_mail":
            if c.user_is_loggedin and thing._id == c.user._id:
                return bool(c.have_mod_messages)
            return None
        if attr == "is_mod":
            return bool(Subreddit.reverse_moderator_ids(thing))
        return ThingJsonTemplate.thing_attr(self, thing, attr)

    def raw_data(self, thing):
        data = ThingJsonTemplate.raw_data(self, thing)
        if c.user_is_loggedin and thing._id == c.user._id:
            data["modhash"] = c.modhash
        return data

class LinkJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = ThingJsonTemplate.data_attrs(ups          = "upvotes",
                                                downs        = "downvotes",
                                                score        = "score",
                                                saved        = "saved",
                                                clicked      = "clicked",
                                                hidden       = "hidden",
                                                over_18      = "over_18",
                                                likes        = "likes",
                                                domain       = "domain",
                                                title        = "title",
                                                url          = "url",
                                                author       = "author",
                                                author_flair_text =
                                                    "author_flair_text",
                                                author_flair_css_class =
                                                    "author_flair_css_class",
                                                thumbnail    = "thumbnail",
                                                media        = "media_object",
                                                media_embed  = "media_embed",
                                                selftext     = "selftext",
                                                selftext_html= "selftext_html",
                                                num_comments = "num_comments",
                                                num_reports  = "num_reports",
                                                banned_by    = "banned_by",
                                                approved_by  = "approved_by",
                                                subreddit    = "subreddit",
                                                subreddit_id = "subreddit_id",
                                                is_self      = "is_self", 
                                                permalink    = "permalink",
                                                )

    def thing_attr(self, thing, attr):
        from r2.lib.scraper import get_media_embed
        if attr == "media_embed":
           if (thing.media_object and
               not isinstance(thing.media_object, basestring)):
               media_embed = get_media_embed(thing.media_object)
               if media_embed:
                   return dict(scrolling = media_embed.scrolling,
                               width = media_embed.width,
                               height = media_embed.height,
                               content = media_embed.content)
           return dict()
        elif attr == 'subreddit':
            return thing.subreddit.name
        elif attr == 'subreddit_id':
            return thing.subreddit._fullname
        elif attr == 'selftext':
            if not thing.expunged:
                return thing.selftext
            else:
                return ''
        elif attr == 'selftext_html':
            if not thing.expunged:
                return safemarkdown(thing.selftext)
            else:
                return safemarkdown(_("[removed]"))
        return ThingJsonTemplate.thing_attr(self, thing, attr)

    def rendered_data(self, thing):
        d = ThingJsonTemplate.rendered_data(self, thing)
        d['sr'] = thing.subreddit._fullname
        return d


class PromotedLinkJsonTemplate(LinkJsonTemplate):
    _data_attrs_ = LinkJsonTemplate.data_attrs(promoted = "promoted")
    del _data_attrs_['author']

class CommentJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = ThingJsonTemplate.data_attrs(ups          = "upvotes",
                                                downs        = "downvotes",
                                                replies      = "child",
                                                body         = "body",
                                                body_html    = "body_html",
                                                likes        = "likes",
                                                author       = "author", 
                                                author_flair_text =
                                                    "author_flair_text",
                                                author_flair_css_class =
                                                    "author_flair_css_class",
                                                link_id      = "link_id",
                                                subreddit    = "subreddit",
                                                subreddit_id = "subreddit_id",
                                                num_reports  = "num_reports",
                                                banned_by    = "banned_by",
                                                approved_by  = "approved_by",
                                                parent_id    = "parent_id",
                                                )

    def thing_attr(self, thing, attr):
        from r2.models import Comment, Link, Subreddit
        if attr == 'link_id':
            return make_fullname(Link, thing.link_id)
        elif attr == 'subreddit':
            return thing.subreddit.name
        elif attr == 'subreddit_id':
            return thing.subreddit._fullname
        elif attr == "parent_id":
            if getattr(thing, "parent_id", None):
                return make_fullname(Comment, thing.parent_id)
            else:
                return make_fullname(Link, thing.link_id)
        elif attr == "body_html":
            return spaceCompress(safemarkdown(thing.body))
        return ThingJsonTemplate.thing_attr(self, thing, attr)

    def kind(self, wrapped):
        from r2.models import Comment
        return make_typename(Comment)

    def raw_data(self, thing):
        d = ThingJsonTemplate.raw_data(self, thing)
        if c.profilepage:
            d['link_title'] = thing.link.title
        return d

    def rendered_data(self, wrapped):
        d = ThingJsonTemplate.rendered_data(self, wrapped)
        d['replies'] = self.thing_attr(wrapped, 'child')
        d['contentText'] = self.thing_attr(wrapped, 'body')
        d['contentHTML'] = self.thing_attr(wrapped, 'body_html')
        d['link'] = self.thing_attr(wrapped, 'link_id')
        d['parent'] = self.thing_attr(wrapped, 'parent_id')
        return d

class MoreCommentJsonTemplate(CommentJsonTemplate):
    _data_attrs_ = dict(id           = "_id36",
                        name         = "_fullname",
                        children     = "children")

    def kind(self, wrapped):
        return "more"

    def thing_attr(self, thing, attr):
        if attr == 'children':
            return [to36(x) for x in thing.children]
        if attr in ('body', 'body_html'):
            return ""
        return CommentJsonTemplate.thing_attr(self, thing, attr)

    def rendered_data(self, wrapped):
        return CommentJsonTemplate.rendered_data(self, wrapped)

class MessageJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = ThingJsonTemplate.data_attrs(new          = "new",
                                                subject      = "subject",
                                                body         = "body",
                                                replies      = "child",
                                                body_html    = "body_html",
                                                author       = "author",
                                                dest         = "dest",
                                                subreddit = "subreddit",
                                                was_comment  = "was_comment",
                                                context      = "context", 
                                                created      = "created",
                                                parent_id    = "parent_id",
                                                first_message= "first_message")

    def thing_attr(self, thing, attr):
        from r2.models import Message
        if attr == "was_comment":
            return thing.was_comment
        elif attr == "context":
            return ("" if not thing.was_comment
                    else thing.permalink + "?context=3")
        elif attr == "dest":
            if thing.to_id:
                return thing.to.name
            else:
                return "#" + thing.subreddit.name
        elif attr == "subreddit":
            if thing.sr_id:
                return thing.subreddit.name
            return None
        elif attr == "body_html":
            return safemarkdown(thing.body)
        elif attr == "author" and getattr(thing, "hide_author", False):
            return None
        elif attr == "parent_id":
            if getattr(thing, "parent_id", None):
                return make_fullname(Message, thing.parent_id)
        return ThingJsonTemplate.thing_attr(self, thing, attr)

    def rendered_data(self, wrapped):
        from r2.models import Message
        parent_id = wrapped.parent_id
        if parent_id:
            parent_id = make_fullname(Message, parent_id)
        d = ThingJsonTemplate.rendered_data(self, wrapped)
        d['parent'] = parent_id
        d['contentText'] = self.thing_attr(wrapped, 'body')
        d['contentHTML'] = self.thing_attr(wrapped, 'body_html')
        return d


class RedditJsonTemplate(JsonTemplate):
    def render(self, thing = None, *a, **kw):
        return ObjectTemplate(thing.content().render() if thing else {})

class PanestackJsonTemplate(JsonTemplate):
    def render(self, thing = None, *a, **kw):
        res = [t.render() for t in thing.stack if t] if thing else []
        res = [x for x in res if x]
        if not res:
            return {}
        return ObjectTemplate(res if len(res) > 1 else res[0] )

class NullJsonTemplate(JsonTemplate):
    def render(self, thing = None, *a, **kw):
        return ""

class ListingJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = dict(children = "things",
                        after = "after",
                        before = "before",
                        modhash = "modhash")
    
    def thing_attr(self, thing, attr):
        if attr == "modhash":
            return c.modhash
        elif attr == "things":
            res = []
            for a in thing.things:
                a.childlisting = False
                r = a.render()
                res.append(r)
            return res
        return ThingJsonTemplate.thing_attr(self, thing, attr)
        

    def rendered_data(self, thing):
        return self.thing_attr(thing, "things")
    
    def kind(self, wrapped):
        return "Listing"

class UserListJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = dict(children = "users")

    def thing_attr(self, thing, attr):
        if attr == "users":
            res = []
            for a in thing.users:
                r = a.render()
                res.append(r)
            return res
        return ThingJsonTemplate.thing_attr(self, thing, attr)

    def rendered_data(self, thing):
        return self.thing_attr(thing, "users")

    def kind(self, wrapped):
        return "UserList"

class UserTableItemJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = dict(id = "_fullname",
                        name = "name")

    def thing_attr(self, thing, attr):
        return ThingJsonTemplate.thing_attr(self, thing.user, attr)

    def render(self, thing, *a, **kw):
        return ObjectTemplate(self.data(thing))

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
        return ObjectTemplate(res)

class FlairListJsonTemplate(JsonTemplate):
    def render(self, thing, *a, **kw):
        def row_to_json(row):
            if hasattr(row, 'user'):
              return dict(user=row.user.name, flair_text=row.flair_text,
                          flair_css_class=row.flair_css_class)
            else:
              # prev/next link
              return dict(after=row.after, reverse=row.reverse)

        json_rows = [row_to_json(row) for row in thing.flair]
        result = dict(users=[row for row in json_rows if 'user' in row])
        for row in json_rows:
            if 'after' in row:
                if row['reverse']:
                    result['prev'] = row['after']
                else:
                    result['next'] = row['after']
        return ObjectTemplate(result)

class FlairCsvJsonTemplate(JsonTemplate):
    def render(self, thing, *a, **kw):
        return ObjectTemplate([l.__dict__ for l in thing.results_by_line])
