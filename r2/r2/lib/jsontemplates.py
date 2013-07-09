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

import calendar

from utils import to36, tup, iters
from wrapped import Wrapped, StringTemplate, CacheStub, CachedVariable, Templated
from mako.template import Template
from r2.config.extensions import get_api_subtype
from r2.lib.filters import spaceCompress, safemarkdown
from r2.models.subreddit import SubSR
import time, pytz
from pylons import c, g
from pylons.i18n import _

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
            if thing.author._deleted:
                return "[deleted]"
            return thing.author.name
        if attr == "author_flair_text":
            if thing.author._deleted:
                return None
            if thing.author.flair_enabled_in_sr(thing.subreddit._id):
                return getattr(thing.author,
                               'flair_%s_text' % (thing.subreddit._id),
                               None)
            else:
                return None
        if attr == "author_flair_css_class":
            if thing.author._deleted:
                return None
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

        if attr == 'distinguished':
            distinguished = getattr(thing, attr, 'no')
            if distinguished == 'no':
                return None
            return distinguished
        
        if attr in ["num_reports", "banned_by", "approved_by"]:
            if c.user_is_loggedin and thing.subreddit.is_moderator(c.user):
                if attr == "num_reports":
                    return thing.reported
                ban_info = getattr(thing, "ban_info", {})
                if attr == "banned_by":
                    banner = (ban_info.get("banner")
                              if ban_info.get('moderator_banned')
                              else True)
                    return banner if thing._spam else None
                elif attr == "approved_by":
                    return ban_info.get("unbanner") if not thing._spam else None

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
                                                description_html = "description_html",
                                                public_description = "public_description",
                                                display_name = "name",
                                                header_img   = "header",
                                                header_size  = "header_size",
                                                header_title = "header_title",
                                                accounts_active = "accounts_active",
                                                )

    def raw_data(self, thing):
        data = ThingJsonTemplate.raw_data(self, thing)
        permissions = getattr(thing, 'mod_permissions', None)
        if permissions:
            permissions = [perm for perm, has in permissions.iteritems() if has]
            data['mod_permissions'] = permissions
        return data

    def thing_attr(self, thing, attr):
        if attr == "_ups" and thing.hide_subscribers:
            return 0
        # Don't return accounts_active counts in /subreddits
        elif (attr == "accounts_active" and isinstance(c.site, SubSR)):
            return None
        elif attr == 'description_html':
            return safemarkdown(thing.description)
        else:
            return ThingJsonTemplate.thing_attr(self, thing, attr)

class LabeledMultiJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = ThingJsonTemplate.data_attrs(
        path="path",
        name="name",
        subreddits="srs",
        visibility="visibility",
        can_edit="can_edit",
    )
    del _data_attrs_["id"]

    def kind(self, wrapped):
        return "LabeledMulti"

    @classmethod
    def sr_props(cls, thing, srs):
        sr_props = thing.sr_props
        return [dict(sr_props[sr._id], name=sr.name) for sr in srs]

    def thing_attr(self, thing, attr):
        if attr == "srs":
            return self.sr_props(thing, thing.srs)
        elif attr == "can_edit":
            return c.user_is_loggedin and thing.can_edit(c.user)
        else:
            return ThingJsonTemplate.thing_attr(self, thing, attr)

class LabeledMultiDescriptionJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = dict(
        body_md="description_md",
        body_html="description_html",
    )

    def kind(self, wrapped):
        return "LabeledMultiDescription"

    def thing_attr(self, thing, attr):
        if attr == "description_html":
            # if safemarkdown is passed a falsy string it returns None :/
            description_html = safemarkdown(thing.description_md) or ''
            return description_html
        else:
            return ThingJsonTemplate.thing_attr(self, thing, attr)

class IdentityJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = ThingJsonTemplate.data_attrs(name = "name",
                                                link_karma = "safe_karma",
                                                comment_karma = "comment_karma",
                                                is_gold = "gold",
                                                is_mod = "is_mod",
                                                over_18 = "pref_over_18",
                                                has_verified_email = "email_verified",
                                                )

    def thing_attr(self, thing, attr):
        from r2.models import Subreddit
        if attr == "is_mod":
            t = thing.lookups[0] if isinstance(thing, Wrapped) else thing
            return bool(Subreddit.reverse_moderator_ids(t))
        return ThingJsonTemplate.thing_attr(self, thing, attr)

class AccountJsonTemplate(IdentityJsonTemplate):
    _data_attrs_ = IdentityJsonTemplate.data_attrs(has_mail = "has_mail",
                                                  has_mod_mail = "has_mod_mail",
                                                  is_mod = "is_mod",
                                                  is_friend = "is_friend",
                                                  )

    def thing_attr(self, thing, attr):
        if attr == "has_mail":
            if c.user_is_loggedin and thing._id == c.user._id:
                return bool(c.have_messages)
            return None
        if attr == "has_mod_mail":
            if c.user_is_loggedin and thing._id == c.user._id:
                return bool(c.have_mod_messages)
            return None
        if attr == "is_friend":
            return c.user_is_loggedin and thing._id in c.user.friends
        return IdentityJsonTemplate.thing_attr(self, thing, attr)

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
                                                link_flair_text =
                                                    "flair_text",
                                                link_flair_css_class =
                                                    "flair_css_class",
                                                thumbnail    = "thumbnail",
                                                media        = "media_object",
                                                media_embed  = "media_embed",
                                                selftext     = "selftext",
                                                selftext_html= "selftext_html",
                                                distinguished= "distinguished",
                                                num_comments = "num_comments",
                                                num_reports  = "num_reports",
                                                banned_by    = "banned_by",
                                                approved_by  = "approved_by",
                                                subreddit    = "subreddit",
                                                subreddit_id = "subreddit_id",
                                                is_self      = "is_self", 
                                                permalink    = "permalink",
                                                edited       = "editted"
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
        elif attr == "editted" and not isinstance(thing.editted, bool):
            return (time.mktime(thing.editted.astimezone(pytz.UTC).timetuple())
                    - time.timezone)
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
                                                score_hidden = "score_hidden",
                                                replies      = "child",
                                                body         = "body",
                                                body_html    = "body_html",
                                                distinguished= "distinguished",
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
                                                edited       = "editted",
                                                gilded       = "gilded",
                                                )

    def thing_attr(self, thing, attr):
        from r2.models import Comment, Link, Subreddit
        if attr == 'link_id':
            return make_fullname(Link, thing.link_id)
        elif attr == "editted" and not isinstance(thing.editted, bool):
            return (time.mktime(thing.editted.astimezone(pytz.UTC).timetuple())
                    - time.timezone)
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
        elif attr == "gilded":
            return thing.gildings
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
                        children     = "children",
                        count        = "count",
                        parent_id    = "parent_id")

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
                                                first_message= "first_message",
                                                first_message_name = "first_message_name")

    def thing_attr(self, thing, attr):
        from r2.models import Comment, Link, Message
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
            if thing.was_comment:
                if getattr(thing, "parent_id", None):
                    return make_fullname(Comment, thing.parent_id)
                else:
                    return make_fullname(Link, thing.link_id)
            elif getattr(thing, "parent_id", None):
                return make_fullname(Message, thing.parent_id)
        elif attr == "first_message_name":
            if getattr(thing, "first_message", None):
                return make_fullname(Message, thing.first_message)
        return ThingJsonTemplate.thing_attr(self, thing, attr)

    def raw_data(self, thing):
        d = ThingJsonTemplate.raw_data(self, thing)
        if thing.was_comment:
            d['link_title'] = thing.link_title
            d['likes'] = thing.likes
        return d

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

    def get_def(self, name):
        return self

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
            for a in thing.user_rows:
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

    def inject_note(self, thing, d):
        if (thing.type in ("banned", "wikibanned") or
            (c.user.gold and thing.type == "friend")):
            d["note"] = getattr(thing.rel, 'note', '')
        return d

    def rendered_data(self, thing):
        d = ThingJsonTemplate.rendered_data(self, thing)
        return self.inject_note(thing, d)

    def raw_data(self, thing):
        d = ThingJsonTemplate.raw_data(self, thing)
        return self.inject_note(thing, d)

    def render(self, thing, *a, **kw):
        return ObjectTemplate(self.data(thing))

class OrganicListingJsonTemplate(ListingJsonTemplate):
    def kind(self, wrapped):
        return "OrganicListing"

class TrafficJsonTemplate(JsonTemplate):
    def render(self, thing, *a, **kw):
        res = {}

        for interval in ("hour", "day", "month"):
            # we don't actually care about the column definitions (used for
            # charting) here, so just pass an empty list.
            interval_data = thing.get_data_for_interval(interval, [])

            # turn the python datetimes into unix timestamps and flatten data
            res[interval] = [(calendar.timegm(date.timetuple()),) + data
                             for date, data in interval_data]

        return ObjectTemplate(res)

class WikiJsonTemplate(JsonTemplate):
    def render(self, thing, *a, **kw):
        try:
            content = thing.content()
        except AttributeError:
            content = thing.listing
        return ObjectTemplate(content.render() if thing else {})

class WikiPageListingJsonTemplate(ThingJsonTemplate):
    def kind(self, thing):
        return "wikipagelisting"
    
    def data(self, thing):
        pages = [p.name for p in thing.linear_pages]
        return pages

class WikiViewJsonTemplate(ThingJsonTemplate):
    def kind(self, thing):
        return "wikipage"
    
    def data(self, thing):
        edit_date = time.mktime(thing.edit_date.timetuple()) if thing.edit_date else None
        edit_by = None
        if thing.edit_by and not thing.edit_by._deleted:
             edit_by = Wrapped(thing.edit_by).render()
        return dict(content_md=thing.page_content_md,
                    content_html=thing.page_content,
                    revision_by=edit_by,
                    revision_date=edit_date,
                    may_revise=thing.may_revise)

class WikiSettingsJsonTemplate(ThingJsonTemplate):
     def kind(self, thing):
         return "wikipagesettings"
    
     def data(self, thing):
         editors = [Wrapped(e).render() for e in thing.mayedit]
         return dict(permlevel=thing.permlevel,
                     editors=editors)

class WikiRevisionJsonTemplate(ThingJsonTemplate):
    def render(self, thing, *a, **kw):
        timestamp = time.mktime(thing.date.timetuple()) if thing.date else None
        author = thing.get_author()
        if author and not author._deleted:
            author = Wrapped(author).render()
        else:
            author = None
        return ObjectTemplate(dict(author=author,
                                   id=str(thing._id),
                                   timestamp=timestamp,
                                   reason=thing._get('reason'),
                                   page=thing.page))

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

class StylesheetTemplate(ThingJsonTemplate):
    _data_attrs_ = dict(subreddit_id = '_fullname',
                        stylesheet = 'stylesheet_contents',
                        images = '_images',
                        prevstyle = 'prev_stylesheet')

    def kind(self, wrapped):
        return 'stylesheet'

    def images(self):
        images = []
        for name, url in c.site.get_images():
            images.append({'name': name,
                           'link': 'url(%%%%%s%%%%)' % name,
                           'url': url})
        return images

    def thing_attr(self, thing, attr):
        if attr == '_images':
            return self.images()
        elif attr == '_fullname':
            return c.site._fullname
        elif attr == 'prev_stylesheet':
            return c.site.prev_stylesheet
        return ThingJsonTemplate.thing_attr(self, thing, attr)

class SubredditSettingsTemplate(ThingJsonTemplate):
    _data_attrs_ = dict(subreddit_id = 'site._fullname',
                        title = 'site.title',
                        description = 'site.description',
                        public_description = 'site.public_description',
                        public_traffic = 'site.public_traffic',
                        prev_description_id = 'site.prev_description_id',
                        prev_public_description_id = 'site.prev_public_description_id',
                        language = 'site.lang',
                        subreddit_type = 'site.type',
                        submit_link_label = 'site.submit_link_label',
                        submit_text_label = 'site.submit_text_label',
                        comment_score_hide_mins = 'site.comment_score_hide_mins',
                        content_options = 'site.link_type',
                        over_18 = 'site.over_18',
                        default_set = 'site.allow_top',
                        show_media = 'site.show_media',
                        exclude_banned_modqueue = 'site.exclude_banned_modqueue',
                        domain = 'site.domain',
                        domain_css = 'site.css_on_cname',
                        wikimode = 'site.wikimode',
                        wiki_edit_karma = 'site.wiki_edit_karma',
                        wiki_edit_age = 'site.wiki_edit_age',
                        domain_sidebar = 'site.show_cname_sidebar',
                        header_hover_text = 'site.header_title')

    def kind(self, wrapped):
        return 'subreddit_settings'

    def thing_attr(self, thing, attr):
        if attr.startswith('site.') and thing.site:
            return getattr(thing.site, attr[5:])
        return ThingJsonTemplate.thing_attr(self, thing, attr)

class ModActionTemplate(ThingJsonTemplate):
    _data_attrs_ = dict(sr_id36='sr_id36',
                        mod_id36='mod_id36',
                        id='_fullname',
                        subreddit='sr_name',
                        mod='author',
                        created_utc='date',
                        action='action',
                        details='details',
                        description='description',
                        target_fullname='target_fullname')

    def thing_attr(self, thing, attr):
        if attr == 'date':
            return (time.mktime(thing.date.astimezone(pytz.UTC).timetuple())
                    - time.timezone)
        return ThingJsonTemplate.thing_attr(self, thing, attr)

    def kind(self, wrapped):
        return 'modaction'


class PolicyViewJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = dict(
        body_html="body_html",
        toc_html="toc_html",
        revs="revs",
        display_rev="display_rev",
    )

    def kind(self, wrapped):
        return "Policy"
