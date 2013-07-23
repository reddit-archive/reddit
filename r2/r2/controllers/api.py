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

from r2.controllers.reddit_base import (
    cross_domain,
    MinimalController,
    pagecache_policy,
    PAGECACHE_POLICY,
    paginated_listing,
    RedditController,
    set_user_cookie,
)

from pylons.i18n import _
from pylons import c, request, response

from r2.lib.validator import *

from r2.models import *

from r2.lib import amqp

from r2.lib.utils import get_title, sanitize_url, timeuntil, set_last_modified
from r2.lib.utils import query_string, timefromnow, randstr
from r2.lib.utils import timeago, tup, filter_links
from r2.lib.pages import (EnemyList, FriendList, ContributorList, ModList,
                          BannedList, WikiBannedList, WikiMayContributeList,
                          BoringPage, FormPage, CssError, UploadedImage,
                          ClickGadget, UrlParser, WrappedUser)
from r2.lib.pages import FlairList, FlairCsv, FlairTemplateEditor, \
    FlairSelector
from r2.lib.pages import PrefApps
from r2.lib.pages.things import wrap_links, default_thing_wrapper
from r2.models.last_modified import LastModified

from r2.lib.menus import CommentSortMenu
from r2.lib.captcha import get_iden
from r2.lib.strings import strings
from r2.lib.filters import _force_unicode, websafe_json, websafe, spaceCompress
from r2.lib.db import queries
from r2.lib.db.queries import changed
from r2.lib import media
from r2.lib.db import tdb_cassandra
from r2.lib import promote
from r2.lib.comment_tree import delete_comment
from r2.lib import tracking,  cssfilter, emailer
from r2.lib.subreddit_search import search_reddits
from r2.lib.log import log_text
from r2.lib.filters import safemarkdown
from r2.lib.scraper import str_to_image
from r2.controllers.api_docs import api_doc, api_section
from r2.lib.search import SearchQuery
from r2.controllers.oauth2 import OAuth2ResourceController, require_oauth2_scope
from r2.lib.template_helpers import add_sr, get_domain
from r2.lib.system_messages import notify_user_added
from r2.controllers.ipn import generate_blob
from r2.lib.lock import TimeoutExpired

from r2.models import wiki
from r2.lib.merge import ConflictException

import csv
from collections import defaultdict
from datetime import datetime, timedelta
import hashlib
import re
import urllib
import urllib2

def reject_vote(thing):
    voteword = request.params.get('dir')

    if voteword == '1':
        voteword = 'upvote'
    elif voteword == '0':
        voteword = '0-vote'
    elif voteword == '-1':
        voteword = 'downvote'

    log_text ("rejected vote", "Rejected %s from %s (%s) on %s %s via %s" %
              (voteword, c.user.name, request.ip, thing.__class__.__name__,
               thing._id36, request.referer), "info")


class ApiminimalController(MinimalController):
    """
    Put API calls in here which don't rely on the user being logged in
    """

    @validatedForm()
    @api_doc(api_section.captcha)
    def POST_new_captcha(self, form, jquery, *a, **kw):
        """
        Responds with an `iden` of a new CAPTCHA

        Use this endpoint if a user cannot read a given CAPTCHA,
        and wishes to receive a new CAPTCHA.

        To request the CAPTCHA image for an iden, use
        [/captcha/`iden`](#GET_captcha_{iden}).
        """

        iden = get_iden()
        jquery("body").captcha(iden)
        form._send_data(iden = iden) 


class ApiController(RedditController, OAuth2ResourceController):
    """
    Controller which deals with almost all AJAX site interaction.  
    """

    def pre(self):
        self.check_for_bearer_token()
        RedditController.pre(self)

    @validatedForm()
    def ajax_login_redirect(self, form, jquery, dest):
        form.redirect("/login" + query_string(dict(dest=dest)))

    @pagecache_policy(PAGECACHE_POLICY.NEVER)
    @require_oauth2_scope("read")
    @validate(link1 = VUrl(['url']),
              link2 = VByName('id'),
              count = VLimit('limit'))
    @api_doc(api_section.links_and_comments)
    def GET_info(self, link1, link2, count):
        """Get a link by fullname or a list of links by URL.

        If `id` is provided, the link with the given fullname will be returned.
        If `url` is provided, a list of links with the given URL will be
        returned.

        If both `url` and `id` are provided, `id` will take precedence.

        """

        c.update_last_visit = False

        links = []
        if link2:
            links = filter_links(tup(link2), filter_spam = False)
        elif link1 and ('ALREADY_SUB', 'url')  in c.errors:
            links = filter_links(tup(link1), filter_spam = False)

        listing = wrap_links(filter(None, links or []), num = count)
        return BoringPage(_("API"), content = listing).render()


    @json_validate()
    @api_doc(api_section.account, extensions=["json"])
    def GET_me(self, responder):
        """Get info about the currently authenticated user.

        Response includes a modhash, karma, and new mail status.

        """
        if c.user_is_loggedin:
            return Wrapped(c.user).render()
        else:
            return {}

    @json_validate(user=VUname(("user",)))
    @api_doc(api_section.users, extensions=["json"])
    def GET_username_available(self, responder, user):
        """
        Check whether a username is available for registration.
        """
        if not (responder.has_errors("user", errors.BAD_USERNAME)):
            return bool(user)

    @json_validate()
    @api_doc(api_section.captcha, extensions=["json"])
    def GET_needs_captcha(self, responder):
        """
        Check whether CAPTCHAs are needed for API methods that define the
        "captcha" and "iden" parameters.
        """
        return bool(c.user.needs_captcha())

    @validatedForm(VCaptcha(),
                   name=VRequired('name', errors.NO_NAME),
                   email=ValidEmails('email', num = 1),
                   reason = VOneOf('reason', ('ad_inq', 'feedback')),
                   message=VRequired('text', errors.NO_TEXT),
                   )
    def POST_feedback(self, form, jquery, name, email, reason, message):
        if not (form.has_errors('name',     errors.NO_NAME) or
                form.has_errors('email',    errors.BAD_EMAILS) or
                form.has_errors('text', errors.NO_TEXT) or
                form.has_errors('captcha', errors.BAD_CAPTCHA)):

            if reason == 'ad_inq':
                emailer.ad_inq_email(email, message, name, reply_to = '')
            else:
                emailer.feedback_email(email, message, name, reply_to = '')
            form.set_html(".status", _("thanks for your message! "
                            "you should hear back from us shortly."))
            form.set_inputs(text = "", captcha = "")
            form.find(".spacer").hide()
            form.find(".btn").hide()

    POST_ad_inq = POST_feedback

    @require_oauth2_scope("privatemessages")
    @validatedForm(VCaptcha(),
                   VUser(),
                   VModhash(),
                   ip = ValidIP(),
                   to = VMessageRecipient('to'),
                   subject = VLength('subject', 100, empty_error=errors.NO_SUBJECT),
                   body = VMarkdown(['text', 'message']))
    @api_doc(api_section.messages)
    def POST_compose(self, form, jquery, to, subject, body, ip):
        """
        handles message composition under /message/compose.
        """
        if not (form.has_errors("to",  errors.USER_DOESNT_EXIST,
                                errors.NO_USER, errors.SUBREDDIT_NOEXIST,
                                errors.USER_BLOCKED) or
                form.has_errors("subject", errors.NO_SUBJECT) or
                form.has_errors("subject", errors.TOO_LONG) or
                form.has_errors("text", errors.NO_TEXT, errors.TOO_LONG) or
                form.has_errors("captcha", errors.BAD_CAPTCHA)):

            m, inbox_rel = Message._new(c.user, to, subject, body, ip)
            form.set_html(".status", _("your message has been delivered"))
            form.set_inputs(to = "", subject = "", text = "", captcha="")

            amqp.add_item('new_message', m._fullname)

            queries.new_message(m, inbox_rel)

    @require_oauth2_scope("submit")
    @validatedForm(VUser(),
                   VModhash(),
                   VCaptcha(),
                   VRatelimit(rate_user = True, rate_ip = True,
                              prefix = "rate_submit_"),
                   VShamedDomain('url'),
                   ip = ValidIP(),
                   sr = VSubmitSR('sr', 'kind'),
                   url = VUrl(['url', 'sr', 'resubmit']),
                   title = VTitle('title'),
                   save = VBoolean('save'),
                   sendreplies = VBoolean('sendreplies'),
                   selftext = VSelfText('text'),
                   kind = VOneOf('kind', ['link', 'self']),
                   then = VOneOf('then', ('tb', 'comments'),
                                 default='comments'),
                   extension=VLength("extension", 20, docs={"extension":
                       "extension used for redirects"}),
                  )
    @api_doc(api_section.links_and_comments)
    def POST_submit(self, form, jquery, url, selftext, kind, title,
                    save, sr, ip, then, extension, sendreplies):
        """Submit a link to a subreddit.

        Submit will create a link or self-post in the subreddit `sr` with the
        title `title`. If `kind` is `"link"`, then `url` is expected to be a
        valid URL to link to. Otherwise, `text`, if present, will be the
        body of the self-post.

        If a link with the same URL has already been submitted to the specified
        subreddit an error will be returned unless `resubmit` is true.
        `extension` is used for determining which view-type (e.g. `json`,
        `compact` etc.) to use for the redirect that is generated if the
        `resubmit` error occurs.

        If `save` is true, the link will be implicitly saved after submission
        (see [/api/save](#POST_api_save) for more information).

        """

        from r2.models.admintools import is_banned_domain

        if isinstance(url, (unicode, str)):
            #backwards compatability
            if url.lower() == 'self':
                url = kind = 'self'

            # VUrl may have replaced 'url' by adding 'http://'
            form.set_inputs(url = url)

        if not kind or form.has_errors('sr', errors.INVALID_OPTION):
            # this should only happen if somebody is trying to post
            # links in some automated manner outside of the regular
            # submission page, and hasn't updated their script
            return

        if form.has_errors('captcha', errors.BAD_CAPTCHA):
            return

        if (form.has_errors('sr',
                            errors.SUBREDDIT_NOEXIST,
                            errors.SUBREDDIT_NOTALLOWED,
                            errors.SUBREDDIT_REQUIRED,
                            errors.NO_SELFS,
                            errors.NO_LINKS)
            or not sr):
            # checking to get the error set in the form, but we can't
            # check for rate-limiting if there's no subreddit
            return

        if sr.link_type == 'link' and kind == 'self':
            # this could happen if they actually typed "self" into the
            # URL box and we helpfully translated it for them
            c.errors.add(errors.NO_SELFS, field='sr')

            # and trigger that by hand for the form
            form.has_errors('sr', errors.NO_SELFS)

            return

        should_ratelimit = sr.should_ratelimit(c.user, 'link')
        #remove the ratelimit error if the user's karma is high
        if not should_ratelimit:
            c.errors.remove((errors.RATELIMIT, 'ratelimit'))

        banmsg = None

        if kind == 'link':
            check_domain = True

            # check for no url, or clear that error field on return
            if form.has_errors("url", errors.NO_URL, errors.BAD_URL):
                pass
            elif form.has_errors("url", errors.DOMAIN_BANNED):
                g.stats.simple_event('spam.shame.link')
            elif form.has_errors("url", errors.ALREADY_SUB):
                check_domain = False
                u = url[0].already_submitted_link
                if extension:
                    u = UrlParser(u)
                    u.set_extension(extension)
                    u = u.unparse()
                form.redirect(u)
            # check for title, otherwise look it up and return it
            elif form.has_errors("title", errors.NO_TEXT):
                pass

            if url is None:
                g.log.warning("%s is trying to submit url=None (title: %r)"
                              % (request.ip, title))
            elif check_domain:
                banmsg = is_banned_domain(url)
        else:
            form.has_errors('text', errors.TOO_LONG)

        if form.has_errors("title", errors.TOO_LONG, errors.NO_TEXT):
            pass

        if form.has_errors('ratelimit', errors.RATELIMIT):
            pass

        if form.has_error() or not title:
            return

        if should_ratelimit:
            filled_quota = c.user.quota_full('link')
            if filled_quota is not None:
                if c.user._spam:
                    msg = strings.generic_quota_msg
                else:
                    log_text ("over-quota",
                              "%s just went over their per-%s quota" %
                              (c.user.name, filled_quota), "info")

                    verify_link = "/verify?reason=submit"
                    reddiquette_link = "/wiki/reddiquette" 

                    if c.user.email_verified:
                        msg = strings.verified_quota_msg % dict(reddiquette=reddiquette_link)
                    else:
                        msg = strings.unverified_quota_msg % dict(verify=verify_link,
                                                                  reddiquette=reddiquette_link)

                md = safemarkdown(msg)
                form.set_html(".status", md)
                c.errors.add(errors.QUOTA_FILLED)
                form.set_error(errors.QUOTA_FILLED, None)
                return

        if not c.user.gold or not hasattr(request.post, 'sendreplies'):
            sendreplies = kind == 'self'

        # get rid of extraneous whitespace in the title
        cleaned_title = re.sub(r'\s+', ' ', request.post.title, flags=re.UNICODE)
        cleaned_title = cleaned_title.strip()

        # well, nothing left to do but submit it
        l = Link._submit(cleaned_title, url if kind == 'link' else 'self',
                         c.user, sr, ip, spam=c.user._spam, sendreplies=sendreplies)

        if banmsg:
            g.stats.simple_event('spam.domainban.link_url')
            admintools.spam(l, banner = "domain (%s)" % banmsg)

        if kind == 'self':
            l.url = l.make_permalink_slow()
            l.is_self = True
            l.selftext = selftext

            l._commit()
            l.set_url_cache()

        queries.queue_vote(c.user, l, True, ip,
                           cheater = (errors.CHEATER, None) in c.errors)
        if save:
            r = l._save(c.user)

        #set the ratelimiter
        if should_ratelimit:
            c.user.clog_quota('link', l)
            VRatelimit.ratelimit(rate_user=True, rate_ip = True,
                                 prefix = "rate_submit_")

        #update the queries
        queries.new_link(l)
        changed(l)

        if then == 'comments':
            path = add_sr(l.make_permalink_slow())
        elif then == 'tb':
            form.attr('target', '_top')
            path = add_sr('/tb/%s' % l._id36)
        if extension:
            path += ".%s" % extension
        form.redirect(path)
        form._send_data(url=path)
        form._send_data(id=l._id36)
        form._send_data(name=l._fullname)

    @validatedForm(VRatelimit(rate_ip = True,
                              rate_user = True,
                              prefix = 'fetchtitle_'),
                   VUser(),
                   url = VSanitizedUrl('url'))
    def POST_fetch_title(self, form, jquery, url):
        if form.has_errors('ratelimit', errors.RATELIMIT):
            form.set_html(".title-status", "");
            return

        VRatelimit.ratelimit(rate_ip = True, rate_user = True,
                             prefix = 'fetchtitle_', seconds=1)
        if url:
            title = get_title(url)
            if title:
                form.set_inputs(title = title)
                form.set_html(".title-status", "");
            else:
                form.set_html(".title-status", _("no title found"))
        
    def _login(self, responder, user, rem = None):
        """
        AJAX login handler, used by both login and register to set the
        user cookie and send back a redirect.
        """
        self.login(user, rem = rem)

        if request.params.get("hoist") != "cookie":
            responder._send_data(modhash = user.modhash())
            responder._send_data(cookie  = user.make_cookie())

    @validatedForm(VLoggedOut(),
                   user = VThrottledLogin(['user', 'passwd']),
                   rem = VBoolean('rem'))
    def _handle_login(self, form, responder, user, rem):
        exempt_ua = (request.user_agent and
                     any(ua in request.user_agent for ua
                         in g.config.get('exempt_login_user_agents', ())))
        if (errors.LOGGED_IN, None) in c.errors:
            if user == c.user or exempt_ua:
                # Allow funky clients to re-login as the current user.
                c.errors.remove((errors.LOGGED_IN, None))
            else:
                from r2.lib.base import abort
                from r2.lib.errors import reddit_http_error
                abort(reddit_http_error(409, errors.LOGGED_IN))

        if not (responder.has_errors("vdelay", errors.RATELIMIT) or
                responder.has_errors("passwd", errors.WRONG_PASSWORD)):
            self._login(responder, user, rem)

    @cross_domain(allow_credentials=True)
    @api_doc(api_section.account, extends=_handle_login)
    def POST_login(self, *args, **kwargs):
        """Log in to an account.

        `rem` specifies whether or not the session cookie returned should last
        beyond the current browser session (that is, if `rem` is `True` the
        cookie will have an explicit expiration far in the future indicating
        that it is not a session cookie.)

        """
        return self._handle_login(*args, **kwargs)

    @validatedForm(VCaptcha(),
                   VRatelimit(rate_ip = True, prefix = "rate_register_"),
                   name = VUname(['user']),
                   email=ValidEmails(
                       "email",
                       num=1,
                       docs={
                           "email": "(optional) the user's email address",
                       },
                   ),
                   password = VPassword(['passwd', 'passwd2']),
                   rem = VBoolean('rem'))
    def _handle_register(self, form, responder, name, email,
                      password, rem):
        bad_captcha = responder.has_errors('captcha', errors.BAD_CAPTCHA)
        if not (responder.has_errors("user", errors.BAD_USERNAME,
                                errors.USERNAME_TAKEN_DEL,
                                errors.USERNAME_TAKEN) or
                responder.has_errors("email", errors.BAD_EMAILS) or
                responder.has_errors("passwd", errors.BAD_PASSWORD) or
                responder.has_errors("passwd2", errors.BAD_PASSWORD_MATCH) or
                responder.has_errors('ratelimit', errors.RATELIMIT) or
                (not g.disable_captcha and bad_captcha)):
            
            user = register(name, password, request.ip)
            VRatelimit.ratelimit(rate_ip = True, prefix = "rate_register_")

            #anything else we know (email, languages)?
            if email:
                user.email = email

            user.pref_lang = c.lang
            if c.content_langs == 'all':
                user.pref_content_langs = 'all'
            else:
                langs = list(c.content_langs)
                langs.sort()
                user.pref_content_langs = tuple(langs)

            d = c.user._dirties.copy()
            user._commit()

            amqp.add_item('new_account', user._fullname)

            c.user = user
            self._login(responder, user, rem)

    @cross_domain(allow_credentials=True)
    @api_doc(api_section.account, extends=_handle_register)
    def POST_register(self, *args, **kwargs):
        """Register a new account.

        `rem` specifies whether or not the session cookie returned should last
        beyond the current browser session (that is, if `rem` is `True` the
        cookie will have an explicit expiration far in the future indicating
        that it is not a session cookie.)

        """
        return self._handle_register(*args, **kwargs)

    @noresponse(VUser(),
                VModhash(),
                container = VByName('id'))
    @api_doc(api_section.moderation)
    def POST_leavemoderator(self, container):
        """
        Handles self-removal as moderator from a subreddit as rendered
        in the subreddit sidebox on any of that subreddit's pages.
        """
        if container and container.is_moderator(c.user):
            container.remove_moderator(c.user)
            ModAction.create(container, c.user, 'removemoderator', target=c.user, 
                             details='remove_self')

    @noresponse(VUser(),
                VModhash(),
                container = VByName('id'))
    @api_doc(api_section.moderation)
    def POST_leavecontributor(self, container):
        """
        same comment as for POST_leave_moderator.
        """
        if container and container.is_contributor(c.user):
            container.remove_contributor(c.user)


    _sr_friend_types = (
        'moderator',
        'moderator_invite',
        'contributor',
        'banned',
        'wikibanned',
        'wikicontributor',
    )

    _sr_friend_types_with_permissions = (
        'moderator',
        'moderator_invite',
    )

    @noresponse(VUser(),
                VModhash(),
                nuser = VExistingUname('name'),
                iuser = VByName('id'),
                container = nop('container'),
                type = VOneOf('type', ('friend', 'enemy') +
                                      _sr_friend_types))
    @api_doc(api_section.users)
    def POST_unfriend(self, nuser, iuser, container, type):
        """
        Handles removal of a friend (a user-user relation) or removal
        of a user's privileges from a subreddit (a user-subreddit
        relation).  The user can either be passed in by name (nuser)
        or by fullname (iuser).  If type is friend or enemy, 'container'
        will be the current user, otherwise the subreddit must be set.
        """
        if type in self._sr_friend_types:
            container = c.site
            if c.user._spam:
                return
        else:
            container = VByName('container').run(container)
            if not container:
                return

        # The user who made the request must be an admin or a moderator
        # for the privilege change to succeed.
        # (Exception: a user can remove privilege from oneself)
        victim = iuser or nuser
        required_perms = []
        if c.user != victim:
            if type.startswith('wiki'):
                required_perms.append('wiki')
            else:
                required_perms.append('access')
        if (not c.user_is_admin
            and (type in self._sr_friend_types
                 and not container.is_moderator_with_perms(
                     c.user, *required_perms))):
            abort(403, 'forbidden')
        if (type == 'moderator' and not
            (c.user_is_admin or container.can_demod(c.user, victim))):
            abort(403, 'forbidden')
        # if we are (strictly) unfriending, the container had better
        # be the current user.
        if type in ("friend", "enemy") and container != c.user:
            abort(403, 'forbidden')
        fn = getattr(container, 'remove_' + type)
        new = fn(victim)

        # Log this action
        if new and type in self._sr_friend_types:
            action = dict(banned='unbanuser', moderator='removemoderator',
                          moderator_invite='uninvitemoderator',
                          wikicontributor='removewikicontributor',
                          wikibanned='wikiunbanned',
                          contributor='removecontributor').get(type, None)
            ModAction.create(container, c.user, action, target=victim)

        if type == "friend" and c.user.gold:
            c.user.friend_rels_cache(_update=True)

    @validatedForm(VSrModerator(), VModhash(),
                   target=VExistingUname('name'),
                   type_and_permissions=VPermissions('type', 'permissions'))
    @api_doc(api_section.users)
    def POST_setpermissions(self, form, jquery, target, type_and_permissions):
        if form.has_errors('name', errors.USER_DOESNT_EXIST, errors.NO_USER):
            return
        if form.has_errors('type', errors.INVALID_PERMISSION_TYPE):
            return
        if form.has_errors('permissions', errors.INVALID_PERMISSIONS):
            return

        if c.user._spam:
            return

        type, permissions = type_and_permissions
        update = None

        if type in ("moderator", "moderator_invite"):
            if not c.user_is_admin:
                if type == "moderator" and (
                    c.user == target or not c.site.can_demod(c.user, target)):
                    abort(403, 'forbidden')
                if (type == "moderator_invite"
                    and not c.site.is_unlimited_moderator(c.user)):
                    abort(403, 'forbidden')
            if type == "moderator":
                rel = c.site.get_moderator(target)
            if type == "moderator_invite":
                rel = c.site.get_moderator_invite(target)
            rel.set_permissions(permissions)
            rel._commit()
            update = rel.encoded_permissions
            ModAction.create(c.site, c.user, action='setpermissions',
                             target=target, details='permission_' + type,
                             description=update)

        if update:
            row = form.closest('tr')
            editor = row.find('.permissions').data('PermissionEditor')
            editor.onCommit(update)

    @validatedForm(VUser(),
                   VModhash(),
                   ip = ValidIP(),
                   friend = VExistingUname('name'),
                   container = nop('container'),
                   type = VOneOf('type', ('friend',) + _sr_friend_types),
                   type_and_permissions = VPermissions('type', 'permissions'),
                   note = VLength('note', 300))
    @api_doc(api_section.users)
    def POST_friend(self, form, jquery, ip, friend,
                    container, type, type_and_permissions, note):
        """
        Complement to POST_unfriend: handles friending as well as
        privilege changes on subreddits.
        """
        if type in self._sr_friend_types:
            container = c.site
        else:
            container = VByName('container').run(container)
            if not container:
                return

        # Don't let banned users make subreddit access changes
        if type in self._sr_friend_types and c.user._spam:
            return

        if type == "moderator" and not c.user_is_admin:
            # attempts to add moderators now create moderator invites.
            type = "moderator_invite"

        fn = getattr(container, 'add_' + type)

        # Make sure the user making the request has the correct permissions
        # to be able to make this status change
        if type in self._sr_friend_types:
            if c.user_is_admin:
                has_perms = True
            elif type.startswith('wiki'):
                has_perms = container.is_moderator_with_perms(c.user, 'wiki')
            elif type == 'moderator_invite':
                has_perms = container.is_unlimited_moderator(c.user)
            else:
                has_perms = container.is_moderator_with_perms(c.user, 'access')

            if not has_perms:
                abort(403, 'forbidden')

        if type == 'moderator_invite':
            invites = sum(1 for i in container.each_moderator_invite())
            if invites >= g.sr_invite_limit:
                c.errors.add(errors.SUBREDDIT_RATELIMIT, field="name")
                form.set_error(errors.SUBREDDIT_RATELIMIT, "name")
                return

        if type in self._sr_friend_types and not c.user_is_admin:
            quota_key = "sr%squota-%s" % (str(type), container._id36)
            g.cache.add(quota_key, 0, time=g.sr_quota_time)
            subreddit_quota = g.cache.incr(quota_key)
            quota_limit = getattr(g, "sr_%s_quota" % type)
            if subreddit_quota > quota_limit and container.use_quotas:
                form.set_html(".status", errors.SUBREDDIT_RATELIMIT)
                c.errors.add(errors.SUBREDDIT_RATELIMIT)
                form.set_error(errors.SUBREDDIT_RATELIMIT, None)
                return

        # if we are (strictly) friending, the container
        # had better be the current user.
        if type == "friend" and container != c.user:
            abort(403,'forbidden')

        elif form.has_errors("name", errors.USER_DOESNT_EXIST, errors.NO_USER):
            return
        elif form.has_errors("note", errors.TOO_LONG):
            return

        if type in self._sr_friend_types_with_permissions:
            if form.has_errors('type', errors.INVALID_PERMISSION_TYPE):
                return
            if form.has_errors('permissions', errors.INVALID_PERMISSIONS):
                return
        else:
            permissions = None

        if type == "moderator_invite" and container.is_moderator(friend):
            c.errors.add(errors.ALREADY_MODERATOR, field="name")
            form.set_error(errors.ALREADY_MODERATOR, "name")
            return

        if type == "moderator":
            container.remove_moderator_invite(friend)

        new = fn(friend, permissions=type_and_permissions[1])

        # Log this action
        if new and type in self._sr_friend_types:
            action = dict(banned='banuser',
                          moderator='addmoderator',
                          moderator_invite='invitemoderator',
                          wikicontributor='wikicontributor',
                          contributor='addcontributor',
                          wikibanned='wikibanned').get(type, None)
            ModAction.create(container, c.user, action, target=friend)

        if type == "friend" and c.user.gold:
            # Yes, the order of the next two lines is correct.
            # First you recalculate the rel_ids, then you find
            # the right one and update its data.
            c.user.friend_rels_cache(_update=True)
            c.user.add_friend_note(friend, note or '')
        
        if type in ('banned', 'wikibanned'):
            container.add_rel_note(type, friend, note)

        cls = dict(friend=FriendList,
                   moderator=ModList,
                   moderator_invite=ModList,
                   contributor=ContributorList,
                   wikicontributor=WikiMayContributeList,
                   banned=BannedList, wikibanned=WikiBannedList).get(type)
        userlist = cls()
        form.set_inputs(name = "")
        if note:
            form.set_inputs(note = "")
        form.removeClass("edited")
        form.set_html(".status:first", userlist.executed_message(type))
        if new and cls:
            user_row = userlist.user_row(type, friend)
            jquery("." + type + "-table").show(
                ).find("table").insert_table_rows(user_row)

        if new:
            notify_user_added(type, c.user, friend, container)

    @validatedForm(VGold(),
                   friend = VExistingUname('name'),
                   note = VLength('note', 300))
    def POST_friendnote(self, form, jquery, friend, note):
        if form.has_errors("note", errors.TOO_LONG):
            return
        c.user.add_friend_note(friend, note)
        form.set_html('.status', _("saved"))

    @validatedForm(type = VOneOf('type', ('bannednote', 'wikibannednote')),
                   user = VExistingUname('name'),
                   note = VLength('note', 300))
    def POST_relnote(self, form, jquery, type, user, note):
        if form.has_errors("note", errors.TOO_LONG):
            return
        c.site.add_rel_note(type[:-4], user, note)
        form.set_html('.status', _("saved"))

    @validatedForm(VUser(),
                   VModhash(),
                   ip=ValidIP())
    @api_doc(api_section.subreddits)
    def POST_accept_moderator_invite(self, form, jquery, ip):
        rel = c.site.get_moderator_invite(c.user)
        if not c.site.remove_moderator_invite(c.user):
            c.errors.add(errors.NO_INVITE_FOUND)
            form.set_error(errors.NO_INVITE_FOUND, None)
            return

        permissions = rel.get_permissions()
        ModAction.create(c.site, c.user, "acceptmoderatorinvite")
        c.site.add_moderator(c.user, permissions=rel.get_permissions())
        notify_user_added("accept_moderator_invite", c.user, c.user, c.site)
        jquery.refresh()

    @json_validate(VUser(),
                   VGold(),
                   VModhash(),
                   deal=VLength('deal', 100))
    def POST_claim_gold_partner_deal_code(self, responder, deal):
        try:
            return {'code': GoldPartnerDealCode.claim_code(c.user, deal)}
        except GoldPartnerCodesExhaustedError:
            return {'error': 'GOLD_PARTNER_CODES_EXHAUSTED',
                    'explanation': _("sorry, we're out of codes!")}

    @validatedForm(VUser('curpass', default=''),
                   VModhash(),
                   password=VPassword(
                        ['curpass', 'curpass'],
                        docs=dict(curpass="the user's current password")
                   ),
                   dest = VDestination())
    @api_doc(api_section.account)
    def POST_clear_sessions(self, form, jquery, password, dest):
        """Clear all session cookies and replace the current one.

        A valid password (`curpass`) must be supplied.

        """
        # password is required to proceed
        if form.has_errors("curpass", errors.WRONG_PASSWORD):
            return

        form.set_html('.status',
                      _('all other sessions have been logged out'))
        form.set_inputs(curpass = "")

        # deauthorize all access tokens
        OAuth2AccessToken.revoke_all_by_user(c.user)
        OAuth2RefreshToken.revoke_all_by_user(c.user)

        # run the change password command to get a new salt
        change_password(c.user, password)
        # the password salt has changed, so the user's cookie has been
        # invalidated.  drop a new cookie.
        self.login(c.user)

    @validatedForm(VUser('curpass', default = ''),
                   VModhash(),
                   email = ValidEmails("email", num = 1),
                   password = VPassword(['newpass', 'verpass']),
                   verify = VBoolean("verify"))
    @api_doc(api_section.account)
    def POST_update(self, form, jquery, email, password, verify):
        """
        Update account email address and password.

        Called by /prefs/update on the site. For frontend form verification
        purposes, `newpass` and `verpass` must be equal for a password change
        to succeed.
        """
        # password is required to proceed
        if form.has_errors("curpass", errors.WRONG_PASSWORD):
            return
        
        # check if the email is valid.  If one is given and it is
        # different from the current address (or there is not one
        # currently) apply it
        updated = False
        if (not form.has_errors("email", errors.BAD_EMAILS) and
            email):
            if (not hasattr(c.user,'email') or c.user.email != email):
                if c.user.email_verified:
                    emailer.email_change_email(c.user)
                c.user.email = email
                # unverified email for now
                c.user.email_verified = None
                c.user._commit()
                Award.take_away("verified_email", c.user)
                updated = True
            if verify:
                # TODO: rate limit this?
                emailer.verify_email(c.user)
                form.set_html('.status',
                     _("you should be getting a verification email shortly."))
            else:
                form.set_html('.status', _('your email has been updated'))

        # user is removing their email
        if (not email and c.user.email and 
            (errors.NO_EMAILS, 'email') in c.errors):
            c.errors.remove((errors.NO_EMAILS, 'email'))
            c.user.email = ''
            c.user.email_verified = None
            c.user._commit()
            Award.take_away("verified_email", c.user)
            updated = True
            form.set_html('.status', _('your email has been updated'))

        # change password
        if (password and
            not (form.has_errors("newpass", errors.BAD_PASSWORD) or
                 form.has_errors("verpass", errors.BAD_PASSWORD_MATCH))):
            change_password(c.user, password)
            if c.user.email_verified:
                emailer.password_change_email(c.user)
            if updated:
                form.set_html(".status",
                              _('your email and password have been updated'))
            else:
                form.set_html('.status', 
                              _('your password has been updated'))
            form.set_inputs(curpass = "", newpass = "", verpass = "")
            # the password has changed, so the user's cookie has been
            # invalidated.  drop a new cookie.
            self.login(c.user)

    @validatedForm(VUser(),
                   VModhash(),
                   delete_message = VLength("delete_message", max_length=500),
                   username = VRequired("user", errors.NOT_USER),
                   user = VThrottledLogin(["user", "passwd"]),
                   confirm = VBoolean("confirm"))
    @api_doc(api_section.account)
    def POST_delete_user(self, form, jquery, delete_message, username, user, confirm):
        """Delete the currently logged in account.

        A valid username/password and confirmation must be supplied. An
        optional `delete_message` may be supplied to explain the reason the
        account is to be deleted.

        Called by /prefs/delete on the site.

        """
        if username and username.lower() != c.user.name.lower():
            c.errors.add(errors.NOT_USER, field="user")

        if not confirm:
            c.errors.add(errors.CONFIRM, field="confirm")

        if not (form.has_errors('vdelay', errors.RATELIMIT) or
                form.has_errors("user", errors.NOT_USER) or
                form.has_errors("passwd", errors.WRONG_PASSWORD) or
                form.has_errors("delete_message", errors.TOO_LONG) or
                form.has_errors("confirm", errors.CONFIRM)):
            c.user.delete(delete_message)
            form.redirect("/?deleted=true")

    @require_oauth2_scope("edit")
    @noresponse(VUser(),
                VModhash(),
                thing = VByNameIfAuthor('id'))
    @api_doc(api_section.links_and_comments)
    def POST_del(self, thing):
        """Delete a Link or Comment."""
        if not thing: return
        was_deleted = thing._deleted
        thing._deleted = True
        if (getattr(thing, "promoted", None) is not None and
            not promote.is_promoted(thing)):
            promote.reject_promotion(thing)
        thing._commit()

        # flag search indexer that something has changed
        changed(thing)

        #expire the item from the sr cache
        if isinstance(thing, Link):
            queries.delete(thing)

        #comments have special delete tasks
        elif isinstance(thing, Comment):
            parent_id = getattr(thing, 'parent_id', None)
            link_id = thing.link_id
            recipient = None

            if parent_id:
                parent_comment = Comment._byID(parent_id, data=True)
                recipient = Account._byID(parent_comment.author_id)
            else:
                parent_link = Link._byID(link_id, data=True)
                if parent_link.is_self:
                    recipient = Account._byID(parent_link.author_id)

            if not was_deleted:
                delete_comment(thing)

            if recipient:
                inbox_class = Inbox.rel(Account, Comment)
                d = inbox_class._fast_query(recipient, thing, ("inbox",
                                                               "selfreply",
                                                               "mention"))
                rels = filter(None, d.values()) or None
                queries.new_comment(thing, rels)

            queries.delete(thing)

    @require_oauth2_scope("modposts")
    @noresponse(VUser(),
                VModhash(),
                VSrCanAlter('id'),
                thing = VByName('id'))
    @api_doc(api_section.links_and_comments)
    def POST_marknsfw(self, thing):
        """Mark a link NSFW.

        See also: [/api/unmarknsfw](#POST_api_unmarknsfw).

        """
        thing.over_18 = True
        thing._commit()

        if c.user._id != thing.author_id:
            ModAction.create(thing.subreddit_slow, c.user, target=thing,
                             action='marknsfw')

        # flag search indexer that something has changed
        changed(thing)

    @require_oauth2_scope("modposts")
    @noresponse(VUser(),
                VModhash(),
                VSrCanAlter('id'),
                thing = VByName('id'))
    @api_doc(api_section.links_and_comments)
    def POST_unmarknsfw(self, thing):
        """Remove the NSFW marking from a link.

        See also: [/api/marknsfw](#POST_api_marknsfw).

        """
        thing.over_18 = False
        thing._commit()

        if c.user._id != thing.author_id:
            ModAction.create(thing.subreddit_slow, c.user, target=thing,
                             action='marknsfw', details='remove')

        # flag search indexer that something has changed
        changed(thing)

    @require_oauth2_scope("modposts")
    @validatedForm(VUser(),
                   VModhash(),
                   VSrCanBan('id'),
                   thing=VByName('id'),
                   state=VBoolean('state'))
    def POST_set_contest_mode(self, form, jquery, thing, state):
        thing.contest_mode = state
        thing._commit()
        jquery.refresh()

    @noresponse(VUser(), VModhash(),
                thing = VByName('id'))
    @api_doc(api_section.links_and_comments)
    def POST_report(self, thing):
        """Report a link or comment.

        Reporting a thing brings it to the attention of the subreddit's
        moderators. The thing is implicitly hidden as well (see
        [/api/hide](#POST_api_hide) for details).

        """
        if not thing or thing._deleted:
            return
        elif getattr(thing, 'promoted', False):
            return

        # if it is a message that is being reported, ban it.
        # every user is admin over their own personal inbox
        if isinstance(thing, Message):
            admintools.spam(thing, False, True, c.user.name)
        # auto-hide links that are reported
        elif isinstance(thing, Link):
            r = thing._hide(c.user)
        # TODO: be nice to be able to remove comments that are reported
        # from a user's inbox so they don't have to look at them.
        elif isinstance(thing, Comment):
            pass

        sr = getattr(thing, 'subreddit_slow', None)
        if (c.user._spam or
                c.user.ignorereports or
                (sr and sr.is_banned(c.user))):
            return
        Report.new(c.user, thing)
        admintools.report(thing)

    @require_oauth2_scope("privatemessages")
    @noresponse(VUser(), VModhash(),
                thing=VByName('id'))
    @api_doc(api_section.messages)
    def POST_block(self, thing):
        '''for blocking via inbox'''
        if not thing:
            return

        # Users may only block someone who has
        # actively harassed them (i.e., comment/link reply
        # or PM). Check that 'thing' is in the user's inbox somewhere
        inbox_cls = Inbox.rel(Account, thing.__class__)
        rels = inbox_cls._fast_query(c.user, thing,
                                     ("inbox", "selfreply", "mention"))
        if not filter(None, rels.values()):
            return

        block_acct = Account._byID(thing.author_id)
        if block_acct.name in g.admins:
            return
        c.user.add_enemy(block_acct)

    @require_oauth2_scope("edit")
    @validatedForm(VUser(),
                   VModhash(),
                   item = VByNameIfAuthor('thing_id'),
                   text = VSelfText('text'))
    @api_doc(api_section.links_and_comments)
    def POST_editusertext(self, form, jquery, item, text):
        """Edit the body text of a comment or self-post."""
        if (not form.has_errors("text",
                                errors.NO_TEXT, errors.TOO_LONG) and
            not form.has_errors("thing_id", errors.NOT_AUTHOR)):

            if isinstance(item, Comment):
                kind = 'comment'
                item.body = text
            elif isinstance(item, Link):
                kind = 'link'
                if not getattr(item, "is_self", False):
                    return abort(403, "forbidden")
                item.selftext = text
            else:
                g.log.warning("%s tried to edit usertext on %r", c.user, item)
                return

            if item._deleted:
                return abort(403, "forbidden")

            if (item._date < timeago('3 minutes')
                or (item._ups + item._downs > 2)):
                item.editted = c.start_time

            item.ignore_reports = False

            item._commit()

            changed(item)

            amqp.add_item('usertext_edited', item._fullname)

            if kind == 'link':
                set_last_modified(item, 'comments')
                LastModified.touch(item._fullname, 'Comments')

            wrapper = default_thing_wrapper(expand_children = True)
            jquery(".content").replace_things(item, True, True, wrap = wrapper)
            jquery(".content .link .rank").hide()

    @require_oauth2_scope("submit")
    @validatedForm(VUser(),
                   VModhash(),
                   VRatelimit(rate_user = True, rate_ip = True,
                              prefix = "rate_comment_"),
                   ip = ValidIP(),
                   parent = VSubmitParent(['thing_id', 'parent']),
                   comment = VMarkdown(['text', 'comment']))
    @api_doc(api_section.links_and_comments)
    def POST_comment(self, commentform, jquery, parent, comment, ip):
        """Submit a new comment or reply to a message.

        `parent` is the fullname of the thing being replied to. Its value
        changes the kind of object created by this request:

        * the fullname of a Link: a top-level comment in that Link's thread.
        * the fullname of a Comment: a comment reply to that comment.
        * the fullname of a Message: a message reply to that message.

        `text` should be the raw markdown body of the comment or message.

        To start a new message thread, use [/api/compose](#POST_api_compose).

        """
        should_ratelimit = True
        #check the parent type here cause we need that for the
        #ratelimit checks
        if isinstance(parent, Message):
            if not getattr(parent, "repliable", True):
                abort(403, 'forbidden')
            if not parent.can_view_slow():
                abort(403, 'forbidden')
            is_message = True
            should_ratelimit = False
        else:
            is_message = False
            is_comment = True
            if isinstance(parent, Link):
                link = parent
                parent_comment = None
            else:
                link = Link._byID(parent.link_id, data = True)
                parent_comment = parent
            sr = parent.subreddit_slow
            if ((link.is_self and link.author_id == c.user._id)
                or not sr.should_ratelimit(c.user, 'comment')):
                should_ratelimit = False
            parent_age = c.start_time - parent._date
            if not link.promoted and parent_age.days > g.REPLY_AGE_LIMIT:
                c.errors.add(errors.TOO_OLD, field = "parent")

        #remove the ratelimit error if the user's karma is high
        if not should_ratelimit:
            c.errors.remove((errors.RATELIMIT, 'ratelimit'))

        if (not commentform.has_errors("text",
                                       errors.NO_TEXT,
                                       errors.TOO_LONG) and
            not commentform.has_errors("ratelimit",
                                       errors.RATELIMIT) and
            not commentform.has_errors("parent",
                                       errors.DELETED_COMMENT,
                                       errors.DELETED_LINK,
                                       errors.TOO_OLD,
                                       errors.USER_BLOCKED)):

            if is_message:
                if parent.from_sr:
                    to = Subreddit._byID(parent.sr_id)
                else:
                    to = Account._byID(parent.author_id)
                subject = parent.subject
                re = "re: "
                if not subject.startswith(re):
                    subject = re + subject
                item, inbox_rel = Message._new(c.user, to, subject,
                                               comment, ip, parent = parent)
                item.parent_id = parent._id
            else:
                item, inbox_rel = Comment._new(c.user, link, parent_comment,
                                               comment, ip)
                queries.queue_vote(c.user, item, True, ip,
                                   cheater = (errors.CHEATER, None) in c.errors)

                # adding to comments-tree is done as part of
                # newcomments_q, so if they refresh immediately they
                # won't see their comment

            # clean up the submission form and remove it from the DOM (if reply)
            t = commentform.find("textarea")
            t.attr('rows', 3).html("").val("")
            if isinstance(parent, (Comment, Message)):
                commentform.remove()
                jquery.things(parent._fullname).set_html(".reply-button:first",
                                                         _("replied"))

            # insert the new comment
            jquery.insert_things(item)

            # remove any null listings that may be present
            jquery("#noresults").hide()

            #update the queries
            if is_message:
                queries.new_message(item, inbox_rel)
            else:
                queries.new_comment(item, inbox_rel)

            #set the ratelimiter
            if should_ratelimit:
                VRatelimit.ratelimit(rate_user=True, rate_ip = True,
                                     prefix = "rate_comment_")

    @validatedForm(VUser(),
                   VModhash(),
                   VCaptcha(),
                   VRatelimit(rate_user = True, rate_ip = True,
                              prefix = "rate_share_"),
                   share_from = VLength('share_from', max_length = 100),
                   emails = ValidEmailsOrExistingUnames("share_to"),
                   reply_to = ValidEmails("replyto", num = 1), 
                   message = VLength("message", max_length = 1000), 
                   thing = VByName('parent'),
                   ip = ValidIP())
    def POST_share(self, shareform, jquery, emails, thing, share_from, reply_to,
                   message, ip):

        # remove the ratelimit error if the user's karma is high
        sr = thing.subreddit_slow
        should_ratelimit = sr.should_ratelimit(c.user, 'link')
        if not should_ratelimit:
            c.errors.remove((errors.RATELIMIT, 'ratelimit'))

        # share_from and messages share a too_long error.
        # finding an error on one necessitates hiding the other error
        if shareform.has_errors("share_from", errors.TOO_LONG):
            shareform.find(".message-errors").children().hide()
        elif shareform.has_errors("message", errors.TOO_LONG):
            shareform.find(".share-form-errors").children().hide()
        # reply_to and share_to also share errors...
        elif shareform.has_errors("share_to", errors.BAD_EMAILS,
                                  errors.NO_EMAILS,
                                  errors.TOO_MANY_EMAILS):
            shareform.find(".reply-to-errors").children().hide()
        elif shareform.has_errors("replyto", errors.BAD_EMAILS,
                                  errors.TOO_MANY_EMAILS):
            shareform.find(".share-to-errors").children().hide()
        # lastly, check the captcha.
        elif shareform.has_errors("captcha", errors.BAD_CAPTCHA):
            pass
        elif shareform.has_errors("ratelimit", errors.RATELIMIT):
            pass
        else:
            emails, users = emails
            c.user.add_share_emails(emails)
            c.user._commit()
            link = jquery.things(thing._fullname)
            link.set_html(".share", _("shared"))
            shareform.html("<div class='clearleft'></div>"
                           "<p class='error'>%s</p>" % 
                           _("your link has been shared."))
            
            # Set up the parts that are common between e-mail and PMs
            urlparts = (get_domain(cname=c.cname, subreddit=False),
                        thing._id36)
            url = "http://%s/tb/%s" % urlparts
            
            if message:
                message = message + "\n\n"
            else:
                message = ""
            message = message + '\n%s\n\n%s\n\n' % (thing.title,url)
            
            # Deliberately not translating this, as it'd be in the
            # sender's language
            if thing.num_comments:
                count = ("There are currently %(num_comments)s comments on " +
                         "this link.  You can view them here:")
                if thing.num_comments == 1:
                    count = ("There is currently %(num_comments)s comment " +
                             "on this link.  You can view it here:")
                
                numcom = count % {'num_comments':thing.num_comments}
                message = message + "%s\n\n" % numcom
            else:
                message = message + "You can leave a comment here:\n\n"
                
            url = add_sr(thing.make_permalink_slow(), force_hostname=True)
            message = message + url
            
            # E-mail everyone
            emailer.share(thing, emails, from_name = share_from or "",
                          body = message or "", reply_to = reply_to or "")

            # Send the PMs
            subject = "%s has shared a link with you!" % c.user.name
            # Prepend this subject to the message - we're repeating ourselves
            # because it looks very abrupt without it.
            message = "%s\n\n%s" % (subject,message)
            
            for target in users:
                
                m, inbox_rel = Message._new(c.user, target, subject,
                                            message, ip)
                # Queue up this PM
                amqp.add_item('new_message', m._fullname)

                queries.new_message(m, inbox_rel)

            #set the ratelimiter
            if should_ratelimit:
                VRatelimit.ratelimit(rate_user=True, rate_ip = True,
                                     prefix = "rate_share_")


    @require_oauth2_scope("vote")
    @noresponse(VUser(),
                VModhash(),
                vote_type = VVotehash(('vh', 'id')),
                ip = ValidIP(),
                dir=VInt('dir', min=-1, max=1, docs={"dir":
                    "vote direction. one of (1, 0, -1)"}),
                thing = VByName('id'))
    @api_doc(api_section.links_and_comments)
    def POST_vote(self, dir, thing, ip, vote_type):
        """Cast a vote on a thing.

        `id` should be the fullname of the Link or Comment to vote on.

        `dir` indicates the direction of the vote. Voting `1` is an upvote,
        `-1` is a downvote, and `0` is equivalent to "un-voting" by clicking
        again on a highlighted arrow.

        **Note: votes must be cast by humans.** That is, API clients proxying a
        human's action one-for-one are OK, but bots deciding how to vote on
        content or amplifying a human's vote are not. See [the reddit
        rules](/rules) for more details on what constitutes vote cheating.

        """

        ip = request.ip
        user = c.user
        store = True

        if not thing or thing._deleted:
            return

        if vote_type == "rejected":
            reject_vote(thing)
            store = False

        thing_age = c.start_time - thing._date
        if thing_age.days > g.VOTE_AGE_LIMIT:
            g.log.debug("ignoring vote on old thing %s" % thing._fullname)
            store = False

        if getattr(c.user, "suspicious", False):
            g.log.info("%s cast a %d vote on %s", c.user.name, dir, thing._fullname)

        dir = (True if dir > 0
               else False if dir < 0
               else None)

        organic = vote_type == 'organic'
        queries.queue_vote(user, thing, dir, ip, organic, store = store,
                           cheater = (errors.CHEATER, None) in c.errors)

    @require_oauth2_scope("modconfig")
    @validatedForm(VUser(),
                   VModhash(),
                   # nop is safe: handled after auth checks below
                   stylesheet_contents = nop('stylesheet_contents'),
                   prevstyle = VLength('prevstyle', max_length=36),
                   op = VOneOf('op',['save','preview']))
    @api_doc(api_section.subreddits)
    def POST_subreddit_stylesheet(self, form, jquery,
                                  stylesheet_contents = '', prevstyle='', op='save'):
        
        if form.has_errors("prevstyle", errors.TOO_LONG):
            return
        report, parsed = c.site.parse_css(stylesheet_contents)

        # Use the raw POST value as we need to tell the difference between
        # None/Undefined and an empty string.  The validators use a default
        # value with both of those cases and would need to be changed. 
        # In order to avoid breaking functionality, this was done instead.
        prevstyle = request.post.get('prevstyle')
        if not report:
            return abort(403, 'forbidden')
        
        if report.errors:
            error_items = [ CssError(x).render(style='html')
                            for x in sorted(report.errors) ]
            form.set_html(".status", _('validation errors'))
            form.set_html(".errors ul", ''.join(error_items))
            form.find('.errors').show()
            c.errors.add(errors.BAD_CSS, field="stylesheet_contents")
            form.has_errors("stylesheet_contents", errors.BAD_CSS)
            return
        else:
            form.find('.errors').hide()
            form.find('#conflict_box').hide()
            form.set_html(".errors ul", '')

        stylesheet_contents_parsed = parsed or ''
        if op == 'save':
            c.site.stylesheet_contents = stylesheet_contents_parsed
            try:
                wr = c.site.change_css(stylesheet_contents, parsed, prevstyle)
                form.find('.conflict_box').hide()
                form.find('.errors').hide()
                form.set_html(".status", _('saved'))
                form.set_html(".errors ul", "")
                if wr:
                    description = wiki.modactions.get('config/stylesheet')
                    form.set_inputs(prevstyle=str(wr._id))
                    ModAction.create(c.site, c.user, 'wikirevise', description)
            except ConflictException as e:
                c.errors.add(errors.CONFLICT, field="stylesheet_contents")
                form.has_errors("stylesheet_contents", errors.CONFLICT)
                form.set_html(".status", _('conflict error'))
                form.set_html(".errors ul", _('There was a conflict while editing the stylesheet'))
                form.find('#conflict_box').show()
                form.set_inputs(conflict_old=e.your,
                                prevstyle=e.new_id, stylesheet_contents=e.new)
                form.set_html('#conflict_diff', e.htmldiff)
                form.find('.errors').show()
                return
            except (tdb_cassandra.NotFound, ValueError):
                c.errors.add(errors.BAD_REVISION, field="prevstyle")
                form.has_errors("prevstyle", errors.BAD_REVISION)
                return
        jquery.apply_stylesheet(stylesheet_contents_parsed)
        if op == 'preview':
            # try to find a link to use, otherwise give up and
            # return
            links = cssfilter.find_preview_links(c.site)
            if links:

                jquery('#preview-table').show()
    
                # do a regular link
                jquery('#preview_link_normal').html(
                    cssfilter.rendered_link(links, media = 'off',
                                            compress=False))
                # now do one with media
                jquery('#preview_link_media').html(
                    cssfilter.rendered_link(links, media = 'on',
                                            compress=False))
                # do a compressed link
                jquery('#preview_link_compressed').html(
                    cssfilter.rendered_link(links, media = 'off',
                                            compress=True))
    
            # and do a comment
            comments = cssfilter.find_preview_comments(c.site)
            if comments:
                jquery('#preview_comment').html(
                    cssfilter.rendered_comment(comments))

    @require_oauth2_scope("modconfig")
    @validatedForm(VSrModerator(perms='config'),
                   VModhash(),
                   name = VCssName('img_name'))
    @api_doc(api_section.subreddits)
    def POST_delete_sr_img(self, form, jquery, name):
        """
        Called upon requested delete on /about/stylesheet.
        Updates the site's image list, and causes the <li> which wraps
        the image to be hidden.
        """
        # just in case we need to kill this feature from XSS
        if g.css_killswitch:
            return self.abort(403,'forbidden')
        c.site.del_image(name)
        c.site._commit()
        ModAction.create(c.site, c.user, action='editsettings', 
                         details='del_image', description=name)

    @require_oauth2_scope("modconfig")
    @validatedForm(VSrModerator(perms='config'),
                   VModhash())
    @api_doc(api_section.subreddits)
    def POST_delete_sr_header(self, form, jquery):
        """
        Called when the user request that the header on a sr be reset.
        """
        # just in case we need to kill this feature from XSS
        if g.css_killswitch:
            return self.abort(403,'forbidden')
        if c.site.header:
            c.site.header = None
            c.site.header_size = None
            c.site._commit()
            ModAction.create(c.site, c.user, action='editsettings', 
                             details='del_header')

        # hide the button which started this
        form.find('.delete-img').hide()
        # hide the preview box
        form.find('.img-preview-container').hide()
        # reset the status boxes
        form.set_html('.img-status', _("deleted"))
        

    def GET_upload_sr_img(self, *a, **kw):
        """
        Completely unnecessary method which exists because safari can
        be dumb too.  On page reload after an image has been posted in
        safari, the iframe to which the request posted preserves the
        URL of the POST, and safari attempts to execute a GET against
        it.  The iframe is hidden, so what it returns is completely
        irrelevant.
        """
        return "nothing to see here."

    @require_oauth2_scope("modconfig")
    @validate(VSrModerator(perms='config'),
              VModhash(),
              file = VLength('file', max_length=1024*500),
              name = VCssName("name"),
              img_type = VImageType('img_type'),
              form_id = VLength('formid', max_length = 100), 
              header = VInt('header', max=1, min=0))
    @api_doc(api_section.subreddits)
    def POST_upload_sr_img(self, file, header, name, form_id, img_type):
        """
        Called on /about/stylesheet when an image needs to be replaced
        or uploaded, as well as on /about/edit for updating the
        header.  Unlike every other POST in this controller, this
        method does not get called with Ajax but rather is from the
        original form POSTing to a hidden iFrame.  Unfortunately, this
        means the response needs to generate an page with a script tag
        to fire the requisite updates to the parent document, and,
        more importantly, that we can't use our normal toolkit for
        passing those responses back.

        The result of this function is a rendered UploadedImage()
        object in charge of firing the completedUploadImage() call in
        JS.
        """

        # default error list (default values will reset the errors in
        # the response if no error is raised)
        errors = dict(BAD_CSS_NAME = "", IMAGE_ERROR = "")
        add_image_to_sr = False
        size = None
        
        if not header:
            add_image_to_sr = True
            if not name:
                # error if the name wasn't specified and the image was not for a sponsored link or header
                # this may also fail if a sponsored image was added and the user is not an admin
                errors['BAD_CSS_NAME'] = _("bad image name")
        
        if c.site.images and add_image_to_sr:
            if c.site.get_num_images() >= g.max_sr_images:
                errors['IMAGE_ERROR'] = _("too many images (you only get %d)") % g.max_sr_images

        if any(errors.values()):
            return UploadedImage("", "", "", errors=errors, form_id=form_id).render()
        else:
            try:
                new_url = cssfilter.save_sr_image(c.site, file, suffix ='.' + img_type)
            except cssfilter.BadImage:
                errors['IMAGE_ERROR'] = _("Invalid image or general image error")
                return UploadedImage("", "", "", errors=errors, form_id=form_id).render()
            size = str_to_image(file).size
            if header:
                c.site.header = new_url
                c.site.header_size = size
            if add_image_to_sr:
                c.site.add_image(name, url = new_url)
            c.site._commit()

            if header:
                kw = dict(details='upload_image_header')
            else:
                kw = dict(details='upload_image', description=name)
            ModAction.create(c.site, c.user, action='editsettings', **kw)

            return UploadedImage(_('saved'), new_url, name, 
                                 errors=errors, form_id=form_id).render()

    @require_oauth2_scope("modconfig")
    @validatedForm(VUser(),
                   VModhash(),
                   VRatelimit(rate_user = True,
                              rate_ip = True,
                              prefix = 'create_reddit_'),
                   sr = VByName('sr'),
                   name = VAvailableSubredditName("name"),
                   title = VLength("title", max_length = 100),
                   header_title = VLength("header-title", max_length = 500),
                   domain = VCnameDomain("domain"),
                   public_description = VMarkdown("public_description", max_length = 500),
                   prev_public_description_id = VLength('prev_public_description_id', max_length = 36),
                   description = VMarkdown("description", max_length = 5120),
                   prev_description_id = VLength('prev_description_id', max_length = 36),
                   lang = VLang("lang"),
                   over_18 = VBoolean('over_18'),
                   allow_top = VBoolean('allow_top'),
                   show_media = VBoolean('show_media'),
                   public_traffic = VBoolean('public_traffic'),
                   exclude_banned_modqueue = VBoolean('exclude_banned_modqueue'),
                   show_cname_sidebar = VBoolean('show_cname_sidebar'),
                   type = VOneOf('type', ('public', 'private', 'restricted', 'gold_restricted', 'archived')),
                   link_type = VOneOf('link_type', ('any', 'link', 'self')),
                   submit_link_label=VLength('submit_link_label', max_length=60),
                   submit_text_label=VLength('submit_text_label', max_length=60),
                   comment_score_hide_mins=VInt('comment_score_hide_mins',
                       coerce=False, num_default=0, min=0, max=1440),
                   wikimode = VOneOf('wikimode', ('disabled', 'modonly', 'anyone')),
                   wiki_edit_karma = VInt("wiki_edit_karma", coerce=False, num_default=0, min=0),
                   wiki_edit_age = VInt("wiki_edit_age", coerce=False, num_default=0, min=0),
                   ip = ValidIP(),
                   css_on_cname = VBoolean("css_on_cname"),
                   )
    @api_doc(api_section.subreddits)
    def POST_site_admin(self, form, jquery, name, ip, sr, **kw):
        def apply_wikid_field(sr, form, pagename, value, prev, field, error):
            id_field_name = 'prev_%s_id' % field
            try:
                wikipage = wiki.WikiPage.get(sr, pagename)
            except tdb_cassandra.NotFound:
                wikipage = wiki.WikiPage.create(sr, pagename)
            try:
                wr = wikipage.revise(value, previous=prev, author=c.user._id36)
                setattr(sr, field, value)
                if not wr:
                    return True
                setattr(sr, id_field_name, str(wikipage.revision))
                ModAction.create(sr, c.user, 'wikirevise', details=wiki.modactions.get(pagename))
                return True
            except ConflictException as e:
                c.errors.add(errors.CONFLICT, field=field)
                form.has_errors(field, errors.CONFLICT)
                form.parent().set_html('.status', error)
                form.find('#%s_conflict_box' % field).show()
                form.set_inputs(**{id_field_name: e.new_id, '%s_conflict_old' % field: e.your, field: e.new})
                form.set_html('#%s_conflict_diff' % field, e.htmldiff)
            except (tdb_cassandra.NotFound, ValueError):
                c.errors.add(errors.BAD_REVISION, field=id_field_name)
                form.has_errors(id_field_name, errors.BAD_REVISION)
            return False
        
        # the status button is outside the form -- have to reset by hand
        form.parent().set_html('.status', "")

        redir = False
        kw = dict((k, v) for k, v in kw.iteritems()
                  if k in ('name', 'title', 'domain', 'description',
                           'show_media', 'exclude_banned_modqueue',
                           'show_cname_sidebar', 'type', 'public_traffic',
                           'link_type', 'submit_link_label', 'comment_score_hide_mins',
                           'submit_text_label', 'lang', 'css_on_cname',
                           'header_title', 'over_18', 'wikimode', 'wiki_edit_karma',
                           'wiki_edit_age', 'allow_top', 'public_description'))

        public_description = kw.pop('public_description')
        description = kw.pop('description')

        # Use the raw POST value as we need to tell the difference between
        # None/Undefined and an empty string.  The validators use a default
        # value with both of those cases and would need to be changed. 
        # In order to avoid breaking functionality, this was done instead.
        prev_desc = request.post.get('prev_description_id')
        prev_pubdesc = request.post.get('prev_public_description_id')

        def update_wiki_text(sr):
            error = False
            if not apply_wikid_field(sr,
                                     form,
                                     'config/sidebar',
                                     description,
                                     prev_desc,
                                     'description',
                                     _("Sidebar was not saved")):
                error = True

            if not apply_wikid_field(sr,
                                     form,
                                     'config/description',
                                     public_description,
                                     prev_pubdesc,
                                     'public_description',
                                     _("Description was not saved")):
                error = True
            return not error

        
        #if a user is banned, return rate-limit errors
        if c.user._spam:
            time = timeuntil(datetime.now(g.tz) + timedelta(seconds=600))
            c.errors.add(errors.RATELIMIT, {'time': time})

        domain = kw['domain']
        cname_sr = domain and Subreddit._by_domain(domain)
        if cname_sr and (not sr or sr != cname_sr):
            c.errors.add(errors.USED_CNAME)

        can_set_archived = c.user_is_admin or (sr and sr.type == 'archived')
        if kw['type'] == 'archived' and not can_set_archived:
            c.errors.add(errors.INVALID_OPTION, field='type')

        can_set_gold_restricted = c.user_is_admin or (sr and sr.type == 'gold_restricted')
        if kw['type'] == 'gold_restricted' and not can_set_gold_restricted:
            c.errors.add(errors.INVALID_OPTION, field='type')

        if not sr and form.has_errors("ratelimit", errors.RATELIMIT):
            pass
        elif not sr and form.has_errors("name", errors.SUBREDDIT_EXISTS,
                                        errors.BAD_SR_NAME):
            form.find('#example_name').hide()
        elif form.has_errors('title', errors.NO_TEXT, errors.TOO_LONG):
            form.find('#example_title').hide()
        elif form.has_errors('domain', errors.BAD_CNAME, errors.USED_CNAME):
            form.find('#example_domain').hide()
        elif (form.has_errors(('type', 'link_type', 'wikimode'),
                              errors.INVALID_OPTION) or
              form.has_errors('public_description', errors.TOO_LONG) or
              form.has_errors('description', errors.TOO_LONG)):
            pass
        elif sr and (form.has_errors(('prev_public_description_id', 
                                      'prev_description_id'), errors.TOO_LONG)):
            pass
        elif (form.has_errors(('wiki_edit_karma', 'wiki_edit_age'), 
                              errors.BAD_NUMBER)):
            pass
        elif form.has_errors('comment_score_hide_mins', errors.BAD_NUMBER):
            pass
        #creating a new reddit
        elif not sr:
            #sending kw is ok because it was sanitized above
            sr = Subreddit._new(name = name, author_id = c.user._id, ip = ip,
                                **kw)

            update_wiki_text(sr)
            sr._commit()

            Subreddit.subscribe_defaults(c.user)
            # make sure this user is on the admin list of that site!
            if sr.add_subscriber(c.user):
                sr._incr('_ups', 1)
            sr.add_moderator(c.user)
            sr.add_contributor(c.user)
            redir = sr.path + "about/edit/?created=true"
            if not c.user_is_admin:
                VRatelimit.ratelimit(rate_user=True,
                                     rate_ip = True,
                                     prefix = "create_reddit_")

            queries.new_subreddit(sr)
            changed(sr)

        #editting an existing reddit
        elif sr.is_moderator_with_perms(c.user, 'config') or c.user_is_admin:
            #assume sr existed, or was just built
            old_domain = sr.domain

            success = update_wiki_text(sr)

            if not sr.domain:
                del kw['css_on_cname']
            for k, v in kw.iteritems():
                if getattr(sr, k, None) != v:
                    ModAction.create(sr, c.user, action='editsettings', 
                                     details=k)
                setattr(sr, k, v)
            sr._commit()

            #update the domain cache if the domain changed
            if sr.domain != old_domain:
                Subreddit._by_domain(old_domain, _update = True)
                Subreddit._by_domain(sr.domain, _update = True)

            # flag search indexer that something has changed
            changed(sr)
            if success:
                form.parent().set_html('.status', _("saved"))

        if form.has_error():
            return

        if redir:
            form.redirect(redir)
        else:
            jquery.refresh()

    @noresponse(q = VPrintable('q', max_length=500),
                sort = VPrintable('sort', max_length=10),
                t = VPrintable('t', max_length=10),
                approval = VBoolean('approval'))
    def POST_searchfeedback(self, q, sort, t, approval):
        timestamp = c.start_time.strftime("%Y/%m/%d-%H:%M:%S")
        if c.user_is_loggedin:
            username = c.user.name
        else:
            username = None
        d = dict(username=username, q=q, sort=sort, t=t)
        hex = hashlib.md5(repr(d)).hexdigest()
        key = "searchfeedback-%s-%s-%s" % (timestamp[:10], request.ip, hex)
        d['timestamp'] = timestamp
        d['approval'] = approval
        g.hardcache.set(key, d, time=86400 * 7)

    @require_oauth2_scope("modposts")
    @noresponse(VUser(), VModhash(),
                VSrCanBan('id'),
                thing = VByName('id'),
                spam = VBoolean('spam', default=True))
    @api_doc(api_section.moderation)
    def POST_remove(self, thing, spam):

        # Don't remove a promoted link
        if getattr(thing, "promoted", None):
            return

        filtered = thing._spam
        kw = {'target': thing}

        if filtered and spam:
            kw['details'] = 'confirm_spam'
            train_spam = False
        elif filtered and not spam:
            kw['details'] = 'remove'
            admintools.unspam(thing, unbanner=c.user.name, insert=False)
            train_spam = False
        elif not filtered and spam:
            kw['details'] = 'spam'
            train_spam = True
        elif not filtered and not spam:
            kw['details'] = 'remove'
            train_spam = False

        admintools.spam(thing, auto=False,
                        moderator_banned=not c.user_is_admin,
                        banner=c.user.name,
                        train_spam=train_spam)

        if isinstance(thing, (Link, Comment)):
            sr = thing.subreddit_slow
            action = 'remove' + thing.__class__.__name__.lower()
            ModAction.create(sr, c.user, action, **kw)

    @require_oauth2_scope("modposts")
    @noresponse(VUser(), VModhash(),
                VSrCanBan('id'),
                thing = VByName('id'))
    @api_doc(api_section.moderation)
    def POST_approve(self, thing):
        if not thing: return
        if thing._deleted: return
        kw = {'target': thing}
        if thing._spam:
            kw['details'] = 'unspam'
            train_spam = True
            insert = True
        else:
            kw['details'] = 'confirm_ham'
            train_spam = False
            insert = False

        admintools.unspam(thing, moderator_unbanned=not c.user_is_admin,
                          unbanner=c.user.name, train_spam=train_spam,
                          insert=insert)

        if isinstance(thing, (Link, Comment)):
            sr = thing.subreddit_slow
            action = 'approve' + thing.__class__.__name__.lower()
            ModAction.create(sr, c.user, action, **kw)

    @require_oauth2_scope("modposts")
    @noresponse(VUser(), VModhash(),
                VSrCanBan('id'),
                thing=VByName('id'))
    @api_doc(api_section.moderation)
    def POST_ignore_reports(self, thing):
        if not thing: return
        if thing._deleted: return
        if thing.ignore_reports: return

        thing.ignore_reports = True
        thing._commit()

        sr = thing.subreddit_slow
        ModAction.create(sr, c.user, 'ignorereports', target=thing)

    @require_oauth2_scope("modposts")
    @noresponse(VUser(), VModhash(),
                VSrCanBan('id'),
                thing=VByName('id'))
    @api_doc(api_section.moderation)
    def POST_unignore_reports(self, thing):
        if not thing: return
        if thing._deleted: return
        if not thing.ignore_reports: return

        thing.ignore_reports = False
        thing._commit()

        sr = thing.subreddit_slow
        ModAction.create(sr, c.user, 'unignorereports', target=thing)

    @require_oauth2_scope("modposts")
    @validatedForm(VUser(), VModhash(),
                   VCanDistinguish(('id', 'how')),
                   thing = VByName('id'),
                   how = VOneOf('how', ('yes','no','admin','special')))
    @api_doc(api_section.moderation)
    def POST_distinguish(self, form, jquery, thing, how):
        if not thing:return

        log_modaction = True
        log_kw = {}
        send_message = False
        original = getattr(thing, 'distinguished', 'no')
        if how == original: # Distinguish unchanged
            log_modaction = False
        elif how in ('admin', 'special'): # Add admin/special
            log_modaction = False
            send_message = True
        elif (original in ('admin', 'special') and
                how == 'no'): # Remove admin/special
            log_modaction = False
        elif how == 'no': # From yes to no
            log_kw['details'] = 'remove'
        else: # From no to yes
            send_message = True

        # Send a message if this is a top-level comment on a submission that
        # does not have sendreplies set, if it's the first distinguish for this
        # comment, and if the user isn't banned or blocked by the author
        if isinstance(thing, Comment):
            link = Link._byID(thing.link_id, data=True)
            to = Account._byID(link.author_id, data=True)
            if (send_message and
                    thing.parent_id is None and
                    not link.sendreplies and
                    not hasattr(thing, 'distinguished') and
                    not c.user._spam and
                    c.user._id not in to.enemies and
                    to.name != c.user.name):
                inbox_rel = Inbox._add(to, thing, 'selfreply')
                queries.new_comment(thing, inbox_rel)

        thing.distinguished = how
        thing._commit()

        wrapper = default_thing_wrapper(expand_children = True)
        w = wrap_links(thing, wrapper)
        jquery(".content").replace_things(w, True, True)
        jquery(".content .link .rank").hide()
        if log_modaction:
            sr = thing.subreddit_slow
            ModAction.create(sr, c.user, 'distinguish', target=thing, **log_kw)

    @noresponse(VUser(),
                VModhash(),
                thing = VByName('id'))
    @api_doc(api_section.links_and_comments)
    def POST_save(self, thing):
        """Save a link or comment.

        Saved things are kept in the user's saved listing for later perusal.

        See also: [/api/unsave](#POST_api_unsave).

        """
        if not thing: return
        if isinstance(thing, Comment) and not c.user.gold: return
        r = thing._save(c.user)

    @noresponse(VUser(),
                VModhash(),
                thing = VByName('id'))
    @api_doc(api_section.links_and_comments)
    def POST_unsave(self, thing):
        """Unsave a link or comment.

        This removes the thing from the user's saved listings as well.

        See also: [/api/save](#POST_api_save).

        """
        if not thing: return
        r = thing._unsave(c.user)

    def collapse_handler(self, things, collapse):
        if not things:
            return
        things = tup(things)
        srs = Subreddit._byID([t.sr_id for t in things if t.sr_id],
                              return_dict = True)
        for t in things:
            if hasattr(t, "to_id") and c.user._id == t.to_id:
                t.to_collapse = collapse
            elif hasattr(t, "author_id") and c.user._id == t.author_id:
                t.author_collapse = collapse
            elif isinstance(t, Message) and t.sr_id:
                if srs[t.sr_id].is_moderator(c.user):
                    t.to_collapse = collapse
            t._commit()

    @noresponse(VUser(),
                VModhash(),
                things = VByName('id', multiple = True))
    def POST_collapse_message(self, things):
        self.collapse_handler(things, True)

    @noresponse(VUser(),
                VModhash(),
                things = VByName('id', multiple = True))
    def POST_uncollapse_message(self, things):
        self.collapse_handler(things, False)

    def unread_handler(self, things, unread):
        if not things:
            if (errors.TOO_MANY_THING_IDS, 'id') in c.errors:
                return abort(413)
            else:
                return abort(400)

        sr_messages = defaultdict(list)
        comments = []
        messages = []
        # Group things by subreddit or type
        for thing in things:
            if isinstance(thing, Message):
                if getattr(thing, 'sr_id', False):
                    sr_messages[thing.sr_id].append(thing)
                else:
                    messages.append(thing)
            else:
                comments.append(thing)

        if sr_messages:
            mod_srs = Subreddit.reverse_moderator_ids(c.user)
            srs = Subreddit._byID(sr_messages.keys())
        else:
            mod_srs = []

        # Batch set items as unread
        for sr_id, things in sr_messages.items():
            # Remove the item(s) from the user's inbox
            queries.set_unread(things, c.user, unread)
            if sr_id in mod_srs:
                # Only moderators can change the read status of that
                # message in the modmail inbox
                sr = srs[sr_id]
                queries.set_unread(things, sr, unread)
        if comments:
            queries.set_unread(comments, c.user, unread)
        if messages:
            queries.set_unread(messages, c.user, unread)


    @require_oauth2_scope("privatemessages")
    @noresponse(VUser(),
                VModhash(),
                things = VByName('id', multiple=True, limit=25))
    @api_doc(api_section.messages)
    def POST_unread_message(self, things):
        self.unread_handler(things, True)

    @require_oauth2_scope("privatemessages")
    @noresponse(VUser(),
                VModhash(),
                things = VByName('id', multiple=True, limit=25))
    @api_doc(api_section.messages)
    def POST_read_message(self, things):
        self.unread_handler(things, False)

    @noresponse(VUser(),
                VModhash(),
                thing = VByName('id', thing_cls=Link))
    @api_doc(api_section.links_and_comments)
    def POST_hide(self, thing):
        """Hide a link.

        This removes it from the user's default view of subreddit listings.

        See also: [/api/unhide](#POST_api_unhide).

        """
        if not thing: return
        r = thing._hide(c.user)

    @noresponse(VUser(),
                VModhash(),
                thing = VByName('id'))
    @api_doc(api_section.links_and_comments)
    def POST_unhide(self, thing):
        """Unhide a link.

        See also: [/api/hide](#POST_api_hide).

        """
        if not thing: return
        r = thing._unhide(c.user)


    @validatedForm(VUser(),
                   parent = VByName('parent_id'))
    def POST_moremessages(self, form, jquery, parent):
        if not parent.can_view_slow():
            return self.abort(403,'forbidden')

        if parent.sr_id:
            builder = SrMessageBuilder(parent.subreddit_slow,
                                       parent = parent, skip = False)
        else:
            builder = UserMessageBuilder(c.user, parent = parent, skip = False)
        listing = Listing(builder).listing()
        a = []
        for item in listing.things:
            a.append(item)
            for x in item.child.things:
                a.append(x)
        for item in a:
            if hasattr(item, "child"):
                item.child = None
        jquery.things(parent._fullname).parent().replace_things(a, False, True)

    @validatedForm(link = VByName('link_id'),
                   sort = VMenu('where', CommentSortMenu),
                   children = VCommentIDs('children'),
                   pv_hex=VPrintable("pv_hex", 40, docs={"pv_hex":
                       "(optional) a previous-visits token"}),
                   mc_id=nop("id", docs={"id":
                       "(optional) id of the associated MoreChildren object"}),
                  )
    @api_doc(api_section.links_and_comments)
    def POST_morechildren(self, form, jquery, link, sort, children,
                          pv_hex, mc_id):
        """Retrieve additional comments omitted from a base comment tree.

        When a comment tree is rendered, the most relevant comments are
        selected for display first. Remaining comments are stubbed out with
        "MoreComments" links. This API call is used to retrieve the additional
        comments represented by those stubs, up to 20 at a time.

        The two core parameters required are `link` and `children`.  `link` is
        the fullname of the link whose comments are being fetched. `children`
        is a comma-delimited list of comment ID36s that need to be fetched.

        If `id` is passed, it should be the ID of the MoreComments object this
        call is replacing. This is needed only for the HTML UI's purposes and
        is optional otherwise.

        `pv_hex` is part of the reddit gold "previous visits" feature. It is
        optional and deprecated.

        **NOTE:** you may only make one request at a time to this API endpoint.
        Higher concurrency will result in an error being returned.

        """

        CHILD_FETCH_COUNT = 20

        lock = None
        if c.user_is_loggedin:
            lock = g.make_lock("morechildren", "morechildren-" + c.user.name,
                               timeout=0)
            try:
                lock.acquire()
            except TimeoutExpired:
                abort(429)

        try:
            if not link or not link.subreddit_slow.can_view(c.user):
                return abort(403,'forbidden')

            if pv_hex:
                c.previous_visits = g.cache.get(pv_hex)

            if children:
                builder = CommentBuilder(link, CommentSortMenu.operator(sort),
                                         children)
                listing = Listing(builder, nextprev = False)
                items = listing.get_items(num=CHILD_FETCH_COUNT)
                def _children(cur_items):
                    items = []
                    for cm in cur_items:
                        items.append(cm)
                        if hasattr(cm, 'child'):
                            if hasattr(cm.child, 'things'):
                                items.extend(_children(cm.child.things))
                                cm.child = None
                            else:
                                items.append(cm.child)

                    return items
                # assumes there is at least one child
                # a = _children(items[0].child.things)
                a = []
                for item in items:
                    a.append(item)
                    if hasattr(item, 'child'):
                        a.extend(_children(item.child.things))
                        item.child = None

                # the result is not always sufficient to replace the
                # morechildren link
                jquery.things(str(mc_id)).remove()
                jquery.insert_things(a, append = True)

                if pv_hex:
                    jquery.rehighlight_new_comments()
        finally:
            if lock:
                lock.release()


    @validate(uh = nop('uh'), # VModHash() will raise, check manually
              action = VOneOf('what', ('like', 'dislike', 'save')),
              links = VUrl(['u']))
    def GET_bookmarklet(self, action, uh, links):
        '''Controller for the functionality of the bookmarklets (not
        the distribution page)'''

        # the redirect handler will clobber the extension if not told otherwise
        c.extension = "png"

        if not c.user_is_loggedin:
            return self.redirect("/static/css_login.png")
        # check the modhash (or force them to get new bookmarlets)
        elif not c.user.valid_hash(uh) or not action:
            return self.redirect("/static/css_update.png")
        # unlike most cases, if not already submitted, error.
        elif errors.ALREADY_SUB in c.errors:
            # preserve the subreddit if not Default
            sr = c.site if not isinstance(c.site, FakeSubreddit) else None

            # check permissions on those links to make sure votes will count
            Subreddit.load_subreddits(links, return_dict = False)
            user = c.user if c.user_is_loggedin else None
            links = [l for l in links if l.subreddit_slow.can_view(user)]

            if links:
                if action in ['like', 'dislike']:
                    #vote up all of the links
                    for link in links:
                        queries.queue_vote(c.user, link,
                                           action == 'like', request.ip,
                                           cheater = (errors.CHEATER, None) in c.errors)
                elif action == 'save':
                    link = max(links, key = lambda x: x._score)
                    r = link._save(c.user)
                return self.redirect("/static/css_%sd.png" % action)
        return self.redirect("/static/css_submit.png")


    @validatedForm(VUser(),
                   code = VPrintable("code", 30))
    def POST_claimgold(self, form, jquery, code):
        status = ''
        if not code:
            c.errors.add(errors.NO_TEXT, field = "code")
            form.has_errors("code", errors.NO_TEXT)
            return

        rv = claim_gold(code, c.user._id)

        if rv is None:
            c.errors.add(errors.INVALID_CODE, field = "code")
            log_text ("invalid gold claim",
                      "%s just tried to claim %s" % (c.user.name, code),
                      "info")
        elif rv == "already claimed":
            c.errors.add(errors.CLAIMED_CODE, field = "code")
            log_text ("invalid gold reclaim",
                      "%s just tried to reclaim %s" % (c.user.name, code),
                      "info")
        else:
            days, subscr_id = rv
            if days <= 0:
                raise ValueError("days = %r?" % days)

            log_text ("valid gold claim",
                      "%s just claimed %s" % (c.user.name, code),
                      "info")

            if subscr_id:
                c.user.gold_subscr_id = subscr_id

            if code.startswith("cr_"):
                c.user.gold_creddits += int(days / 31)
                c.user._commit()
                status = 'claimed-creddits'
            else:
                admintools.engolden(c.user, days)

                g.cache.set("recent-gold-" + c.user.name, True, 600)
                status = 'claimed-gold'
                jquery(".lounge").show()

        # Activate any errors we just manually set
        if not form.has_errors("code", errors.INVALID_CODE, errors.CLAIMED_CODE,
                               errors.NO_TEXT):
            form.redirect("/gold/thanks?v=%s" % status)

    @validatedForm(user = VUserWithEmail('name'))
    def POST_password(self, form, jquery, user):
        if form.has_errors('name', errors.USER_DOESNT_EXIST):
            return
        elif form.has_errors('name', errors.NO_EMAIL_FOR_USER):
            return
        else:
            if emailer.password_email(user):
                form.set_html(".status",
                      _("an email will be sent to that account's address shortly"))
            else:
                form.set_html(".status", _("try again tomorrow"))


    @validatedForm(token=VOneTimeToken(PasswordResetToken, "key"),
                   password=VPassword(["passwd", "passwd2"]))
    def POST_resetpassword(self, form, jquery, token, password):
        # was the token invalid or has it expired?
        if not token:
            form.redirect("/password?expired=true")
            return

        # did they fill out the password form correctly?
        form.has_errors("passwd",  errors.BAD_PASSWORD)
        form.has_errors("passwd2", errors.BAD_PASSWORD_MATCH)
        if form.has_error():
            return

        # at this point, we should mark the token used since it's either
        # valid now or will never be valid again.
        token.consume()

        # load up the user and check that things haven't changed
        user = Account._by_fullname(token.user_id)
        if not token.valid_for_user(user):
            form.redirect('/password?expired=true')
            return

        # Prevent banned users from resetting, and thereby logging in
        if user._banned:
            return

        # successfully entered user name and valid new password
        change_password(user, password)
        if user.email_verified:
            emailer.password_change_email(user)
        g.log.warning("%s did a password reset for %s via %s",
                      request.ip, user.name, token._id)

        self._login(jquery, user)
        jquery.redirect('/')


    @noresponse(VUser())
    def POST_noframe(self):
        """
        removes the reddit toolbar if that currently the user's preference
        """
        c.user.pref_frame = False
        c.user._commit()


    @noresponse(VUser())
    def POST_frame(self):
        """
        undoes POST_noframe
        """
        c.user.pref_frame = True
        c.user._commit()


    @require_oauth2_scope("subscribe")
    @noresponse(VUser(),
                VModhash(),
                action = VOneOf('action', ('sub', 'unsub')),
                sr = VSubscribeSR('sr', 'sr_name'))
    @api_doc(api_section.subreddits)
    def POST_subscribe(self, action, sr):
        # only users who can make edits are allowed to subscribe.
        # Anyone can leave.
        if sr and (action != 'sub' or sr.can_comment(c.user)):
            self._subscribe(sr, action == 'sub')

    @classmethod
    def _subscribe(cls, sr, sub):
        try:
            Subreddit.subscribe_defaults(c.user)

            if sub:
                if sr.add_subscriber(c.user):
                    sr._incr('_ups', 1)
            else:
                if sr.remove_subscriber(c.user):
                    sr._incr('_ups', -1)
            changed(sr, True)
        except CreationError:
            # This only seems to happen when someone is pounding on the
            # subscribe button or the DBs are really lagged; either way,
            # some other proc has already handled this subscribe request.
            return


    @validatedForm(VAdmin(),
                   hexkey=VLength("hexkey", max_length=32),
                   nickname=VLength("nickname", max_length = 1000),
                   status = VOneOf("status",
                      ("new", "severe", "interesting", "normal", "fixed")))
    def POST_edit_error(self, form, jquery, hexkey, nickname, status):
        if form.has_errors(("hexkey", "nickname", "status"),
                           errors.NO_TEXT, errors.INVALID_OPTION):
            pass

        if form.has_error():
            return

        key = "error_nickname-%s" % str(hexkey)
        g.hardcache.set(key, nickname, 86400 * 365)

        key = "error_status-%s" % str(hexkey)
        g.hardcache.set(key, status, 86400 * 365)

        form.set_html(".status", _('saved'))

    @validatedForm(VAdmin(),
                   award=VByName("fullname"),
                   colliding_award=VAwardByCodename(("codename", "fullname")),
                   codename=VLength("codename", max_length = 100),
                   title=VLength("title", max_length = 100),
                   awardtype=VOneOf("awardtype",
                                    ("regular", "manual", "invisible")),
                   api_ok=VBoolean("api_ok"),
                   imgurl=VLength("imgurl", max_length = 1000))
    def POST_editaward(self, form, jquery, award, colliding_award, codename,
                       title, awardtype, api_ok, imgurl):
        if form.has_errors(("codename", "title", "awardtype", "imgurl"),
                           errors.NO_TEXT):
            pass

        if awardtype is None:
            form.set_html(".status", "bad awardtype")
            return

        if form.has_errors(("codename"), errors.INVALID_OPTION):
            form.set_html(".status", "some other award has that codename")
            pass

        if form.has_error():
            return

        if award is None:
            Award._new(codename, title, awardtype, imgurl, api_ok)
            form.set_html(".status", "saved. reload to see it.")
            return

        award.codename = codename
        award.title = title
        award.awardtype = awardtype
        award.imgurl = imgurl
        award.api_ok = api_ok
        award._commit()
        form.set_html(".status", _('saved'))

    @require_oauth2_scope("modflair")
    @validatedForm(VSrModerator(perms='flair'),
                   VModhash(),
                   user = VFlairAccount("name"),
                   link = VFlairLink('link'),
                   text = VFlairText("text"),
                   css_class = VFlairCss("css_class"))
    @api_doc(api_section.flair)
    def POST_flair(self, form, jquery, user, link, text, css_class):
        if link:
            flair_type = LINK_FLAIR
            if hasattr(c.site, '_id') and c.site._id == link.sr_id:
                site = c.site
            else:
                site = Subreddit._byID(link.sr_id, data=True)
                # make sure c.user has permission to set flair on this link
                if not (c.user_is_admin 
                        or site.is_moderator_with_perms(c.user, 'flair')):
                    abort(403, 'forbidden')
        else:
            flair_type = USER_FLAIR
            site = c.site
            if form.has_errors('name', errors.BAD_FLAIR_TARGET):
                return

        if form.has_errors('css_class', errors.BAD_CSS_NAME):
            form.set_html(".status:first", _('invalid css class'))
            return
        if form.has_errors('css_class', errors.TOO_MUCH_FLAIR_CSS):
            form.set_html(".status:first", _('too many css classes'))
            return

        if flair_type == LINK_FLAIR:
            if not text and not css_class:
                text = css_class = None
            link.flair_text = text
            link.flair_css_class = css_class
            link._commit()
            changed(link)
            ModAction.create(site, c.user, action='editflair', target=link,
                             details='flair_edit')
        elif flair_type == USER_FLAIR:
            if not text and not css_class:
                # empty text and css is equivalent to unflairing
                text = css_class = None
                c.site.remove_flair(user)
                jquery('#flairrow_%s' % user._id36).hide()
                new = False
            elif not c.site.is_flair(user):
                c.site.add_flair(user)
                new = True
            else:
                new = False

            # Save the flair details in the account data.
            setattr(user, 'flair_%s_text' % c.site._id, text)
            setattr(user, 'flair_%s_css_class' % c.site._id, css_class)
            user._commit()

            if c.user != user:
                ModAction.create(site, c.user, action='editflair',
                                 target=user, details='flair_edit')

            if new:
                jquery.redirect('?name=%s' % user.name)
            else:
                flair = WrappedUser(
                    user, force_show_flair=True,
                    include_flair_selector=True).render(style='html')
                jquery('.tagline .flairselectable.id-%s'
                    % user._fullname).parent().html(flair)
                jquery('input[name="text"]').data('saved', text)
                jquery('input[name="css_class"]').data('saved', css_class)
                form.set_html('.status', _('saved'))

    @require_oauth2_scope("modflair")
    @validatedForm(VSrModerator(perms='flair'),
                   VModhash(),
                   user = VFlairAccount("name"))
    @api_doc(api_section.flair)
    def POST_deleteflair(self, form, jquery, user):
        # Check validation.
        if form.has_errors('name', errors.USER_DOESNT_EXIST, errors.NO_USER):
            return
        c.site.remove_flair(user)
        setattr(user, 'flair_%s_text' % c.site._id, None)
        setattr(user, 'flair_%s_css_class' % c.site._id, None)
        user._commit()

        ModAction.create(c.site, c.user, action='editflair', target=user,
                         details='flair_delete')

        jquery('#flairrow_%s' % user._id36).remove()
        unflair = WrappedUser(
            user, include_flair_selector=True).render(style='html')
        jquery('.tagline .id-%s' % user._fullname).parent().html(unflair)

    @require_oauth2_scope("modflair")
    @validate(VSrModerator(perms='flair'),
              VModhash(),
              flair_csv = nop('flair_csv'))
    @api_doc(api_section.flair)
    def POST_flaircsv(self, flair_csv):
        limit = 100  # max of 100 flair settings per call
        results = FlairCsv()
        # encode to UTF-8, since csv module doesn't fully support unicode
        infile = csv.reader(flair_csv.strip().encode('utf-8').split('\n'))
        for i, row in enumerate(infile):
            line_result = results.add_line()
            line_no = i + 1
            if line_no > limit:
                line_result.error('row',
                                  'limit of %d rows per call reached' % limit)
                break

            try:
                name, text, css_class = row
            except ValueError:
                line_result.error('row', 'improperly formatted row, ignoring')
                continue

            user = VFlairAccount('name').run(name)
            if not user:
                line_result.error('user',
                                  "unable to resolve user `%s', ignoring"
                                  % name)
                continue

            if not text and not css_class:
                # this is equivalent to unflairing
                text = None
                css_class = None

            orig_text = text
            text = VFlairText('text').run(orig_text)
            if text and orig_text and len(text) < len(orig_text):
                line_result.warn('text',
                                 'truncating flair text to %d chars'
                                 % len(text))

            if css_class and not VFlairCss('css_class').run(css_class):
                line_result.error('css',
                                  "invalid css class `%s', ignoring"
                                  % css_class)
                continue

            # all validation passed, enflair the user
            if text or css_class:
                mode = 'added'
                c.site.add_flair(user)
            else:
                mode = 'removed'
                c.site.remove_flair(user)
            setattr(user, 'flair_%s_text' % c.site._id, text)
            setattr(user, 'flair_%s_css_class' % c.site._id, css_class)
            user._commit()

            line_result.status = '%s flair for user %s' % (mode, user.name)
            line_result.ok = True

        ModAction.create(c.site, c.user, action='editflair',
                         details='flair_csv')

        return BoringPage(_("API"), content = results).render()

    @validatedForm(VUser(),
                   VModhash(),
                   flair_enabled = VBoolean("flair_enabled"))
    @api_doc(api_section.flair)
    def POST_setflairenabled(self, form, jquery, flair_enabled):
        setattr(c.user, 'flair_%s_enabled' % c.site._id, flair_enabled)
        c.user._commit()
        jquery.refresh()

    @require_oauth2_scope("modflair")
    @validatedForm(
        VSrModerator(perms='flair'),
        VModhash(),
        flair_enabled = VBoolean("flair_enabled"),
        flair_position = VOneOf("flair_position", ("left", "right")),
        link_flair_position = VOneOf("link_flair_position",
                                     ("", "left", "right")),
        flair_self_assign_enabled = VBoolean("flair_self_assign_enabled"),
        link_flair_self_assign_enabled =
            VBoolean("link_flair_self_assign_enabled"))
    @api_doc(api_section.flair)
    def POST_flairconfig(self, form, jquery, flair_enabled, flair_position,
                         link_flair_position, flair_self_assign_enabled,
                         link_flair_self_assign_enabled):
        if c.site.flair_enabled != flair_enabled:
            c.site.flair_enabled = flair_enabled
            ModAction.create(c.site, c.user, action='editflair',
                             details='flair_enabled')
        if c.site.flair_position != flair_position:
            c.site.flair_position = flair_position
            ModAction.create(c.site, c.user, action='editflair',
                             details='flair_position')
        if c.site.link_flair_position != link_flair_position:
            c.site.link_flair_position = link_flair_position
            ModAction.create(c.site, c.user, action='editflair',
                             details='link_flair_position')
        if c.site.flair_self_assign_enabled != flair_self_assign_enabled:
            c.site.flair_self_assign_enabled = flair_self_assign_enabled
            ModAction.create(c.site, c.user, action='editflair',
                             details='flair_self_enabled')
        if (c.site.link_flair_self_assign_enabled
            != link_flair_self_assign_enabled):
            c.site.link_flair_self_assign_enabled = (
                link_flair_self_assign_enabled)
            ModAction.create(c.site, c.user, action='editflair',
                             details='link_flair_self_enabled')
        c.site._commit()
        jquery.refresh()

    @require_oauth2_scope("modflair")
    @paginated_listing(max_page_size=1000)
    @validate(user = VFlairAccount('name'))
    @api_doc(api_section.flair)
    def GET_flairlist(self, num, after, reverse, count, user):
        flair = FlairList(num, after, reverse, '', user)
        return BoringPage(_("API"), content = flair).render()

    @require_oauth2_scope("modflair")
    @validatedForm(VSrModerator(perms='flair'),
                   VModhash(),
                   flair_template = VFlairTemplateByID('flair_template_id'),
                   text = VFlairText('text'),
                   css_class = VFlairCss('css_class'),
                   text_editable = VBoolean('text_editable'),
                   flair_type = VOneOf('flair_type', (USER_FLAIR, LINK_FLAIR),
                                       default=USER_FLAIR))
    @api_doc(api_section.flair)
    def POST_flairtemplate(self, form, jquery, flair_template, text,
                           css_class, text_editable, flair_type):
        if text is None:
            text = ''
        if css_class is None:
            css_class = ''

        # Check validation.
        if form.has_errors('css_class', errors.BAD_CSS_NAME):
            form.set_html(".status:first", _('invalid css class'))
            return
        if form.has_errors('css_class', errors.TOO_MUCH_FLAIR_CSS):
            form.set_html(".status:first", _('too many css classes'))
            return

        # Load flair template thing.
        if flair_template:
            flair_template.text = text
            flair_template.css_class = css_class
            flair_template.text_editable = text_editable
            flair_template._commit()
            new = False
        else:
            try:
                flair_template = FlairTemplateBySubredditIndex.create_template(
                    c.site._id, text=text, css_class=css_class,
                    text_editable=text_editable,
                    flair_type=flair_type)
            except OverflowError:
                form.set_html(".status:first", _('max flair templates reached'))
                return

            new = True

        # Push changes back to client.
        if new:
            empty_ids = {
                USER_FLAIR: '#empty-user-flair-template',
                LINK_FLAIR: '#empty-link-flair-template',
            }
            empty_id = empty_ids[flair_type]
            jquery(empty_id).before(
                FlairTemplateEditor(flair_template, flair_type)
                .render(style='html'))
            empty_template = FlairTemplate()
            empty_template._committed = True  # to disable unnecessary warning
            jquery(empty_id).html(
                FlairTemplateEditor(empty_template, flair_type)
                .render(style='html'))
            form.set_html('.status', _('saved'))
        else:
            jquery('#%s' % flair_template._id).html(
                FlairTemplateEditor(flair_template, flair_type)
                .render(style='html'))
            form.set_html('.status', _('saved'))
            jquery('input[name="text"]').data('saved', text)
            jquery('input[name="css_class"]').data('saved', css_class)
        ModAction.create(c.site, c.user, action='editflair',
                             details='flair_template')

    @require_oauth2_scope("modflair")
    @validatedForm(VSrModerator(perms='flair'),
                   VModhash(),
                   flair_template = VFlairTemplateByID('flair_template_id'))
    @api_doc(api_section.flair)
    def POST_deleteflairtemplate(self, form, jquery, flair_template):
        idx = FlairTemplateBySubredditIndex.by_sr(c.site._id)
        if idx.delete_by_id(flair_template._id):
            jquery('#%s' % flair_template._id).parent().remove()
            ModAction.create(c.site, c.user, action='editflair',
                             details='flair_delete_template')

    @require_oauth2_scope("modflair")
    @validatedForm(VSrModerator(perms='flair'), VModhash(),
                   flair_type = VOneOf('flair_type', (USER_FLAIR, LINK_FLAIR),
                                       default=USER_FLAIR))
    @api_doc(api_section.flair)
    def POST_clearflairtemplates(self, form, jquery, flair_type):
        FlairTemplateBySubredditIndex.clear(c.site._id, flair_type=flair_type)
        jquery.refresh()
        ModAction.create(c.site, c.user, action='editflair',
                         details='flair_clear_template')

    @validate(VUser(),
              user = VFlairAccount('name'),
              link = VFlairLink('link'))
    def POST_flairselector(self, user, link):
        if link:
            if hasattr(c.site, '_id') and c.site._id == link.sr_id:
                site = c.site
            else:
                site = Subreddit._byID(link.sr_id, data=True)
            return FlairSelector(link=link, site=site).render()
        if user and not (c.user_is_admin
                         or c.site.is_moderator_with_perms(c.user, 'flair')):
            # ignore user parameter if c.user is not mod/admin
            user = None
        return FlairSelector(user=user).render()

    @validatedForm(VUser(),
                   VModhash(),
                   user = VFlairAccount('name'),
                   link = VFlairLink('link'),
                   flair_template_id = nop('flair_template_id'),
                   text = VFlairText('text'))
    @api_doc(api_section.flair)
    def POST_selectflair(self, form, jquery, user, link, flair_template_id,
                         text):
        if link:
            flair_type = LINK_FLAIR
            if hasattr(c.site, '_id') and c.site._id == link.sr_id:
                site = c.site
            else:
                site = Subreddit._byID(link.sr_id, data=True)
            self_assign_enabled = site.link_flair_self_assign_enabled
        else:
            flair_type = USER_FLAIR
            site = c.site
            self_assign_enabled = site.flair_self_assign_enabled

        if flair_template_id:
            try:
                flair_template = FlairTemplateBySubredditIndex.get_template(
                    site._id, flair_template_id, flair_type=flair_type)
            except NotFound:
                # TODO: serve error to client
                g.log.debug('invalid flair template for subreddit %s', site._id)
                return
        else:
            flair_template = None
            text = None

        if not (c.user_is_admin
                or site.is_moderator_with_perms(c.user, 'flair')):
            if not self_assign_enabled:
                # TODO: serve error to client
                g.log.debug('flair self-assignment not permitted')
                return

            # Ignore user choice if not an admin or mod.
            user = c.user

            # Ignore given text if user doesn't have permission to customize it.
            if not (flair_template and flair_template.text_editable):
                text = None

        if not text:
            text = flair_template.text if flair_template else None

        css_class = flair_template.css_class if flair_template else None
        text_editable = (
            flair_template.text_editable if flair_template else False)

        if flair_type == USER_FLAIR:
            site.add_flair(user)
            setattr(user, 'flair_%s_text' % site._id, text)
            setattr(user, 'flair_%s_css_class' % site._id, css_class)
            user._commit()

            if ((c.user_is_admin
                 or site.is_moderator_with_perms(c.user, 'flair'))
                and c.user != user):
                ModAction.create(site, c.user, action='editflair',
                                 target=user, details='flair_edit')

            # Push some client-side updates back to the browser.
            u = WrappedUser(user, force_show_flair=True,
                            flair_text_editable=text_editable,
                            include_flair_selector=True)
            flair = u.render(style='html')
            jquery('.tagline .flairselectable.id-%s'
                % user._fullname).parent().html(flair)
            jquery('#flairrow_%s input[name="text"]' % user._id36).data(
                'saved', text).val(text)
            jquery('#flairrow_%s input[name="css_class"]' % user._id36).data(
                'saved', css_class).val(css_class)
        elif flair_type == LINK_FLAIR:
            link.flair_text = text
            link.flair_css_class = css_class
            link._commit()
            changed(link)

            if c.user_is_admin or site.is_moderator_with_perms(c.user, 'flair'):
                ModAction.create(site, c.user, action='editflair',
                                 target=link, details='flair_edit')

            # Push some client-side updates back to the browser.

            jquery('.id-%s .entry .linkflairlabel' % link._fullname).remove()
            title_path = '.id-%s .entry > .title > .title' % link._fullname

            # TODO: move this to a template
            if flair_template:
                flair = '<span class="linkflairlabel %s">%s</span>' % (
                    ' '.join('linkflair-' + c for c in css_class.split()),
                    websafe(text))
                if site.link_flair_position == 'left':
                    jquery(title_path).before(flair)
                elif site.link_flair_position == 'right':
                    jquery(title_path).after(flair)

            # TODO: close the selector popup more gracefully
            jquery('body').click()

    @validatedForm(secret_used=VAdminOrAdminSecret("secret"),
                   award=VByName("fullname"),
                   description=VLength("description", max_length=1000),
                   url=VLength("url", max_length=1000),
                   cup_hours=VFloat("cup_hours",
                                      coerce=False, min=0, max=24 * 365),
                   recipient=VExistingUname("recipient"))
    def POST_givetrophy(self, form, jquery, secret_used, award, description,
                        url, cup_hours, recipient):
        if form.has_errors("recipient", errors.USER_DOESNT_EXIST,
                                        errors.NO_USER):
            pass

        if form.has_errors("fullname", errors.NO_TEXT, errors.NO_THING_ID):
            pass

        if form.has_errors("cup_hours", errors.BAD_NUMBER):
            pass
        
        if secret_used and not award.api_ok:
            c.errors.add(errors.NO_API, field='secret')
            form.has_errors('secret', errors.NO_API)

        if form.has_error():
            return

        if cup_hours:
            cup_seconds = int(cup_hours * 3600)
            cup_expiration = timefromnow("%s seconds" % cup_seconds)
        else:
            cup_expiration = None
        
        t = Trophy._new(recipient, award, description=description, url=url,
                        cup_info=dict(expiration=cup_expiration))

        form.set_html(".status", _('saved'))
        form._send_data(trophy_fn=t._id36)
    
    @validatedForm(VAdmin(),
                   account = VExistingUname("account"))
    def POST_removecup(self, form, jquery, account):
        if not account:
            return self.abort404()
        account.remove_cup()

    @validatedForm(secret_used=VAdminOrAdminSecret("secret"),
                   trophy = VTrophy("trophy_fn"))
    def POST_removetrophy(self, form, jquery, secret_used, trophy):
        if not trophy:
            return self.abort404()
        recipient = trophy._thing1
        award = trophy._thing2
        if secret_used and not award.api_ok:
            c.errors.add(errors.NO_API, field='secret')
            form.has_errors('secret', errors.NO_API)
        
        if form.has_error():
            return

        trophy._delete()
        Trophy.by_account(recipient, _update=True)
        Trophy.by_award(award, _update=True)


    @validate(link=nop('link'),
              campaign=nop('campaign'))
    def GET_fetch_promo(self, link, campaign):
        promo_tuples = [promote.PromoTuple(link, 1., campaign)]
        builder = CampaignBuilder(promo_tuples,
                                  wrap=default_thing_wrapper(),
                                  keep_fn=promote.is_promoted)
        promoted_links = builder.get_items()[0]
        if promoted_links:
            s = SpotlightListing(promoted_links=promoted_links).listing()
            item = s.things[0]
            return spaceCompress(item.render())


    @noresponse(VUser(),
              ui_elem = VOneOf('id', ('organic',)))
    def POST_disable_ui(self, ui_elem):
        if ui_elem:
            pref = "pref_%s" % ui_elem
            if getattr(c.user, pref):
                setattr(c.user, "pref_" + ui_elem, False)
                c.user._commit()

    @validatedForm(type = VOneOf('type', ('click'), default = 'click'),
                   links = VByName('ids', thing_cls = Link, multiple = True))
    def GET_gadget(self, form, jquery, type, links):
        if not links and type == 'click':
            # malformed cookie, clear it out
            set_user_cookie('recentclicks2', '')

        if not links:
            return

        content = ClickGadget(links).make_content()

        jquery('.gadget').show().find('.click-gadget').html(
            spaceCompress(content))

    @noresponse()
    def POST_tb_commentspanel_show(self):
        # this preference is allowed for non-logged-in users
        c.user.pref_frame_commentspanel = True
        c.user._commit()

    @noresponse()
    def POST_tb_commentspanel_hide(self):
        # this preference is allowed for non-logged-in users
        c.user.pref_frame_commentspanel = False
        c.user._commit()

    @json_validate(query=VPrintable('query', max_length=50),
                   include_over_18=VBoolean('include_over_18', default=True))
    def POST_search_reddit_names(self, responder, query, include_over_18):
        names = []
        if query:
            names = search_reddits(query, include_over_18)

        return {'names': names}

    @validate(link = VByName('link_id', thing_cls = Link))
    def POST_expando(self, link):
        if not link:
            abort(404, 'not found')

        wrapped = wrap_links(link)
        wrapped = list(wrapped)[0]
        link_child = wrapped.link_child
        if not link_child:
            abort(404, 'not found')
        return websafe(spaceCompress(link_child.content()))

    @validatedForm(VUser('password', default=''),
                   VModhash(),
                   VOneTimePassword("otp",
                                    required=not g.disable_require_admin_otp),
                   remember=VBoolean("remember"),
                   dest=VDestination())
    def POST_adminon(self, form, jquery, remember, dest):
        if form.has_errors('password', errors.WRONG_PASSWORD):
            return

        if form.has_errors("otp", errors.WRONG_PASSWORD,
                                  errors.NO_OTP_SECRET,
                                  errors.RATELIMIT):
            return

        if remember:
            self.remember_otp(c.user)

        self.enable_admin_mode(c.user)
        form.redirect(dest)

    @validatedForm(VUser("password", default=""),
                   VModhash())
    def POST_generate_otp_secret(self, form, jquery):
        if form.has_errors("password", errors.WRONG_PASSWORD):
            return

        secret = totp.generate_secret()
        g.cache.set('otp_secret_' + c.user._id36, secret, time=300)
        jquery("body").make_totp_qrcode(secret)

    @validatedForm(VUser(),
                   VModhash(),
                   otp=nop("otp"))
    def POST_enable_otp(self, form, jquery, otp):
        if form.has_errors("password", errors.WRONG_PASSWORD):
            return

        secret = g.cache.get("otp_secret_" + c.user._id36)
        if not secret:
            c.errors.add(errors.EXPIRED, field="otp")
            form.has_errors("otp", errors.EXPIRED)
            return

        if not VOneTimePassword.validate_otp(secret, otp):
            c.errors.add(errors.WRONG_PASSWORD, field="otp")
            form.has_errors("otp", errors.WRONG_PASSWORD)
            return

        c.user.otp_secret = secret
        c.user._commit()

        form.redirect("/prefs/otp")

    @validatedForm(VUser("password", default=""),
                   VOneTimePassword("otp", required=True),
                   VModhash())
    def POST_disable_otp(self, form, jquery):
        if form.has_errors("password", errors.WRONG_PASSWORD):
            return

        if form.has_errors("otp", errors.WRONG_PASSWORD,
                                  errors.NO_OTP_SECRET,
                                  errors.RATELIMIT):
            return

        c.user.otp_secret = ""
        c.user._commit()
        form.redirect("/prefs/otp")

    @json_validate(query=VLength("query", max_length=50))
    @api_doc(api_section.subreddits, extensions=["json"])
    def GET_subreddits_by_topic(self, responder, query):
        if not g.CLOUDSEARCH_SEARCH_API:
            return []

        query = query and query.strip()
        if not query or len(query) < 2:
            return []

        exclude = Subreddit.default_subreddits()

        faceting = {"reddit":{"sort":"-sum(text_relevance)", "count":20}}
        results = SearchQuery(query, sort="relevance", faceting=faceting,
                              syntax="plain").run()

        sr_results = []
        for sr, count in results.subreddit_facets:
            if (sr._id in exclude or (sr.over_18 and not c.over18)
                  or sr.type == "archived"):
                continue

            sr_results.append({
                "name": sr.name,
            })

        return sr_results

    @noresponse(VUser(),
                VModhash(),
                client=VOAuth2ClientID())
    @api_doc(api_section.apps)
    def POST_revokeapp(self, client):
        if client:
            client.revoke(c.user)

    @validatedForm(VUser(),
                   VModhash(),
                   name=VRequired('name', errors.NO_TEXT,
                                  docs=dict(name="a name for the app")),
                   about_url=VSanitizedUrl('about_url'),
                   icon_url=VSanitizedUrl('icon_url'),
                   redirect_uri=VSanitizedUrl('redirect_uri'))
    @api_doc(api_section.apps)
    def POST_updateapp(self, form, jquery, name, about_url, icon_url, redirect_uri):
        if (form.has_errors('name', errors.NO_TEXT) |
            form.has_errors('redirect_uri', errors.BAD_URL, errors.NO_URL)):
            return

        description = request.post.get('description', '')

        client_id = request.post.get('client_id')
        if client_id:
            # client_id was specified, updating existing OAuth2Client
            client = OAuth2Client.get_token(client_id)
            if not client:
                form.set_html('.status', _('invalid client id'))
                return
            if getattr(client, 'deleted', False):
                form.set_html('.status', _('cannot update deleted app'))
                return
            if not client.has_developer(c.user):
                form.set_html('.status', _('app does not belong to you'))
                return

            client.name = name
            client.description = description
            client.about_url = about_url or ''
            client.redirect_uri = redirect_uri
            client._commit()
            form.set_html('.status', _('application updated'))
            apps = PrefApps([], [client])
            jquery('#developed-app-%s' % client._id).replaceWith(
                apps.call('developed_app', client, collapsed=False))
        else:
            # client_id was omitted or empty, creating new OAuth2Client
            client = OAuth2Client._new(name=name,
                                       description=description,
                                       about_url=about_url or '',
                                       redirect_uri=redirect_uri)
            client._commit()
            client.add_developer(c.user)
            form.set_html('.status', _('application created'))
            apps = PrefApps([], [client])
            jquery('#developed-apps > h1').show()
            jquery('#developed-apps > ul').append(
                apps.call('developed_app', client, collapsed=False))

    @validatedForm(VUser(),
                   VModhash(),
                   client=VOAuth2ClientDeveloper(),
                   account=VExistingUname('name'))
    @api_doc(api_section.apps)
    def POST_adddeveloper(self, form, jquery, client, account):
        if not client:
            return
        if form.has_errors('name', errors.USER_DOESNT_EXIST, errors.NO_USER):
            return
        if client.has_developer(account):
            c.errors.add(errors.DEVELOPER_ALREADY_ADDED, field='name')
            form.set_error(errors.DEVELOPER_ALREADY_ADDED, 'name')
            return
        try:
            client.add_developer(account)
        except OverflowError:
            c.errors.add(errors.TOO_MANY_DEVELOPERS, field='')
            form.set_error(errors.TOO_MANY_DEVELOPERS, '')
            return

        form.set_html('.status', _('developer added'))
        apps = PrefApps([], [client])
        (jquery('#app-developer-%s input[name="name"]' % client._id).val('')
            .closest('.prefright').find('ul').append(
                apps.call('editable_developer', client, account)))

    @validatedForm(VUser(),
                   VModhash(),
                   client=VOAuth2ClientDeveloper(),
                   account=VExistingUname('name'))
    @api_doc(api_section.apps)
    def POST_removedeveloper(self, form, jquery, client, account):
        if client and account and not form.has_errors('name'):
            client.remove_developer(account)
            if account._id == c.user._id:
                jquery('#developed-app-%s' % client._id).fadeOut()
            else:
                jquery('li#app-dev-%s-%s' % (client._id, account._id)).fadeOut()

    @noresponse(VUser(),
                VModhash(),
                client=VOAuth2ClientDeveloper())
    @api_doc(api_section.apps)
    def POST_deleteapp(self, client):
        if client:
            client.deleted = True
            client._commit()

    @validatedMultipartForm(VUser(),
                            VModhash(),
                            client=VOAuth2ClientDeveloper(),
                            icon_file=VLength(
                                'file', max_length=1024*128,
                                docs=dict(file="an icon (72x72)")))
    @api_doc(api_section.apps)
    def POST_setappicon(self, form, jquery, client, icon_file):
        if not media.can_upload_icon():
            form.set_error(errors.NOT_SUPPORTED, '')
        if not icon_file:
            form.set_error(errors.TOO_LONG, 'file')
        if not form.has_error():
            filename = 'icon-%s' % client._id
            try:
                client.icon_url = media.upload_icon(filename, icon_file,
                                                    (72, 72))
            except IOError, ex:
                c.errors.add(errors.BAD_IMAGE,
                             msg_params=dict(message=ex.message),
                             field='file')
                form.set_error(errors.BAD_IMAGE, 'file')
            else:
                client._commit()
                form.set_html('.status', 'uploaded')
                jquery('#developed-app-%s .app-icon img'
                       % client._id).attr('src', client.icon_url)
                jquery('#developed-app-%s .ajax-upload-form'
                       % client._id).hide()
                jquery('#developed-app-%s .edit-app-icon-button'
                       % client._id).toggleClass('collapsed')

    @json_validate(VUser(),
                   VModhash(),
                   comment=VByName("comment", thing_cls=Comment))
    def POST_generate_payment_blob(self, responder, comment):
        if not comment:
            abort(400, "Bad Request")

        comment_sr = Subreddit._byID(comment.sr_id, data=True)
        if not comment_sr.allow_comment_gilding:
            abort(403, "Forbidden")

        try:
            recipient = Account._byID(comment.author_id, data=True)
        except NotFound:
            self.abort404()

        if recipient._deleted:
            self.abort404()

        return generate_blob(dict(
            goldtype="gift",
            account_id=c.user._id,
            account_name=c.user.name,
            status="initialized",
            signed=False,
            recipient=recipient.name,
            giftmessage=None,
            comment=comment._fullname,
        ))
