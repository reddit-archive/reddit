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
# All portions of the code written by reddit are Copyright (c) 2006-2012 reddit
# Inc. All Rights Reserved.
###############################################################################

from reddit_base import RedditController, MinimalController, set_user_cookie
from reddit_base import cross_domain, paginated_listing

from pylons.i18n import _
from pylons import c, request, response

from validator import *

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
from r2.lib.utils.trial_utils import indict, end_trial, trial_info
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

from r2.models import wiki
from r2.lib.merge import ConflictException

import csv
from collections import defaultdict
from datetime import datetime, timedelta
import hashlib
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
    @api_doc(api_section.misc)
    def POST_new_captcha(self, form, jquery, *a, **kw):
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

    
    @require_oauth2_scope("read")
    @validate(link1 = VUrl(['url']),
              link2 = VByName('id'),
              count = VLimit('limit'))
    @api_doc(api_section.links_and_comments)
    def GET_info(self, link1, link2, count):
        """
        Gets a listing of links which have the provided url.  
        """
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
        """
        Get info about the currently authenticated user.

        Response includes a modhash, karma, and new mail status.
        """
        if c.user_is_loggedin:
            return Wrapped(c.user).render()
        else:
            return {}

    @json_validate(user=VUname("user"))
    @api_doc(api_section.users, extensions=["json"])
    def GET_username_available(self, responder, user):
        """
        Check whether a username is available for registration.
        """
        if not (responder.has_errors("user", errors.BAD_USERNAME)):
            return bool(user)

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
                   subject = VRequired('subject', errors.NO_SUBJECT),
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
                   selftext = VSelfText('text'),
                   kind = VOneOf('kind', ['link', 'self']),
                   then = VOneOf('then', ('tb', 'comments'),
                                 default='comments'),
                   extension = VLength("extension", 20))
    @api_doc(api_section.links_and_comments)
    def POST_submit(self, form, jquery, url, selftext, kind, title,
                    save, sr, ip, then, extension):
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

                banmsg = is_banned_domain(url, request.ip)
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
                    reddiquette_link = "/help/reddiquette" 

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

        # well, nothing left to do but submit it
        l = Link._submit(request.post.title, url if kind == 'link' else 'self',
                         c.user, sr, ip, spam=c.user._spam)

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
            queries.new_savehide(r)

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

    @cross_domain(allow_credentials=True)
    @api_doc(api_section.account)
    def POST_login(self, *args, **kwargs):
        return self._handle_login(*args, **kwargs)

    @cross_domain(allow_credentials=True)
    @api_doc(api_section.account)
    def POST_register(self, *args, **kwargs):
        return self._handle_register(*args, **kwargs)

    @validatedForm(user = VThrottledLogin(['user', 'passwd']),
                   rem = VBoolean('rem'))
    def _handle_login(self, form, responder, user, rem):
        if not (responder.has_errors("vdelay", errors.RATELIMIT) or
                responder.has_errors("passwd", errors.WRONG_PASSWORD)):
            self._login(responder, user, rem)

    @validatedForm(VCaptcha(),
                   VRatelimit(rate_ip = True, prefix = "rate_register_"),
                   name = VUname(['user']),
                   email = ValidEmails("email", num = 1),
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
            
            user = register(name, password)
            VRatelimit.ratelimit(rate_ip = True, prefix = "rate_register_")

            #anything else we know (email, languages)?
            if email:
                user.email = email

            user.registration_ip = request.ip
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
            Subreddit.special_reddits(c.user, "moderator", _update=True)
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
            Subreddit.special_reddits(c.user, "contributor", _update=True)

    @noresponse(VUser(),
                VModhash(),
                nuser = VExistingUname('name'),
                iuser = VByName('id'),
                container = nop('container'),
                type = VOneOf('type', ('friend', 'enemy', 'moderator',
                                       'wikicontributor', 'banned',
                                       'wikibanned', 'contributor')))
    @api_doc(api_section.users)
    def POST_unfriend(self, nuser, iuser, container, type):
        """
        Handles removal of a friend (a user-user relation) or removal
        of a user's privileges from a subreddit (a user-subreddit
        relation).  The user can either be passed in by name (nuser)
        or by fullname (iuser).  If type is friend or enemy, 'container'
        will be the current user, otherwise the subreddit must be set.
        """
        sr_types = ('moderator', 'contributor', 'banned', 'wikibanned', 'wikicontributor')
        if type in sr_types:
            container = c.site
        else:
            container = VByName('container').run(container)
            if not container:
                return

        # The user who made the request must be an admin or a moderator
        # for the privilege change to succeed.
        victim = iuser or nuser
        if (not c.user_is_admin
            and (type in sr_types and not container.is_moderator(c.user))):
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
        if new and type in sr_types:
            action = dict(banned='unbanuser', moderator='removemoderator',
                          wikicontributor='removewikicontributor',
                          wikibanned='wikiunbanned',
                          contributor='removecontributor').get(type, None)
            ModAction.create(container, c.user, action, target=victim)

        if type == "friend" and c.user.gold:
            c.user.friend_rels_cache(_update=True)

        if type in ("moderator", "contributor"):
            Subreddit.special_reddits(victim, type, _update=True)

    @validatedForm(VUser(),
                   VModhash(),
                   ip = ValidIP(),
                   friend = VExistingUname('name'),
                   container = nop('container'),
                   type = VOneOf('type', ('friend', 'moderator', 'wikicontributor',
                                          'contributor', 'banned', 'wikibanned')),
                   note = VLength('note', 300))
    @api_doc(api_section.users)
    def POST_friend(self, form, jquery, ip, friend,
                    container, type, note):
        """
        Complement to POST_unfriend: handles friending as well as
        privilege changes on subreddits.
        """
        sr_types = ('moderator', 'contributor', 'banned',
                    'wikicontributor', 'wikibanned')
        if type in sr_types:
            container = c.site
        else:
            container = VByName('container').run(container)
            if not container:
                return
        fn = getattr(container, 'add_' + type)

        # The user who made the request must be an admin or a moderator
        # for the privilege change to succeed.
        if (not c.user_is_admin
            and (type in sr_types and not container.is_moderator(c.user))):
            abort(403,'forbidden')
        
        if type in sr_types and not c.user_is_admin:
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

        new = fn(friend)

        # Log this action
        if new and type in sr_types:
            action = dict(banned='banuser', moderator='addmoderator',
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

        if type in ("moderator", "contributor"):
            Subreddit.special_reddits(friend, type, _update=True)

        cls = dict(friend=FriendList,
                   moderator=ModList,
                   contributor=ContributorList,
                   wikicontributor=WikiMayContributeList,
                   banned=BannedList, wikibanned=WikiBannedList).get(type)
        form.set_inputs(name = "")
        form.set_html(".status:first", _("added"))
        if new and cls:
            user_row = cls().user_row(friend)
            jquery("#" + type + "-table").show(
                ).find("table").insert_table_rows(user_row)

            if type != 'friend' and (type != 'banned' or
                                     friend.has_interacted_with(container)):
                msg = strings.msg_add_friend.get(type)
                subj = strings.subj_add_friend.get(type)
                if msg and subj and friend.name != c.user.name:
                    # fullpath with domain needed or the markdown link
                    # will break
                    if isinstance(container, Subreddit):
                        title = "%s: %s" % (container.path.rstrip("/"),
                                            container.title)
                    else:
                        title = container.title
                    d = dict(url = container.path,
                             title = title)
                    msg = msg % d
                    subj = subj % d
                    if type == 'banned':
                        from_sr = True
                        sr = container
                    else:
                        from_sr = False
                        sr = None
                    item, inbox_rel = Message._new(c.user, friend, subj, msg,
                                                   ip, from_sr=from_sr, sr=sr)

                    queries.new_message(item, inbox_rel)


    @validatedForm(VGold(),
                   friend = VExistingUname('name'),
                   note = VLength('note', 300))
    def POST_friendnote(self, form, jquery, friend, note):
        c.user.add_friend_note(friend, note)
        form.set_html('.status', _("saved"))

    @validatedForm(VUser('curpass', default=''),
                   VModhash(),
                   password = VPassword(['curpass', 'curpass']),
                   dest = VDestination())
    @api_doc(api_section.account)
    def POST_clear_sessions(self, form, jquery, password, dest):
        """
        Clear all session cookies and update the current one.

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
                c.user.email = email
                # unverified email for now
                c.user.email_verified = None
                c.user._commit()
                Award.take_away("verified_email", c.user)
                updated = True
            if verify:
                # TODO: rate limit this?
                emailer.verify_email(c.user, request.referer)
                form.set_html('.status',
                     _("you should be getting a verification email shortly."))
            else:
                form.set_html('.status', _('your email has been updated'))

        # user is removing their email
        if (not email and c.user.email and 
            form.has_errors("email", errors.NO_EMAILS)):
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
        """
        Delete an account.

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
        if not thing: return
        '''for deleting all sorts of things'''
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
                d = inbox_class._fast_query(recipient, thing, ("inbox", "selfreply"))
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
        thing.over_18 = False
        thing._commit()

        if c.user._id != thing.author_id:
            ModAction.create(thing.subreddit_slow, c.user, target=thing,
                             action='marknsfw', details='remove')

        # flag search indexer that something has changed
        changed(thing)

    @noresponse(VUser(), VModhash(),
                thing = VByName('id'))
    @api_doc(api_section.links_and_comments)
    def POST_report(self, thing):
        '''for reporting...'''
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
            queries.new_savehide(r)
        # TODO: be nice to be able to remove comments that are reported
        # from a user's inbox so they don't have to look at them.
        elif isinstance(thing, Comment):
            pass

        if c.user._spam or c.user.ignorereports:
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
        # or PM). Check that 'thing' would have showed up in the
        # user's inbox at some point
        if isinstance(thing, Message):
            if thing.to_id != c.user._id:
                return
        elif isinstance(thing, Comment):
            parent_id = getattr(thing, 'parent_id', None)
            link_id = thing.link_id
            if parent_id:
                parent_comment = Comment._byID(parent_id)
                parent_author_id = parent_comment.author_id
            else:
                parent_link = Link._byID(link_id)
                parent_author_id = parent_link.author_id
            if parent_author_id != c.user._id:
                return

        block_acct = Account._byID(thing.author_id)
        if block_acct.name in g.admins:
            return
        c.user.add_enemy(block_acct)

    @noresponse(VAdmin(), VModhash(),
                thing = VByName('id'))
    def POST_indict(self, thing):
        '''put something on trial'''
        if not thing:
            log_text("indict: no thing", level="warning")

        indict(thing)

    @require_oauth2_scope("edit")
    @validatedForm(VUser(),
                   VModhash(),
                   item = VByNameIfAuthor('thing_id'),
                   text = VSelfText('text'))
    @api_doc(api_section.links_and_comments)
    def POST_editusertext(self, form, jquery, item, text):
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
        should_ratelimit = True
        #check the parent type here cause we need that for the
        #ratelimit checks
        if isinstance(parent, Message):
            if not getattr(parent, "repliable", True):
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
            if parent_age.days > g.REPLY_AGE_LIMIT:
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
                   emails = ValidEmails("share_to"),
                   reply_to = ValidEmails("replyto", num = 1), 
                   message = VLength("message", max_length = 1000), 
                   thing = VByName('parent'))
    def POST_share(self, shareform, jquery, emails, thing, share_from, reply_to,
                   message):

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
            c.user.add_share_emails(emails)
            c.user._commit()
            link = jquery.things(thing._fullname)
            link.set_html(".share", _("shared"))
            shareform.html("<div class='clearleft'></div>"
                           "<p class='error'>%s</p>" % 
                           _("your link has been shared."))

            emailer.share(thing, emails, from_name = share_from or "",
                          body = message or "", reply_to = reply_to or "")

            #set the ratelimiter
            if should_ratelimit:
                VRatelimit.ratelimit(rate_user=True, rate_ip = True,
                                     prefix = "rate_share_")

    @noresponse(VUser(),
                VModhash(),
                ip = ValidIP(),
                dir = VInt('dir', min=-1, max=1),
                thing = VByName('id'))
    def POST_juryvote(self, dir, thing, ip):
        if not thing:
            log_text("juryvote: no thing", level="warning")
            return

        if not ip:
            log_text("juryvote: no ip", level="warning")
            return

        if dir is None:
            log_text("juryvote: no dir", level="warning")
            return

        j = Jury.by_account_and_defendant(c.user, thing)

        if not trial_info([thing]).get(thing._fullname,False):
            log_text("juryvote: not on trial", level="warning")
            return

        if not j:
            log_text("juryvote: not on the jury", level="warning")
            return

        log_text("juryvote",
                 "%s cast a %d juryvote on %s" % (c.user.name, dir, thing._id36),
                 level="info")

        j._name = str(dir)
        j._date = c.start_time
        j._commit()

    @require_oauth2_scope("vote")
    @noresponse(VUser(),
                VModhash(),
                vote_type = VVotehash(('vh', 'id')),
                ip = ValidIP(),
                dir = VInt('dir', min=-1, max=1),
                thing = VByName('id'))
    @api_doc(api_section.links_and_comments)
    def POST_vote(self, dir, thing, ip, vote_type):
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
            return self.abort(403,'forbidden')
        
        if report.errors:
            error_items = [ CssError(x).render(style='html')
                            for x in sorted(report.errors) ]
            form.set_html(".status", _('validation errors'))
            form.set_html(".errors ul", ''.join(error_items))
            form.find('.errors').show()
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
    @validatedForm(VSrModerator(),
                   VModhash(),
                   name = VCssName('img_name'))
    @api_doc(api_section.subreddits)
    def POST_delete_sr_img(self, form, jquery, name):
        """
        Called called upon requested delete on /about/stylesheet.
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
    @validatedForm(VSrModerator(),
                   VModhash(),
                   sponsor = VInt("sponsor", min = 0, max = 1))
    @api_doc(api_section.subreddits)
    def POST_delete_sr_header(self, form, jquery, sponsor):
        """
        Called when the user request that the header on a sr be reset.
        """
        # just in case we need to kill this feature from XSS
        if g.css_killswitch:
            return self.abort(403,'forbidden')
        if sponsor and c.user_is_admin:
            c.site.sponsorship_img = None
            c.site.sponsorship_size = None
            c.site._commit()
        elif c.site.header:
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
    @validate(VSrModerator(),
              VModhash(),
              file = VLength('file', max_length=1024*500),
              name = VCssName("name"),
              img_type = VImageType('img_type'),
              form_id = VLength('formid', max_length = 100), 
              header = VInt('header', max=1, min=0),
              sponsor = VSubredditSponsorship('sponsor'))
    @api_doc(api_section.subreddits)
    def POST_upload_sr_img(self, file, header, sponsor, name, form_id, img_type):
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
        
        if not sponsor and not header:
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
            elif sponsor and c.user_is_admin:
                c.site.sponsorship_img = new_url
                c.site.sponsorship_size = size
            if add_image_to_sr:
                c.site.add_image(name, url = new_url)
            c.site._commit()

            if not sponsor:
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
                   name = VSubredditName("name"),
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
                   show_cname_sidebar = VBoolean('show_cname_sidebar'),
                   type = VOneOf('type', ('public', 'private', 'restricted', 'archived')),
                   link_type = VOneOf('link_type', ('any', 'link', 'self')),
                   wikimode = VOneOf('wikimode', ('disabled', 'modonly', 'anyone')),
                   wiki_edit_karma = VInt("wiki_edit_karma", coerce=False, num_default=0, min=0),
                   wiki_edit_age = VInt("wiki_edit_age", coerce=False, num_default=0, min=0),
                   ip = ValidIP(),
                   sponsor_text =VLength('sponsorship-text', max_length = 500),
                   sponsor_name =VLength('sponsorship-name', max_length = 64),
                   sponsor_url = VLength('sponsorship-url', max_length = 500),
                   css_on_cname = VBoolean("css_on_cname"),
                   )
    @api_doc(api_section.subreddits)
    def POST_site_admin(self, form, jquery, name, ip, sr,
                        sponsor_text, sponsor_url, sponsor_name, **kw):
        
        def apply_wikid_field(sr, form, pagename, value, prev, field, error):
            id_field_name = 'prev_%s_id' % field
            try:
                wikipage = wiki.WikiPage.get(sr, pagename)
            except tdb_cassandra.NotFound:
                wikipage = wiki.WikiPage.create(sr, pagename)
            try:
                wr = wikipage.revise(value, previous=prev, author=c.user.name)
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
                           'show_media', 'show_cname_sidebar', 'type', 'link_type', 'lang',
                           'css_on_cname', 'header_title', 'over_18',
                           'wikimode', 'wiki_edit_karma', 'wiki_edit_age',
                           'allow_top', 'public_description'))

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
        elif sr.is_moderator(c.user) or c.user_is_admin:

            if c.user_is_admin:
                sr.sponsorship_text = sponsor_text or ""
                sr.sponsorship_url = sponsor_url or None
                sr.sponsorship_name = sponsor_name or None

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
                why = VSrCanBan('id'),
                thing = VByName('id'),
                spam = VBoolean('spam', default=True))
    @api_doc(api_section.moderation)
    def POST_remove(self, why, thing, spam):

        # Don't remove a promoted link
        if getattr(thing, "promoted", None):
            return

        end_trial(thing, why + "-removed")

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
                why = VSrCanBan('id'),
                thing = VByName('id'))
    @api_doc(api_section.moderation)
    def POST_approve(self, why, thing):
        if not thing: return
        if thing._deleted: return
        end_trial(thing, why + "-approved")
        kw = {'target': thing}
        if thing._spam:
            kw['details'] = 'unspam'
            train_spam = True
            insert = True
        else:
            kw['details'] = 'confirm_ham'
            train_spam = False
            insert = False

        admintools.unspam(thing, c.user.name, train_spam=train_spam,
                          insert=insert)

        if isinstance(thing, (Link, Comment)):
            sr = thing.subreddit_slow
            action = 'approve' + thing.__class__.__name__.lower()
            ModAction.create(sr, c.user, action, **kw)

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
        original = thing.distinguished if hasattr(thing, 'distinguished') else 'no'
        if how == original:
            log_modaction = False   # Distinguish unchanged
        elif how in ('admin', 'special'):
            log_modaction = False   # Add admin/special
        elif original in ('admin', 'special') and how == 'no':
            log_modaction = False  # Remove admin/special
        elif how == 'no':
            log_kw['details'] = 'remove'    # yes --> no
        else:
            pass    # no --> yes

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
        if not thing: return
        r = thing._save(c.user)
        if r:
            queries.new_savehide(r)

    @noresponse(VUser(),
                VModhash(),
                thing = VByName('id'))
    @api_doc(api_section.links_and_comments)
    def POST_unsave(self, thing):
        if not thing: return
        r = thing._unsave(c.user)
        if r:
            queries.new_savehide(r)

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
        if not thing: return
        r = thing._hide(c.user)
        if r:
            queries.new_savehide(r)

    @noresponse(VUser(),
                VModhash(),
                thing = VByName('id'))
    @api_doc(api_section.links_and_comments)
    def POST_unhide(self, thing):
        if not thing: return
        r = thing._unhide(c.user)
        if r:
            queries.new_savehide(r)


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
                   pv_hex = VPrintable('pv_hex', 40),
                   mc_id = nop('id'))
    @api_doc(api_section.links_and_comments)
    def POST_morechildren(self, form, jquery, link, sort, children,
                          pv_hex, mc_id):
        user = c.user if c.user_is_loggedin else None

        mc_key = "morechildren-%s" % request.ip
        try:
            count = g.cache.incr(mc_key)
        except:
            g.cache.set(mc_key, 1, time=30)
            count = 1

        # Anything above 15 hits in 30 seconds violates the
        # "1 request per 2 seconds" rule of the API
        if count > 15:
            if user:
                name = user.name
            else:
                name = "(unlogged user)"
            g.log.warning("%s on %s hit morechildren %d times in 30 seconds"
                          % (name, request.ip, count))
            # TODO: redirect to rickroll or something

        if not link or not link.subreddit_slow.can_view(user):
            return abort(403,'forbidden')

        if pv_hex:
            c.previous_visits = g.cache.get(pv_hex)

        if children:
            builder = CommentBuilder(link, CommentSortMenu.operator(sort),
                                     children)
            listing = Listing(builder, nextprev = False)
            items = listing.get_items(num = 20)
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
                    queries.new_savehide(r)
                return self.redirect("/static/css_%sd.png" % action)
        return self.redirect("/static/css_submit.png")


    @validatedForm(VUser(),
                   code = VPrintable("code", 30))
    def POST_claimgold(self, form, jquery, code):
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
                form.set_html(".status", _("claimed! now go to someone's userpage and give them a present!"))
            else:
                admintools.engolden(c.user, days)

                g.cache.set("recent-gold-" + c.user.name, True, 600)
                form.set_html(".status", _("claimed!"))
                jquery(".lounge").show()

        # Activate any errors we just manually set
        form.has_errors("code", errors.INVALID_CODE, errors.CLAIMED_CODE,
                        errors.NO_TEXT)

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

        # successfully entered user name and valid new password
        change_password(user, password)
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

    @validatedForm(VSponsor(),
                   ad = VByName("fullname"),
                   colliding_ad=VAdByCodename(("codename", "fullname")),
                   codename = VLength("codename", max_length = 100),
                   imgurl = VLength("imgurl", max_length = 1000),
                   raw_html = VLength("raw_html", max_length = 10000),
                   linkurl = VLength("linkurl", max_length = 1000))
    def POST_editad(self, form, jquery, ad, colliding_ad, codename,
                    imgurl, raw_html, linkurl):
        if form.has_errors(("codename", "imgurl", "linkurl"),
                           errors.NO_TEXT):
            pass

        if form.has_errors(("codename"), errors.INVALID_OPTION):
            form.set_html(".status", "some other ad has that codename")
            pass

        if form.has_error():
            return

        if ad is None:
            Ad._new(codename,
                    imgurl=imgurl,
                    raw_html=raw_html,
                    linkurl=linkurl)
            form.set_html(".status", "saved. reload to see it.")
            return

        ad.codename = codename
        ad.imgurl = imgurl
        ad.raw_html = raw_html
        ad.linkurl = linkurl
        ad._commit()
        form.set_html(".status", _('saved'))

    @validatedForm(VSponsor(),
                   ad = VByName("fullname"),
                   sr = VSubmitSR("community"),
                   weight = VInt("weight",
                                 coerce=False, min=0, max=100000),
                   )
    def POST_assignad(self, form, jquery, ad, sr, weight):
        if form.has_errors("ad", errors.NO_TEXT):
            pass

        if form.has_errors("community", errors.SUBREDDIT_REQUIRED,
            errors.SUBREDDIT_NOEXIST, errors.SUBREDDIT_NOTALLOWED):
            pass

        if form.has_errors("fullname", errors.NO_TEXT):
            pass

        if form.has_errors("weight", errors.BAD_NUMBER):
            pass

        if form.has_error():
            return

        if ad.codename == "DART" and sr.name == g.default_sr and weight != 100:
            log_text("Bad default DART weight",
                     "The default DART weight can only be 100, not %s."
                     % weight,
                     "error")
            abort(403, 'forbidden')

        existing = AdSR.by_ad_and_sr(ad, sr)

        if weight is not None:
            if existing:
                existing.weight = weight
                existing._commit()
            else:
                AdSR._new(ad, sr, weight)

            form.set_html(".status", _('saved'))

        else:
            if existing:
                existing._delete()
                AdSR.by_ad(ad, _update=True)
                AdSR.by_sr(sr, _update=True)

            form.set_html(".status", _('deleted'))


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
    @validatedForm(VFlairManager(),
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
                if not c.user_is_admin and not site.is_moderator(c.user):
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
    @validatedForm(VFlairManager(),
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
    @validate(VFlairManager(),
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
        VFlairManager(),
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
    @validatedForm(VFlairManager(),
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
    @validatedForm(VFlairManager(),
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
    @validatedForm(VFlairManager(), VModhash(),
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
        if user and not (c.user_is_admin or c.site.is_moderator(c.user)):
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

        if not site.is_moderator(c.user) and not c.user_is_admin:
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

            if ((c.site.is_moderator(c.user) or c.user_is_admin)
                and c.user != user):
                ModAction.create(c.site, c.user, action='editflair',
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

            if ((c.site.is_moderator(c.user) or c.user_is_admin)):
                ModAction.create(c.site, c.user, action='editflair',
                                 target=link, details='flair_edit')

            # Push some client-side updates back to the browser.

            jquery('.id-%s .entry .linkflair' % link._fullname).remove()
            title_path = '.id-%s .entry > .title > .title' % link._fullname

            # TODO: move this to a template
            if flair_template:
                flair = '<span class="linkflair %s">%s</span>' % (
                    ' '.join('linkflair-' + c for c in css_class.split()), text)
                if c.site.link_flair_position == 'left':
                    jquery(title_path).before(flair)
                elif c.site.link_flair_position == 'right':
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

    @validatedForm(links = VByName('links', thing_cls = Link, multiple = True),
                   show = VByName('show', thing_cls = Link, multiple = False))
    def POST_fetch_links(self, form, jquery, links, show):
        l = wrap_links(links, listing_cls = SpotlightListing,
                       num_margin = 0, mid_margin = 0)
        jquery(".content").replace_things(l, stubs = True)

        if show:
            jquery('.organic-listing .link:visible').hide()
            jquery('.organic-listing .id-%s' % show._fullname).show()

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

    @json_validate(query = VPrintable('query', max_length = 50))
    def POST_search_reddit_names(self, responder, query):
        names = []
        if query:
            names = search_reddits(query)

        return {'names': names}

    @validate(link = VByName('link_id', thing_cls = Link))
    def POST_expando(self, link):
        if not link:
            abort(404, 'not found')

        wrapped = wrap_links(link)
        wrapped = list(wrapped)[0]
        return websafe(spaceCompress(wrapped.link_child.content()))

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
                                  docs=dict(name=_("a name for the app"))),
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
                                docs=dict(file=_("an icon (72x72)"))))
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
