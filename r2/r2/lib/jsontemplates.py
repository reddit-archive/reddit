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
# All portions of the code written by reddit are Copyright (c) 2006-2015 reddit
# Inc. All Rights Reserved.
###############################################################################

import calendar

from utils import to36, tup, iters
from wrapped import Wrapped, StringTemplate, CacheStub, Templated
from mako.template import Template
from r2.config import feature
from r2.config.extensions import get_api_subtype
from r2.lib.filters import spaceCompress, safemarkdown, _force_unicode
from r2.models import Account, Report, Trophy
from r2.models.subreddit import SubSR
from r2.models.token import OAuth2Scope, extra_oauth2_scope
import time, pytz
from pylons import c, g, response
from pylons.i18n import _

from r2.models.wiki import ImagesByWikiPage


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
                return _force_unicode(obj)
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


class ThingTemplate(object):
    @classmethod
    def render(cls, thing):
        """
        Return a JSON representation of a Wrapped Thing object.

        The Thing object should be Wrapped and been run through add_props just
        like is required for regular HTML rendering. The return value is an
        ObjectTemplate wrapped dictionary.

        """

        api_subtype = get_api_subtype()

        # the argument is named `thing` due to specifics of wrapped
        item = thing

        if api_subtype:
            # special handling for rendering a nested template as a different
            # style (usually html)
            data = cls.get_rendered(item, render_style=api_subtype)
        else:
            data = cls.get_json(item)

        d = {
            "kind": cls.get_kind(item),
            "data": data,
        }
        return ObjectTemplate(d)

    @classmethod
    def get_kind(cls, item):
        thing = item.lookups[0]
        return make_typename(thing.__class__)

    @classmethod
    def get_json(cls, item):
        data = {
            "created": time.mktime(item._date.timetuple()),
            "created_utc": time.mktime(
                item._date.astimezone(pytz.UTC).timetuple()) - time.timezone,
            "id": item._id36,
            "name": item._fullname,
        }
        return data

    @classmethod
    def get_rendered(cls, item, render_style):
        data = {
            "id": item._fullname,
            "content": item.render(style=render_style),
        }
        return data


class ThingJsonTemplate(JsonTemplate):
    _data_attrs_ = dict(
        created="created",
        created_utc="created_utc",
        id="_id36",
        name="_fullname",
    )

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
        attrs = dict(self._data_attrs_)
        if hasattr(self, "_optional_data_attrs"):
            for attr, attrv in self._optional_data_attrs.iteritems():
                if hasattr(thing, attr):
                    attrs[attr] = attrv

        return dict((k, self.thing_attr(thing, v))
                    for k, v in attrs.iteritems())

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
            child = getattr(thing, "child", None)
            if child:
                return child.render()
            else:
                return ""
        elif attr == "upvotes":
            return thing.score
        elif attr == "downvotes":
            return 0

        if attr == 'distinguished':
            distinguished = getattr(thing, attr, 'no')
            if distinguished == 'no':
                return None
            return distinguished

        if attr in ["num_reports", "report_reasons", "banned_by", "approved_by"]:
            if c.user_is_loggedin and thing.user_is_moderator:
                if attr == "num_reports":
                    return thing.reported
                elif attr == "report_reasons":
                    return Report.get_reasons(thing)

                ban_info = getattr(thing, "ban_info", {})
                if attr == "banned_by":
                    banner = (ban_info.get("banner")
                              if ban_info.get('moderator_banned')
                              else True)
                    return banner if thing._spam else None
                elif attr == "approved_by":
                    return ban_info.get("unbanner") if not thing._spam else None

        if attr == 'admin_takedown':
            if thing.admin_takedown:
                return 'legal'
            return None

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
    _data_attrs_ = ThingJsonTemplate.data_attrs(
        accounts_active="accounts_active",
        banner_img="banner_img",
        banner_size="banner_size",
        collapse_deleted_comments="collapse_deleted_comments",
        comment_score_hide_mins="comment_score_hide_mins",
        # community_rules="community_rules",
        description="description",
        description_html="description_html",
        display_name="name",
        header_img="header",
        header_size="header_size",
        header_title="header_title",
        icon_img="icon_img",
        icon_size="icon_size",
        # key_color="key_color",
        over18="over_18",
        public_description="public_description",
        public_description_html="public_description_html",
        public_traffic="public_traffic",
        # related_subreddits="related_subreddits",
        hide_ads="hide_ads",
        submission_type="link_type",
        submit_link_label="submit_link_label",
        submit_text_label="submit_text_label",
        submit_text="submit_text",
        submit_text_html="submit_text_html",
        subreddit_type="type",
        subscribers="_ups",
        title="title",
        url="path",
        user_is_banned="is_banned",
        user_is_contributor="is_contributor",
        user_is_moderator="is_moderator",
        user_is_subscriber="is_subscriber",
        user_sr_theme_enabled="user_sr_style_enabled",
    )

    # subreddit *attributes* (right side of the equals)
    # that are accessible even if the user can't view the subreddit
    _public_attrs = {
        "_id36",
        # subreddit ID with prefix
        "_fullname",
        # Creation date
        "created",
        "created_utc",
        # Canonically-cased subreddit name
        "name",
        # Canonical subreddit URL, relative to reddit.com
        "path",
        # Text shown on the access denied page
        "public_description",
        "public_description_html",
        # Title shown in search
        "title",
        # Type of subreddit, so people know that it's private
        "type",
    }

    def raw_data(self, thing):
        data = ThingJsonTemplate.raw_data(self, thing)

        # XXX remove this when feature is enabled and use _data_attrs instead
        if feature.is_enabled('mobile_settings'):
            for attr in ('community_rules', 'key_color', 'related_subreddits'):
                data[attr] = self.thing_attr(thing, attr)

        permissions = getattr(thing, 'mod_permissions', None)
        if permissions:
            permissions = [perm for perm, has in permissions.iteritems() if has]
            data['mod_permissions'] = permissions

        return data

    def thing_attr(self, thing, attr):
        if attr not in self._public_attrs and not thing.can_view(c.user):
            return None

        if attr == "_ups" and thing.hide_subscribers:
            return 0
        # Don't return accounts_active counts in /subreddits
        elif (attr == "accounts_active" and isinstance(c.site, SubSR)):
            return None
        elif attr == 'description_html':
            return safemarkdown(thing.description)
        elif attr == 'public_description_html':
            return safemarkdown(thing.public_description)
        elif attr == "is_moderator":
            if c.user_is_loggedin:
                return thing.moderator
            return None
        elif attr == "is_contributor":
            if c.user_is_loggedin:
                return thing.contributor
            return None
        elif attr == "is_subscriber":
            if c.user_is_loggedin:
                return thing.subscriber
            return None
        elif attr == 'is_banned':
            if c.user_is_loggedin:
                return thing.banned
            return None
        elif attr == 'submit_text_html':
            return safemarkdown(thing.submit_text)
        elif attr == 'community_rules':
            if thing.community_rules:
                return thing.community_rules.split('\n')
            return []
        elif attr == 'user_sr_style_enabled':
            if c.user_is_loggedin:
                return c.user.use_subreddit_style(thing)
            else:
                return True
        else:
            return ThingJsonTemplate.thing_attr(self, thing, attr)


class LabeledMultiDescriptionJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = dict(
        body_html="description_html",
        body_md="description_md",
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


class LabeledMultiJsonTemplate(LabeledMultiDescriptionJsonTemplate):
    _data_attrs_ = ThingJsonTemplate.data_attrs(
        can_edit="can_edit",
        copied_from="copied_from",
        description_html="description_html",
        description_md="description_md",
        display_name="display_name",
        key_color="key_color",
        icon_name="icon_id",
        icon_url="icon_url",
        name="name",
        path="path",
        subreddits="srs",
        visibility="visibility",
        weighting_scheme="weighting_scheme",
    )
    del _data_attrs_["id"]

    def __init__(self, expand_srs=False):
        super(LabeledMultiJsonTemplate, self).__init__()
        self.expand_srs = expand_srs

    def kind(self, wrapped):
        return "LabeledMulti"

    @classmethod
    def sr_props(cls, thing, srs, expand=False):
        sr_props = dict(thing.sr_props)
        if expand:
            for sr in srs:
                sr_props[sr._id]["data"] = TrimmedSubredditJsonTemplate().data(sr)
        return [dict(sr_props[sr._id], name=sr.name) for sr in srs]

    def thing_attr(self, thing, attr):
        if attr == "srs":
            return self.sr_props(thing, thing.srs, expand=self.expand_srs)
        elif attr == "can_edit":
            return c.user_is_loggedin and thing.can_edit(c.user)
        elif attr == "copied_from":
            if thing.can_edit(c.user):
                return thing.copied_from
            else:
                return None
        elif attr == "display_name":
            return thing.display_name or thing.name
        else:
            super_ = super(LabeledMultiJsonTemplate, self)
            return super_.thing_attr(thing, attr)


class TrimmedSubredditJsonTemplate(SubredditJsonTemplate):
    _data_attrs_ = dict(
        name="_fullname",
        display_name="name",
        banner_img="banner_img",
        banner_size="banner_size",
        header_img="header",
        header_size="header_size",
        icon_img="icon_img",
        icon_size="icon_size",
        key_color="key_color",
        subscribers="_ups",
        url="path",
        user_is_banned="is_banned",
        user_is_contributor="is_contributor",
        user_is_moderator="is_moderator",
        user_is_subscriber="is_subscriber",
    )

    def thing_attr(self, thing, attr):
        if attr in ('is_banned', 'is_contributor', 'is_moderator',
                    'is_subscriber'):
            # can't use SubredditJsonTemplate.thing_attr for these attributes
            # because it depends on the thing being a fully built/wrapped object
            # that has run through Subreddit.add_props
            if c.user_is_loggedin:
                check_func = getattr(thing, attr)
                return bool(check_func(c.user))
            else:
                return None
        else:
            return SubredditJsonTemplate.thing_attr(self, thing, attr)


class IdentityJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = ThingJsonTemplate.data_attrs(
        comment_karma="comment_karma",
        has_verified_email="email_verified",
        is_gold="gold",
        is_mod="is_mod",
        link_karma="link_karma",
        name="name",
        hide_from_robots="pref_hide_from_robots",
    )
    _private_data_attrs = dict(
        inbox_count="inbox_count",
        over_18="pref_over_18",
        gold_creddits="gold_creddits",
        gold_expiration="gold_expiration",
    )

    def raw_data(self, thing):
        attrs = self._data_attrs_.copy()
        if c.user_is_loggedin and thing._id == c.user._id:
            attrs.update(self._private_data_attrs)
        if thing.pref_hide_from_robots:
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        data = {k: self.thing_attr(thing, v) for k, v in attrs.iteritems()}
        try:
            self.add_message_data(data, thing)
        except OAuth2Scope.InsufficientScopeError:
            # No access to privatemessages, but the rest of
            # the identity information is sufficient.
            pass
        return data

    @extra_oauth2_scope("privatemessages")
    def add_message_data(self, data, thing):
        if c.user_is_loggedin and thing._id == c.user._id:
            data['has_mail'] = self.thing_attr(thing, 'has_mail')
            data['has_mod_mail'] = self.thing_attr(thing, 'has_mod_mail')

    def thing_attr(self, thing, attr):
        from r2.lib.template_helpers import (
            display_comment_karma, display_link_karma)
        if attr == "is_mod":
            t = thing.lookups[0] if isinstance(thing, Wrapped) else thing
            return t.is_moderator_somewhere
        elif attr == "has_mail":
            return bool(c.have_messages)
        elif attr == "has_mod_mail":
            return bool(c.have_mod_messages)
        elif attr == "comment_karma":
            return display_comment_karma(thing.comment_karma)
        elif attr == "link_karma":
            return display_link_karma(thing.link_karma)
        elif attr == "gold_expiration":
            if not thing.gold:
                return None
            return calendar.timegm(thing.gold_expiration.utctimetuple())
        return ThingJsonTemplate.thing_attr(self, thing, attr)


class AccountJsonTemplate(IdentityJsonTemplate):
    _data_attrs_ = IdentityJsonTemplate.data_attrs(is_friend="is_friend")
    _private_data_attrs = dict(
        modhash="modhash",
        **IdentityJsonTemplate._private_data_attrs
    )

    def thing_attr(self, thing, attr):
        if attr == "is_friend":
            return c.user_is_loggedin and thing._id in c.user.friends
        elif attr == "modhash":
            return c.modhash
        return IdentityJsonTemplate.thing_attr(self, thing, attr)



class PrefsJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = dict((k[len("pref_"):], k) for k in
            Account._preference_attrs)

    def __init__(self, fields=None):
        if fields is not None:
            _data_attrs_ = {}
            for field in fields:
                if field not in self._data_attrs_:
                    raise KeyError(field)
                _data_attrs_[field] = self._data_attrs_[field]
            self._data_attrs_ = _data_attrs_

    def thing_attr(self, thing, attr):
        if attr == "pref_clickgadget":
            return bool(thing.pref_clickgadget)
        return ThingJsonTemplate.thing_attr(self, thing, attr)


class LinkJsonTemplate(ThingJsonTemplate):
    _optional_data_attrs = dict(
        action_type="action_type",
        sr_detail="sr_detail",
        )
    _data_attrs_ = ThingJsonTemplate.data_attrs(
        approved_by="approved_by",
        archived="archived",
        author="author",
        author_flair_css_class="author_flair_css_class",
        author_flair_text="author_flair_text",
        banned_by="banned_by",
        visited="visited",
        clicked="clicked",
        distinguished="distinguished",
        domain="domain",
        downs="downvotes",
        edited="editted",
        gilded="gildings",
        hidden="hidden",
        is_self="is_self",
        likes="likes",
        link_flair_css_class="flair_css_class",
        link_flair_text="flair_text",
        media="media_object",
        media_embed="media_embed",
        num_comments="num_comments",
        num_reports="num_reports",
        report_reasons="report_reasons",
        mod_reports="mod_reports",
        user_reports="user_reports",
        over_18="over_18",
        permalink="permalink",
        removal_reason="admin_takedown",
        saved="saved",
        score="score",
        secure_media="secure_media_object",
        secure_media_embed="secure_media_embed",
        selftext="selftext",
        selftext_html="selftext_html",
        stickied="stickied",
        subreddit="subreddit",
        subreddit_id="subreddit_id",
        thumbnail="thumbnail",
        title="title",
        ups="upvotes",
        url="url",
    )

    PREVIEW_RESOLUTIONS = (108, 216, 320, 640, 960, 1080)
    PREVIEW_MAX_RATIO = 2

    def __init__(self):
        super(LinkJsonTemplate, self).__init__()
        if feature.is_enabled('default_sort'):
            self._data_attrs_['default_sort'] = 'default_sort'

    def thing_attr(self, thing, attr):
        from r2.lib.media import get_media_embed
        if attr == "sr_detail":
            return TrimmedSubredditJsonTemplate().data(thing.subreddit)
        if attr in ("media_embed", "secure_media_embed"):
            media_object = getattr(thing, attr.replace("_embed", "_object"))
            if media_object and not isinstance(media_object, basestring):
                media_embed = get_media_embed(media_object)
                if media_embed:
                    return {
                        "scrolling": media_embed.scrolling,
                        "width": media_embed.width,
                        "height": media_embed.height,
                        "content": media_embed.content,
                    }
            return {}
        elif attr == "clicked":
            # this hasn't been used in years.
            return False
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
        elif attr == "archived":
            return not thing.votable
        return ThingJsonTemplate.thing_attr(self, thing, attr)

    @staticmethod
    def generate_image_links(preview_object, censor_nsfw=False):
        # Determine which previews would be feasible with our given dims
        source_width = preview_object['width']
        source_height = preview_object['height']
        source_ratio = float(source_height) / source_width

        preview_resolutions = []
        for w in LinkJsonTemplate.PREVIEW_RESOLUTIONS:
            if w > source_width:
                continue

            url = g.image_resizing_provider.resize_image(
                preview_object, w, censor_nsfw,
                LinkJsonTemplate.PREVIEW_MAX_RATIO)
            h = int(w * source_ratio)
            preview_resolutions.append({
                "url": url,
                "width": w,
                "height": h,
            })

        url = g.image_resizing_provider.resize_image(
            preview_object, censor_nsfw=censor_nsfw)

        return {
            "source": {
                "url": url,
                "width": source_width,
                "height": source_height,
            },
            "resolutions": preview_resolutions,
        }

    def raw_data(self, thing):
        d = ThingJsonTemplate.raw_data(self, thing)

        if c.permalink_page:
            d["upvote_ratio"] = thing.upvote_ratio

        if feature.is_enabled('default_sort'):
            d['suggested_sort'] = thing.sort_if_suggested()

        preview_object = thing.preview_image
        if preview_object:
            d['preview'] = {}
            d['post_hint'] = thing.post_hint
            images = self.generate_image_links(preview_object)
            images['id'] = preview_object['uid']
            images['variants'] = {}
            if thing.nsfw:
                images['variants']['nsfw'] = self.generate_image_links(
                    preview_object, censor_nsfw=True)
            d['preview']['images'] = [images]

        return d

    def rendered_data(self, thing):
        d = ThingJsonTemplate.rendered_data(self, thing)
        d['sr'] = thing.subreddit._fullname
        return d


class PromotedLinkJsonTemplate(LinkJsonTemplate):
    _data_attrs_ = LinkJsonTemplate.data_attrs(
        promoted="promoted",
        imp_pixel="imp_pixel",
        href_url="href_url",
        adserver_imp_pixel="adserver_imp_pixel",
        adserver_click_url="adserver_click_url",
        mobile_ad_url="mobile_ad_url",
        disable_comments="disable_comments",
    )
    del _data_attrs_['subreddit']
    del _data_attrs_['subreddit_id']


class CommentJsonTemplate(ThingTemplate):
    @classmethod
    def get_parent_id(cls, item):
        from r2.models import Comment, Link

        if getattr(item, "parent_id", None):
            return make_fullname(Comment, item.parent_id)
        else:
            return make_fullname(Link, item.link_id)

    @classmethod
    def get_link_name(cls, item):
        from r2.models import Link
        return make_fullname(Link, item.link_id)

    @classmethod
    def render_child(cls, item):
        child = getattr(item, "child", None)
        if child:
            return child.render()
        else:
            return ""

    @classmethod
    def get_json(cls, item):
        from r2.models import Link

        data = ThingTemplate.get_json(item)

        data.update({
            "archived": not item.votable,
            "body": item.body,
            "body_html": spaceCompress(safemarkdown(item.body)),
            "controversiality": 1 if item.is_controversial else 0,
            "downs": 0,
            "gilded": item.gildings,
            "likes": item.likes,
            "link_id": cls.get_link_name(item),
            "mod_reports": item.mod_reports,
            "user_reports": item.user_reports,
            "saved": item.saved,
            "score": item.score,
            "score_hidden": item.score_hidden,
            "subreddit": item.subreddit.name,
            "subreddit_id": item.subreddit._fullname,
            "ups": item.score,
        })

        if getattr(item, "admin_takedown", None):
            data["removal_reason"] = "legal"
        else:
            data["removal_reason"] = None

        if not item.author._deleted:
            author = item.author
            sr_id = item.subreddit._id

            data["author"] = author.name

            if author.flair_enabled_in_sr(sr_id):
                flair_text = getattr(author, 'flair_%s_text' % sr_id, None)
                flair_css = getattr(author, 'flair_%s_css_class' % sr_id, None)
            else:
                flair_text = None
                flair_css = None
            data["author_flair_text"] = flair_text
            data["author_flair_css_class"] = flair_css

        else:
            data["author"] = "[deleted]"
            data["author_flair_text"] = None
            data["author_flair_css_class"] = None

        data["replies"] = cls.render_child(item)

        distinguished = getattr(item, "distinguished", "no")
        data["distinguished"] = distinguished if distinguished != "no" else None

        if isinstance(item.editted, bool):
            data["edited"] = item.editted
        else:
            editted_timetuple = item.editted.astimezone(pytz.UTC).timetuple()
            data["edited"] = time.mktime(editted_timetuple) - time.timezone

        data["parent_id"] = cls.get_parent_id(item)

        if hasattr(item, "action_type"):
            data["action_type"] = item.action_type

        if c.user_is_loggedin and item.user_is_moderator:
            data["num_reports"] = item.reported
            data["report_reasons"] = Report.get_reasons(item)

            ban_info = getattr(item, "ban_info", {})
            if item._spam:
                data["approved_by"] = None
                if ban_info.get('moderator_banned'):
                    data["banned_by"] = ban_info.get("banner") 
                else:
                    data["banned_by"] = True
            else:
                data["approved_by"] = ban_info.get("unbanner")
                data["banned_by"] = None
        else:
            data["num_reports"] = None
            data["report_reasons"] = None
            data["approved_by"] = None
            data["banned_by"] = None

        if c.profilepage:
            data["link_title"] = item.link.title
            data["link_author"] = item.link_author.name

            if item.link.is_self:
                link_url = item.link.make_permalink(
                    item.subreddit, force_domain=True)
            else:
                link_url = item.link.url
            data["link_url"] = link_url

        return data

    @classmethod
    def get_rendered(cls, item, render_style):
        data = ThingTemplate.get_rendered(item, render_style)
        data.update({
            "replies": cls.render_child(item),
            "contentText": item.body,
            "contentHTML": spaceCompress(safemarkdown(item.body)),
            "link": cls.get_link_name(item),
            "parent": cls.get_parent_id(item),
        })
        return data


class MoreCommentJsonTemplate(ThingTemplate):
    @classmethod
    def get_kind(cls, item):
        return "more"

    @classmethod
    def get_json(cls, item):
        data = {
            "children": [to36(comment_id) for comment_id in item.children],
            "count": item.count,
            "id": item._id36,
            "name": item._fullname,
            "parent_id": CommentJsonTemplate.get_parent_id(item),
        }
        return data

    @classmethod
    def get_rendered(cls, item, render_style):
        data = ThingTemplate.get_rendered(item, render_style)
        data.update({
            "replies": "",
            "contentText": "",
            "contentHTML": "",
            "link": CommentJsonTemplate.get_link_name(item),
            "parent": CommentJsonTemplate.get_parent_id(item),
        })
        return data


class MessageJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = ThingJsonTemplate.data_attrs(
        author="author",
        body="body",
        body_html="body_html",
        context="context",
        created="created",
        dest="dest",
        distinguished="distinguished",
        first_message="first_message",
        first_message_name="first_message_name",
        new="new",
        parent_id="parent_id",
        replies="child",
        subject="subject",
        subreddit="subreddit",
        was_comment="was_comment",
    )

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
    _data_attrs_ = dict(
        after="after",
        before="before",
        children="things",
        modhash="modhash",
    )
    
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


class SearchListingJsonTemplate(ListingJsonTemplate):
    def raw_data(self, thing):
        data = ThingJsonTemplate.raw_data(self, thing)

        def format_sr(sr, count):
            return {'name': sr.name, 'url': sr.path, 'count': count}

        facets = {}
        if thing.subreddit_facets:
            facets['subreddits'] = [format_sr(sr, count)
                                    for sr, count in thing.subreddit_facets]
        data['facets'] = facets

        return data


class UserListingJsonTemplate(ListingJsonTemplate):
    def raw_data(self, thing):
        if not thing.nextprev:
            return {"children": self.rendered_data(thing)}
        return ListingJsonTemplate.raw_data(self, thing)

    def kind(self, wrapped):
        return "Listing" if wrapped.nextprev else "UserList"

class UserListJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = dict(
        children="users",
    )

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
    _data_attrs_ = dict(
        id="_fullname",
        name="name",
    )

    def thing_attr(self, thing, attr):
        return ThingJsonTemplate.thing_attr(self, thing.user, attr)

    def render(self, thing, *a, **kw):
        return ObjectTemplate(self.data(thing))


class RelTableItemJsonTemplate(UserTableItemJsonTemplate):
    _data_attrs_ = UserTableItemJsonTemplate.data_attrs(
        date="date",
    )

    def thing_attr(self, thing, attr):
        rel_attr, splitter, attr = attr.partition(".")
        if attr == 'note':
            # return empty string instead of None for missing note
            return ThingJsonTemplate.thing_attr(self, thing.rel, attr) or ''
        elif attr:
            return ThingJsonTemplate.thing_attr(self, thing.rel, attr)
        elif rel_attr == 'date':
            # make date UTC
            date = self.thing_attr(thing, 'rel._date')
            date = time.mktime(date.astimezone(pytz.UTC).timetuple())
            return date - time.timezone
        else:
            return UserTableItemJsonTemplate.thing_attr(self, thing, rel_attr)


class FriendTableItemJsonTemplate(RelTableItemJsonTemplate):
    def inject_data(self, thing, d):
        if c.user.gold and thing.type == "friend":
            d["note"] = self.thing_attr(thing, 'rel.note')
        return d

    def rendered_data(self, thing):
        d = RelTableItemJsonTemplate.rendered_data(self, thing)
        return self.inject_data(thing, d)

    def raw_data(self, thing):
        d = RelTableItemJsonTemplate.raw_data(self, thing)
        return self.inject_data(thing, d)


class BannedTableItemJsonTemplate(RelTableItemJsonTemplate):
    _data_attrs_ = RelTableItemJsonTemplate.data_attrs(
        note="rel.note",
    )


class InvitedModTableItemJsonTemplate(RelTableItemJsonTemplate):
    _data_attrs_ = RelTableItemJsonTemplate.data_attrs(
        mod_permissions="permissions",
    )

    def thing_attr(self, thing, attr):
        if attr == 'permissions':
            permissions = thing.permissions.items()
            return [perm for perm, has in permissions if has]
        else:
            return RelTableItemJsonTemplate.thing_attr(self, thing, attr)


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
                     listed=thing.listed,
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
              return dict(after=row.after, reverse=row.previous)

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


class FlairSelectorJsonTemplate(JsonTemplate):
    def _template_dict(self, flair):
        return {"flair_template_id": flair.flair_template_id,
                "flair_position": flair.flair_position,
                "flair_text": flair.flair_text,
                "flair_css_class": flair.flair_css_class,
                "flair_text_editable": flair.flair_text_editable}

    def render(self, thing, *a, **kw):
        """Render a list of flair choices into JSON

        Sample output:
        {
            "choices": [
                {
                    "flair_css_class": "flair-444",
                    "flair_position": "right",
                    "flair_template_id": "5668d204-9388-11e3-8109-080027a38559",
                    "flair_text": "444",
                    "flair_text_editable": true
                },
                {
                    "flair_css_class": "flair-nouser",
                    "flair_position": "right",
                    "flair_template_id": "58e34d7a-9388-11e3-ab01-080027a38559",
                    "flair_text": "nouser",
                    "flair_text_editable": true
                },
                {
                    "flair_css_class": "flair-bar",
                    "flair_position": "right",
                    "flair_template_id": "fb01cc04-9391-11e3-b1d6-080027a38559",
                    "flair_text": "foooooo",
                    "flair_text_editable": true
                }
            ],
            "current": {
                "flair_css_class": "444",
                "flair_position": "right",
                "flair_template_id": "5668d204-9388-11e3-8109-080027a38559",
                "flair_text": "444"
            }
        }

        """
        choices = [self._template_dict(choice) for choice in thing.choices]

        current_flair = {
            "flair_text": thing.text,
            "flair_css_class": thing.css_class,
            "flair_position": thing.position,
            "flair_template_id": thing.matching_template,
        }
        return ObjectTemplate({"current": current_flair, "choices": choices})


class StylesheetTemplate(ThingJsonTemplate):
    _data_attrs_ = dict(
        images='_images',
        stylesheet='stylesheet_contents',
        subreddit_id='_fullname',
    )

    def kind(self, wrapped):
        return 'stylesheet'

    def images(self):
        sr_images = ImagesByWikiPage.get_images(c.site, "config/stylesheet")
        images = []
        for name, url in sr_images.iteritems():
            images.append({'name': name,
                           'link': 'url(%%%%%s%%%%)' % name,
                           'url': url})
        return images

    def thing_attr(self, thing, attr):
        if attr == '_images':
            return self.images()
        elif attr == '_fullname':
            return c.site._fullname
        return ThingJsonTemplate.thing_attr(self, thing, attr)

class SubredditSettingsTemplate(ThingJsonTemplate):
    _data_attrs_ = dict(
        collapse_deleted_comments='site.collapse_deleted_comments',
        comment_score_hide_mins='site.comment_score_hide_mins',
        # community_rules='site.community_rules',
        content_options='site.link_type',
        default_set='site.allow_top',
        description='site.description',
        domain='site.domain',
        domain_css='site.css_on_cname',
        domain_sidebar='site.show_cname_sidebar',
        exclude_banned_modqueue='site.exclude_banned_modqueue',
        header_hover_text='site.header_title',
        # key_color='site.key_color',
        language='site.lang',
        over_18='site.over_18',
        public_description='site.public_description',
        public_traffic='site.public_traffic',
        # related_subreddits='site.related_subreddits',
        hide_ads="site.hide_ads",
        show_media='site.show_media',
        submit_link_label='site.submit_link_label',
        submit_text_label='site.submit_text_label',
        submit_text='site.submit_text',
        subreddit_id='site._fullname',
        subreddit_type='site.type',
        title='site.title',
        wiki_edit_age='site.wiki_edit_age',
        wiki_edit_karma='site.wiki_edit_karma',
        wikimode='site.wikimode',
        spam_links='site.spam_links',
        spam_selfposts='site.spam_selfposts',
        spam_comments='site.spam_comments',
    )

    def kind(self, wrapped):
        return 'subreddit_settings'

    def thing_attr(self, thing, attr):
        if attr.startswith('site.') and thing.site:
            return getattr(thing.site, attr[5:])
        if attr == 'related_subreddits':
            # string used for form input
            return '\n'.join(thing.related_subreddits)
        return ThingJsonTemplate.thing_attr(self, thing, attr)

    def raw_data(self, thing):
        data = ThingJsonTemplate.raw_data(self, thing)

        # XXX remove this when feature is enabled and use _data_attrs instead
        if feature.is_enabled('mobile_settings'):
            for attr in ('community_rules', 'key_color', 'related_subreddits'):
                data[attr] = self.thing_attr(thing.site, attr)

        return data


class UploadedImageJsonTemplate(JsonTemplate):
    def render(self, thing, *a, **kw):
        return ObjectTemplate({
            "errors": list(k for (k, v) in thing.errors if v),
            "img_src": thing.img_src,
        })


class ModActionTemplate(ThingJsonTemplate):
    _data_attrs_ = dict(
        action='action',
        created_utc='date',
        description='description',
        details='details',
        id='_fullname',
        mod='moderator',
        mod_id36='mod_id36',
        sr_id36='sr_id36',
        subreddit='sr_name',
        target_author='target_author',
        target_fullname='target_fullname',
        target_permalink='target_permalink',
    )

    def thing_attr(self, thing, attr):
        if attr == 'date':
            return (time.mktime(thing.date.astimezone(pytz.UTC).timetuple())
                    - time.timezone)
        elif attr == 'target_author':
            if thing.target_author and thing.target_author._deleted:
                return "[deleted]"
            elif thing.target_author:
                return thing.target_author.name
            return ""
        elif attr == 'target_permalink':
            try:
                return thing.target.make_permalink_slow()
            except AttributeError:
                return None
        elif attr == "moderator":
            return thing.moderator.name

        return ThingJsonTemplate.thing_attr(self, thing, attr)

    def kind(self, wrapped):
        return 'modaction'


class PolicyViewJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = dict(
        body_html="body_html",
        display_rev="display_rev",
        revs="revs",
        toc_html="toc_html",
    )

    def kind(self, wrapped):
        return "Policy"

class KarmaListJsonTemplate(ThingJsonTemplate):
    def data(self, karmas):
        from r2.lib.template_helpers import (
            display_comment_karma, display_link_karma)
        karmas = [{
            'sr': sr,
            'link_karma': display_link_karma(link_karma),
            'comment_karma': display_comment_karma(comment_karma),
        } for sr, (link_karma, comment_karma) in karmas.iteritems()]
        return karmas

    def kind(self, wrapped):
        return "KarmaList"


def get_usertrophies(user):
    trophies = Trophy.by_account(user)
    def visible_trophy(trophy):
        return trophy._thing2.awardtype != 'invisible'
    trophies = filter(visible_trophy, trophies)
    resp = TrophyListJsonTemplate().render(trophies)
    return resp.finalize()


class TrophyJsonTemplate(ThingJsonTemplate):
    _data_attrs_ = dict(
        award_id="award._id36",
        description="description",
        name="award.title",
        id="_id36",
        icon_40="icon_40",
        icon_70="icon_70",
        url="trophy_url",
    )

    def thing_attr(self, thing, attr):
        if attr == "icon_40":
            return "https:" + thing._thing2.imgurl % 40
        elif attr == "icon_70":
            return "https:" + thing._thing2.imgurl % 70
        rel_attr, splitter, attr = attr.partition(".")
        if attr:
            return ThingJsonTemplate.thing_attr(self, thing._thing2, attr)
        else:
            return ThingJsonTemplate.thing_attr(self, thing, rel_attr)

    def kind(self, thing):
        return ThingJsonTemplate.kind(self, thing._thing2)

class TrophyListJsonTemplate(ThingJsonTemplate):
    def data(self, trophies):
        trophies = [Wrapped(t).render() for t in trophies]
        return dict(trophies=trophies)

    def kind(self, wrapped):
        return "TrophyList"
