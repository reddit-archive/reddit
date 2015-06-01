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

from r2.config import feature
from r2.lib.db.thing import NotFound
from r2.lib.menus import (
  JsButton,
  NavButton,
  NavMenu,
  Styled,
)
from r2.lib.wrapped import Wrapped
from r2.models import LinkListing, Link, PromotedLink, Report
from r2.models import make_wrapper, IDBuilder, Thing
from r2.lib.utils import tup
from r2.lib.strings import Score
from r2.lib.promote import *
from datetime import datetime
from pylons import c, g
from pylons.i18n import _, ungettext

class PrintableButtons(Styled):
    cachable = False

    def __init__(self, style, thing,
                 show_delete = False, show_report = True,
                 show_distinguish = False, show_marknsfw = False,
                 show_unmarknsfw = False, is_link=False,
                 show_flair=False, show_rescrape=False,
                 show_givegold=False, **kw):
        show_ignore = thing.show_reports
        approval_checkmark = getattr(thing, "approval_checkmark", None)
        show_approve = (thing.show_spam or show_ignore or
                        (is_link and approval_checkmark is None)) and not thing._deleted

        show_new_post_sharing = feature.is_enabled('improved_sharing')

        Styled.__init__(self, style = style,
                        thing = thing,
                        fullname = thing._fullname,
                        can_ban = thing.can_ban,
                        show_spam = thing.show_spam,
                        show_reports = thing.show_reports,
                        show_ignore = show_ignore,
                        approval_checkmark = approval_checkmark,
                        show_delete = show_delete,
                        show_approve = show_approve,
                        show_report = show_report,
                        show_distinguish = show_distinguish,
                        show_marknsfw = show_marknsfw,
                        show_unmarknsfw = show_unmarknsfw,
                        show_flair = show_flair,
                        show_rescrape=show_rescrape,
                        show_givegold=show_givegold,
                        show_new_post_sharing=show_new_post_sharing,
                        **kw)
        
class BanButtons(PrintableButtons):
    def __init__(self, thing,
                 show_delete = False, show_report = True):
        PrintableButtons.__init__(self, "banbuttons", thing)

class LinkButtons(PrintableButtons):
    def __init__(self, thing, comments = True, delete = True, report = True):
        # is the current user the author?
        is_author = (c.user_is_loggedin and thing.author and
                     c.user.name == thing.author.name)
        # do we show the report button?
        show_report = not is_author and report

        # if they are the author, can they edit it?
        thing_editable = getattr(thing, 'editable', True)
        thing_takendown = getattr(thing, 'admin_takedown', False)
        editable = is_author and thing_editable and not thing_takendown

        show_marknsfw = show_unmarknsfw = False
        show_rescrape = False
        if thing.can_ban or is_author or (thing.promoted and c.user_is_sponsor):
            if not thing.nsfw:
                show_marknsfw = True
            elif thing.nsfw and not thing.nsfw_str:
                show_unmarknsfw = True

            if (not thing.is_self and
                    not (thing.has_thumbnail or thing.media_object)):
                show_rescrape = True
        show_givegold = thing.can_gild and (c.permalink_page or c.profilepage)

        # do we show the delete button?
        show_delete = is_author and delete and not thing._deleted
        # disable the delete button for live sponsored links
        if (is_promoted(thing) and not c.user_is_sponsor):
            show_delete = False

        # do we show the distinguish button? among other things,
        # we never want it to appear on link listings -- only
        # comments pages
        show_distinguish = (is_author and
                            (thing.can_ban or  # Moderator distinguish
                             c.user.employee or  # Admin distinguish
                             c.user_special_distinguish)
                            and getattr(thing, "expand_children", False))

        kw = {}
        if thing.promoted is not None:
            now = datetime.now(g.tz)
            kw = dict(promo_url = promo_edit_url(thing),
                      promote_status = getattr(thing, "promote_status", 0),
                      user_is_sponsor = c.user_is_sponsor,
                      traffic_url = promo_traffic_url(thing),
                      is_author = thing.is_author,
                      )

            if c.user_is_sponsor:
                kw["is_awaiting_fraud_review"] = is_awaiting_fraud_review(thing)
                kw["payment_flagged_reason"] = thing.payment_flagged_reason
                kw["hide_after_seen"] = getattr(thing, "hide_after_seen", False)

        PrintableButtons.__init__(self, 'linkbuttons', thing, 
                                  # user existence and preferences
                                  is_loggedin = c.user_is_loggedin,
                                  # comment link params
                                  comment_label = thing.comment_label,
                                  commentcls = thing.commentcls,
                                  permalink  = thing.permalink,
                                  # button visibility
                                  saved = thing.saved,
                                  editable = editable, 
                                  hidden = thing.hidden, 
                                  ignore_reports = thing.ignore_reports,
                                  show_delete = show_delete,
                                  show_report = show_report and c.user_is_loggedin,
                                  mod_reports=thing.mod_reports,
                                  user_reports=thing.user_reports,
                                  show_distinguish = show_distinguish,
                                  show_marknsfw = show_marknsfw,
                                  show_unmarknsfw = show_unmarknsfw,
                                  show_flair = thing.can_flair,
                                  show_rescrape=show_rescrape,
                                  show_givegold=show_givegold,
                                  show_comments = comments,
                                  # promotion
                                  promoted = thing.promoted,
                                  is_link = True,
                                  **kw)

class CommentButtons(PrintableButtons):
    def __init__(self, thing, delete = True, report = True):
        # is the current user the author?
        is_author = thing.is_author

        # if they are the author, can they edit it?
        thing_editable = getattr(thing, 'editable', True)
        thing_takendown = getattr(thing, 'admin_takedown', False)
        editable = is_author and thing_editable and not thing_takendown

        # do we show the report button?
        show_report = not is_author and report and thing.can_reply
        # do we show the delete button?
        show_delete = is_author and delete and not thing._deleted
        suppress_reply_buttons = getattr(thing, 'suppress_reply_buttons', False)

        show_distinguish = (is_author and
                            (thing.can_ban or  # Moderator distinguish
                             c.user.employee or  # Admin distinguish
                             c.user_special_distinguish))

        show_givegold = thing.can_gild

        embed_button = False

        from r2.lib import embeds
        if thing.can_embed and embeds.embeddable_sr(thing):
            embed_button = JsButton("embed",
                css_class="embed-comment",
                data={
                    "media": g.media_domain or g.domain,
                    "comment": thing.permalink,
                    "link": thing.link.make_permalink(thing.subreddit),
                    "title": thing.link.title,
                    "root": ("true" if thing.parent_id is None else "false"),
                })

            embed_button.build()

        PrintableButtons.__init__(self, "commentbuttons", thing,
                                  is_author = is_author, 
                                  profilepage = c.profilepage,
                                  permalink = thing.permalink,
                                  saved = thing.saved,
                                  editable = editable,
                                  ignore_reports = thing.ignore_reports,
                                  full_comment_path = thing.full_comment_path,
                                  full_comment_count = thing.full_comment_count,
                                  deleted = thing.deleted,
                                  parent_permalink = thing.parent_permalink, 
                                  can_reply = thing.can_reply,
                                  suppress_reply_buttons = suppress_reply_buttons,
                                  show_report=show_report,
                                  mod_reports=thing.mod_reports,
                                  user_reports=thing.user_reports,
                                  show_distinguish = show_distinguish,
                                  show_delete = show_delete,
                                  show_givegold=show_givegold,
                                  embed_button=embed_button,
        )

class MessageButtons(PrintableButtons):
    def __init__(self, thing, delete = False, report = True):
        was_comment = getattr(thing, 'was_comment', False)
        permalink = thing.permalink
        # don't allow replying to self unless it's modmail
        valid_recipient = (thing.author_id != c.user._id or
                           thing.sr_id)
        can_reply = (c.user_is_loggedin and
                     getattr(thing, "repliable", True) and
                     valid_recipient)
        can_block = True

        if not thing.was_comment and thing.display_author:
            can_block = False

        # Allow comment-reply messages to have links to the full thread.
        if was_comment:
            self.full_comment_path = thing.link_permalink
            self.full_comment_count = thing.full_comment_count

        PrintableButtons.__init__(self, "messagebuttons", thing,
                                  profilepage = c.profilepage,
                                  permalink = permalink,
                                  was_comment = was_comment,
                                  unread = thing.new,
                                  user_is_recipient = thing.user_is_recipient,
                                  can_reply = can_reply,
                                  parent_id = getattr(thing, "parent_id", None),
                                  show_report = True,
                                  show_delete = False,
                                  can_block = can_block,
                                 )

# formerly ListingController.builder_wrapper
def default_thing_wrapper(**params):
    def _default_thing_wrapper(thing):
        w = Wrapped(thing)
        style = params.get('style', c.render_style)
        if isinstance(thing, Link):
            if thing.promoted is not None:
                w.render_class = PromotedLink
            elif style == 'htmllite':
                w.score_fmt = Score.safepoints
            w.should_incr_counts = style != 'htmllite'
        return w
    params['parent_wrapper'] = _default_thing_wrapper
    return make_wrapper(**params)

# TODO: move this into lib somewhere?
def wrap_links(links, wrapper = default_thing_wrapper(),
               listing_cls = LinkListing, 
               num = None, show_nums = False, nextprev = False, **kw):
    links = tup(links)
    if not all(isinstance(x, basestring) for x in links):
        links = [x._fullname for x in links]
    b = IDBuilder(links, num = num, wrap = wrapper, **kw)
    l = listing_cls(b, nextprev = nextprev, show_nums = show_nums)
    return l.listing()


def hot_links_by_url_listing(url, sr=None, num=None, **kw):
    try:
        links_for_url = Link._by_url(url, sr)
    except NotFound:
        links_for_url = []

    links_for_url.sort(key=lambda link: link._hot, reverse=True)
    listing = wrap_links(links_for_url, num=num, **kw)
    return listing


def wrap_things(*things):
    """Instantiate Wrapped for each thing, calling add_props if available."""
    if not things:
        return []

    wrapped = [Wrapped(thing) for thing in things]
    if hasattr(things[0], 'add_props'):
        # assume all things are of the same type and use the first thing's
        # add_props to process the list.
        things[0].add_props(c.user, wrapped)
    return wrapped
