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

from r2.lib.menus import Styled
from r2.lib.wrapped import Wrapped
from r2.models import LinkListing, Link, PromotedLink
from r2.models import make_wrapper, IDBuilder, Thing
from r2.lib.utils import tup
from r2.lib.strings import Score
from r2.lib.promote import *
from datetime import datetime
from pylons import c, g
from pylons.i18n import _, ungettext

class PrintableButtons(Styled):
    def __init__(self, style, thing,
                 show_delete = False, show_report = True,
                 show_distinguish = False, show_marknsfw = False,
                 show_unmarknsfw = False, is_link=False,
                 show_flair = False, **kw):
        show_ignore = thing.show_reports
        approval_checkmark = getattr(thing, "approval_checkmark", None)
        show_approve = (thing.show_spam or show_ignore or
                        (is_link and approval_checkmark is None)) and not thing._deleted

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
        show_report = (not is_author and
                       report and
                       getattr(thing, "promoted", None) is None)

        if c.user_is_admin and thing.promoted is None:
            show_report = False

        if (thing.can_ban or is_author) and not thing.nsfw:
            show_marknsfw = True
        else:
            show_marknsfw = False

        if (thing.can_ban or is_author) and thing.nsfw and not thing.nsfw_str:
            show_unmarknsfw = True
        else:
            show_unmarknsfw = False

        # do we show the delete button?
        show_delete = is_author and delete and not thing._deleted
        # disable the delete button for live sponsored links
        if (is_promoted(thing) and not c.user_is_sponsor):
            show_delete = False

        # do we show the distinguish button? among other things,
        # we never want it to appear on link listings -- only
        # comments pages
        show_distinguish = (is_author and (thing.can_ban or c.user_special_distinguish)
                            and getattr(thing, "expand_children", False))

        kw = {}
        if thing.promoted is not None:
            now = datetime.now(g.tz)
            kw = dict(promo_url = promo_edit_url(thing),
                      promote_status = getattr(thing, "promote_status", 0),
                      user_is_sponsor = c.user_is_sponsor,
                      traffic_url = promo_traffic_url(thing), 
                      is_author = thing.is_author)

        PrintableButtons.__init__(self, 'linkbuttons', thing, 
                                  # user existence and preferences
                                  is_loggedin = c.user_is_loggedin,
                                  new_window = c.user.pref_newwindow,
                                  # comment link params
                                  comment_label = thing.comment_label,
                                  commentcls = thing.commentcls,
                                  permalink  = thing.permalink,
                                  # button visibility
                                  saved = thing.saved,
                                  editable = thing.editable, 
                                  hidden = thing.hidden, 
                                  ignore_reports = thing.ignore_reports,
                                  show_delete = show_delete,
                                  show_report = show_report and c.user_is_loggedin,
                                  show_distinguish = show_distinguish,
                                  show_marknsfw = show_marknsfw,
                                  show_unmarknsfw = show_unmarknsfw,
                                  show_flair = thing.can_flair,
                                  show_comments = comments,
                                  # promotion
                                  promoted = thing.promoted,
                                  is_link = True,
                                  **kw)

class CommentButtons(PrintableButtons):
    def __init__(self, thing, delete = True, report = True):
        # is the current user the author?
        is_author = thing.is_author
        # do we show the report button?
        show_report = not is_author and report and thing.can_reply
        # do we show the delete button?
        show_delete = is_author and delete and not thing._deleted

        can_gild = (
            # you can't gild your own comment
            not is_author
            # no point in showing the button for things you've already gilded
            and not thing.user_gilded
            # this is a way of checking if the user is logged in that works
            # both within CommentPane instances and without.  e.g. CommentPane
            # explicitly sets user_is_loggedin = False but can_reply is
            # correct.  while on user overviews, you can't reply but will get
            # the correct value for user_is_loggedin
            and (c.user_is_loggedin or thing.can_reply)
            # ick, if the author deleted their account we shouldn't waste gold
            and not thing.author._deleted
            # some subreddits can have gilding disabled
            and thing.subreddit.allow_comment_gilding
        )

        show_distinguish = is_author and (thing.can_ban or c.user_special_distinguish)

        PrintableButtons.__init__(self, "commentbuttons", thing,
                                  is_author = is_author, 
                                  profilepage = c.profilepage,
                                  permalink = thing.permalink,
                                  saved = thing.saved,
                                  ignore_reports = thing.ignore_reports,
                                  new_window = c.user.pref_newwindow,
                                  full_comment_path = thing.full_comment_path,
                                  full_comment_count = thing.full_comment_count,
                                  deleted = thing.deleted,
                                  parent_permalink = thing.parent_permalink, 
                                  can_reply = thing.can_reply,
                                  can_gild=can_gild,
                                  show_report = show_report,
                                  show_distinguish = show_distinguish,
                                  show_delete = show_delete)

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

        PrintableButtons.__init__(self, "messagebuttons", thing,
                                  profilepage = c.profilepage,
                                  permalink = permalink,
                                  was_comment = was_comment,
                                  unread = thing.new,
                                  recipient = thing.recipient,
                                  can_reply = can_reply,
                                  parent_id = getattr(thing, "parent_id", None),
                                  show_report = True,
                                  show_delete = False)

# formerly ListingController.builder_wrapper
def default_thing_wrapper(**params):
    def _default_thing_wrapper(thing):
        w = Wrapped(thing)
        style = params.get('style', c.render_style)
        if isinstance(thing, Link):
            if thing.promoted is not None:
                w.render_class = PromotedLink
                w.rowstyle = 'promoted link'
            elif style == 'htmllite':
                w.score_fmt = Score.points
        return w
    params['parent_wrapper'] = _default_thing_wrapper
    return make_wrapper(**params)

# TODO: move this into lib somewhere?
def wrap_links(links, wrapper = default_thing_wrapper(),
               listing_cls = LinkListing, 
               num = None, show_nums = False, nextprev = False,
               num_margin = None, mid_margin = None, **kw):
    links = tup(links)
    if not all(isinstance(x, basestring) for x in links):
        links = [x._fullname for x in links]
    b = IDBuilder(links, num = num, wrap = wrapper, **kw)
    l = listing_cls(b, nextprev = nextprev, show_nums = show_nums)
    if num_margin is not None:
        l.num_margin = num_margin
    if mid_margin is not None:
        l.mid_margin = mid_margin
    return l.listing()


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
