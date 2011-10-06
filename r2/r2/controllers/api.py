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
from reddit_base import RedditController, MinimalController, set_user_cookie
from reddit_base import cross_domain, paginated_listing

from pylons.i18n import _
from pylons import c, request, response

from validator import *

from r2.models import *

from r2.lib.utils import get_title, sanitize_url, timeuntil, set_last_modified
from r2.lib.utils import query_string, timefromnow, randstr
from r2.lib.utils import timeago, tup, filter_links, levenshtein
from r2.lib.pages import EnemyList, FriendList, ContributorList, ModList, \
    FlairList, FlairCsv, BannedList, BoringPage, FormPage, CssError, \
    UploadedImage, ClickGadget, UrlParser, WrappedUser
from r2.lib.utils.trial_utils import indict, end_trial, trial_info
from r2.lib.pages.things import wrap_links, default_thing_wrapper

from r2.lib import spreadshirt
from r2.lib.menus import CommentSortMenu
from r2.lib.captcha import get_iden
from r2.lib.strings import strings
from r2.lib.filters import _force_unicode, websafe_json, websafe, spaceCompress
from r2.lib.db import queries
from r2.lib.db.queries import changed
from r2.lib import promote
from r2.lib.media import force_thumbnail, thumbnail_url
from r2.lib.comment_tree import delete_comment
from r2.lib import tracking,  cssfilter, emailer
from r2.lib.subreddit_search import search_reddits
from r2.lib.log import log_text
from r2.lib.filters import safemarkdown

import csv
from datetime import datetime, timedelta
from md5 import md5
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
    def POST_new_captcha(self, form, jquery, *a, **kw):
        jquery("body").captcha(get_iden())


class ApiController(RedditController):
    """
    Controller which deals with almost all AJAX site interaction.  
    """

    @validatedForm()
    def ajax_login_redirect(self, form, jquery, dest):
        form.redirect("/login" + query_string(dict(dest=dest)))

    @validate(link1 = VUrl(['url']),
              link2 = VByName('id'),
              count = VLimit('limit'))
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
    def GET_me(self, responder):
        if c.user_is_loggedin:
            return Wrapped(c.user).render()
        else:
            return {}

    @validatedForm(VCaptcha(),
                   name=VRequired('name', errors.NO_NAME),
                   email=ValidEmails('email', num = 1),
                   reason = VOneOf('reason', ('ad_inq', 'feedback', "i18n")),
                   message=VRequired('text', errors.NO_TEXT),
                   )
    def POST_feedback(self, form, jquery, name, email, reason, message):
        if not (form.has_errors('name',     errors.NO_NAME) or
                form.has_errors('email',    errors.BAD_EMAILS) or
                form.has_errors('text', errors.NO_TEXT) or
                form.has_errors('captcha', errors.BAD_CAPTCHA)):

            if reason == 'ad_inq':
                emailer.ad_inq_email(email, message, name, reply_to = '')
            elif reason == 'i18n':
                emailer.i18n_email(email, message, name, reply_to = '')
            else:
                emailer.feedback_email(email, message, name, reply_to = '')
            form.set_html(".status", _("thanks for your message! "
                            "you should hear back from us shortly."))
            form.set_inputs(text = "", captcha = "")
            form.find(".spacer").hide()
            form.find(".btn").hide()

    POST_ad_inq = POST_feedback


    @validatedForm(VCaptcha(),
                   VUser(),
                   VModhash(),
                   ip = ValidIP(),
                   to = VMessageRecipient('to'),
                   subject = VRequired('subject', errors.NO_SUBJECT),
                   body = VMarkdown(['text', 'message']))
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

            queries.new_message(m, inbox_rel)

    @validatedForm(VUser(),
                   VCaptcha(),
                   VRatelimit(rate_user = True, rate_ip = True,
                              prefix = "rate_submit_"),
                   ip = ValidIP(),
                   sr = VSubmitSR('sr', 'kind'),
                   url = VUrl(['url', 'sr']),
                   title = VTitle('title'),
                   save = VBoolean('save'),
                   selftext = VSelfText('text'),
                   kind = VOneOf('kind', ['link', 'self']),
                   then = VOneOf('then', ('tb', 'comments'),
                                 default='comments'),
                   extension = VLength("extension", 20))
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

# Uncomment if we want to let spammers know we're on to them
#            if banmsg:
#                form.set_html(".field-url.BAD_URL", banmsg)
#                return

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

                    compose_link = ("/message/compose?to=%23" + sr.name +
                                    "&subject=Exemption+request")

                    verify_link = "/verify?reason=submit"

                    if c.user.email_verified:
                        msg = strings.verified_quota_msg % dict(link=compose_link)
                    else:
                        msg = strings.unverified_quota_msg % dict(link1=verify_link,
                                                                  link2=compose_link)

                md = safemarkdown(msg)
                form.set_html(".status", md)
                return

        # well, nothing left to do but submit it
        l = Link._submit(request.post.title, url if kind == 'link' else 'self',
                         c.user, sr, ip, spam=c.user._spam)

        if banmsg:
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

    @validatedForm(VRatelimit(rate_ip = True,
                              rate_user = True,
                              prefix = 'fetchtitle_'),
                   VUser(),
                   url = VSanitizedUrl(['url']))
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

    @cross_domain([g.origin, g.https_endpoint], allow_credentials=True)
    @validatedForm(VDelay("login"),
                   user = VLogin(['user', 'passwd']),
                   username = VLength('user', max_length = 100),
                   rem    = VBoolean('rem'))
    def POST_login(self, form, responder, user, username, rem):
        if responder.has_errors('vdelay', errors.RATELIMIT):
            return

        if login_throttle(username, wrong_password = responder.has_errors("passwd",
                                                     errors.WRONG_PASSWORD)):
            VDelay.record_violation("login", seconds=1, growfast=True)
            c.errors.add(errors.WRONG_PASSWORD, field = "passwd")

        if not responder.has_errors("passwd", errors.WRONG_PASSWORD):
            self._login(responder, user, rem)

    @cross_domain([g.origin, g.https_endpoint], allow_credentials=True)
    @validatedForm(VCaptcha(),
                   VRatelimit(rate_ip = True, prefix = "rate_register_"),
                   name = VUname(['user']),
                   email = ValidEmails("email", num = 1),
                   password = VPassword(['passwd', 'passwd2']),
                   rem = VBoolean('rem'))
    def POST_register(self, form, responder, name, email,
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

            c.user = user
            self._login(responder, user, rem)

    @noresponse(VUser(),
                VModhash(),
                container = VByName('id'))
    def POST_leavemoderator(self, container):
        """
        Handles self-removal as moderator from a subreddit as rendered
        in the subreddit sidebox on any of that subreddit's pages.
        """
        if container and container.is_moderator(c.user):
            container.remove_moderator(c.user)
            Subreddit.special_reddits(c.user, "moderator", _update=True)

    @noresponse(VUser(),
                VModhash(),
                container = VByName('id'))
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
                container = VByName('container'),
                type = VOneOf('type', ('friend', 'enemy', 'moderator', 
                                       'contributor', 'banned')))
    def POST_unfriend(self, nuser, iuser, container, type):
        """
        Handles removal of a friend (a user-user relation) or removal
        of a user's privileges from a subreddit (a user-subreddit
        relation).  The user can either be passed in by name (nuser)
        or by fullname (iuser).  'container' will either be the
        current user or the subreddit.

        """
        # The user who made the request must be an admin or a moderator
        # for the privilege change to succeed.

        victim = iuser or nuser

        if (not c.user_is_admin
            and (type in ('moderator','contributor','banned')
                 and not c.site.is_moderator(c.user))):
            abort(403, 'forbidden')
        if (type == 'moderator' and not
            (c.user_is_admin or container.can_demod(c.user, victim))):
            abort(403, 'forbidden')
        # if we are (strictly) unfriending, the container had better
        # be the current user.
        if type in ("friend", "enemy") and container != c.user:
            abort(403, 'forbidden')
        fn = getattr(container, 'remove_' + type)
        fn(victim)

        if type == "friend" and c.user.gold:
            c.user.friend_rels_cache(_update=True)

        if type in ("moderator", "contributor"):
            Subreddit.special_reddits(victim, type, _update=True)

    @validatedForm(VUser(),
                   VModhash(),
                   ip = ValidIP(),
                   friend = VExistingUname('name'),
                   container = VByName('container'),
                   type = VOneOf('type', ('friend', 'moderator',
                                          'contributor', 'banned')),
                   note = VLength('note', 300))
    def POST_friend(self, form, jquery, ip, friend,
                    container, type, note):
        """
        Complement to POST_unfriend: handles friending as well as
        privilege changes on subreddits.
        """
        fn = getattr(container, 'add_' + type)

        # The user who made the request must be an admin or a moderator
        # for the privilege change to succeed.
        if (not c.user_is_admin
            and (type in ('moderator','contributor', 'banned')
                 and not c.site.is_moderator(c.user))):
            abort(403,'forbidden')

        # if we are (strictly) friending, the container
        # had better be the current user.
        if type == "friend" and container != c.user:
            abort(403,'forbidden')

        elif form.has_errors("name", errors.USER_DOESNT_EXIST, errors.NO_USER):
            return

        new = fn(friend)

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
                   banned=BannedList).get(type)
        form.set_inputs(name = "")
        form.set_html(".status:first", _("added"))
        if new and cls:
            user_row = cls().user_row(friend)
            jquery("#" + type + "-table").show(
                ).find("table").insert_table_rows(user_row)

            if type != 'friend':
                msg = strings.msg_add_friend.get(type)
                subj = strings.subj_add_friend.get(type)
                if msg and subj and friend.name != c.user.name:
                    # fullpath with domain needed or the markdown link
                    # will break
                    d = dict(url = container.path,
                             title = container.title)
                    msg = msg % d
                    subj = subj % d
                    item, inbox_rel = Message._new(c.user, friend,
                                                   subj, msg, ip)

                    queries.new_message(item, inbox_rel)


    @validatedForm(VGold(),
                   friend = VExistingUname('name'),
                   note = VLength('note', 300))
    def POST_friendnote(self, form, jquery, friend, note):
        c.user.add_friend_note(friend, note)
        form.set_html('.status', _("saved"))

    @validatedForm(VUser('curpass', default = ''),
                   VModhash(),
                   email = ValidEmails("email", num = 1),
                   password = VPassword(['newpass', 'verpass']),
                   verify = VBoolean("verify"))
    def POST_update(self, form, jquery, email, password, verify):
        """
        handles /prefs/update for updating email address and password.
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
                   areyousure1 = VOneOf('areyousure1', ('yes', 'no')),
                   areyousure2 = VOneOf('areyousure2', ('yes', 'no')),
                   areyousure3 = VOneOf('areyousure3', ('yes', 'no')))
    def POST_delete_user(self, form, jquery,
                         areyousure1, areyousure2, areyousure3):
        """
        /prefs/delete.  Make sure there are three yes's.
        """
        if areyousure1 == areyousure2 == areyousure3 == 'yes':
            c.user.delete()
            form.redirect('/?deleted=true')
        else:
            form.set_html('.status', _("see? you don't really want to leave"))

    @noresponse(VUser(),
                VModhash(),
                thing = VByNameIfAuthor('id'))
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
            sr = thing.subreddit_slow
            queries.delete_links(thing)

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

    @noresponse(VUser(),
                VModhash(),
                VSrCanAlter('id'),
                thing = VByName('id'))
    def POST_marknsfw(self, thing):
        thing.over_18 = True
        thing._commit()

        # flag search indexer that something has changed
        changed(thing)

    @noresponse(VUser(),
                VModhash(),
                VSrCanAlter('id'),
                thing = VByName('id'))
    def POST_unmarknsfw(self, thing):
        thing.over_18 = False
        thing._commit()

        # flag search indexer that something has changed
        changed(thing)

    @noresponse(VUser(), VModhash(),
                thing = VByName('id'))
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

    @noresponse(VUser(), VModhash(),
                thing=VByName('id'))
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

    @validatedForm(VUser(),
                   VModhash(),
                   item = VByNameIfAuthor('thing_id'),
                   text = VSelfText('text'))
    def POST_editusertext(self, form, jquery, item, text):
        if (not form.has_errors("text",
                                errors.NO_TEXT, errors.TOO_LONG) and
            not form.has_errors("thing_id", errors.NOT_AUTHOR)):

            if isinstance(item, Comment):
                kind = 'comment'
                old = item.body
                item.body = text
            elif isinstance(item, Link):
                kind = 'link'
                if not getattr(item, "is_self", False):
                    return abort(403, "forbidden")
                old = item.selftext
                item.selftext = text

            if item._deleted:
                return abort(403, "forbidden")

            if (item._date < timeago('3 minutes')
                or (item._ups + item._downs > 2)):
                item.editted = True

            #try:
            #    lv = levenshtein(old, text)
            #    item.levenshtein = getattr(item, 'levenshtein', 0) + lv
            #except:
            #    pass

            item._commit()

            changed(item)

            if kind == 'link':
                set_last_modified(item, 'comments')

            wrapper = default_thing_wrapper(expand_children = True)
            jquery(".content").replace_things(item, True, True, wrap = wrapper)
            jquery(".content .link .rank").hide()

    @validatedForm(VUser(),
                   VModhash(),
                   VRatelimit(rate_user = True, rate_ip = True,
                              prefix = "rate_comment_"),
                   ip = ValidIP(),
                   parent = VSubmitParent(['thing_id', 'parent']),
                   comment = VMarkdown(['text', 'comment']))
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

    @noresponse(VUser(),
                VModhash(),
                vote_type = VVotehash(('vh', 'id')),
                ip = ValidIP(),
                dir = VInt('dir', min=-1, max=1),
                thing = VByName('id'))
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

    @validatedForm(VUser(),
                   VModhash(),
                   # nop is safe: handled after auth checks below
                   stylesheet_contents = nop('stylesheet_contents'),
                   op = VOneOf('op',['save','preview']))
    def POST_subreddit_stylesheet(self, form, jquery,
                                  stylesheet_contents = '', op='save'):
        if not c.site.can_change_stylesheet(c.user):
            return self.abort(403,'forbidden')

        if g.css_killswitch:
            return self.abort(403,'forbidden')

        # validation is expensive.  Validate after we've confirmed
        # that the changes will be allowed
        parsed, report = cssfilter.validate_css(stylesheet_contents)

        if report.errors:
            error_items = [ CssError(x).render(style='html')
                            for x in sorted(report.errors) ]
            form.set_html(".status", _('validation errors'))
            form.set_html(".errors ul", ''.join(error_items))
            form.find('.errors').show()
        else:
            form.find('.errors').hide()
            form.set_html(".errors ul", '')

        stylesheet_contents_parsed = parsed.cssText if parsed else ''
        # if the css parsed, we're going to apply it (both preview & save)
        if not report.errors:
            jquery.apply_stylesheet(stylesheet_contents_parsed)
        if not report.errors and op == 'save':
            c.site.stylesheet_contents      = stylesheet_contents_parsed
            c.site.stylesheet_contents_user = stylesheet_contents

            c.site.stylesheet_hash = md5(stylesheet_contents_parsed).hexdigest()

            set_last_modified(c.site,'stylesheet_contents')

            c.site._commit()

            form.set_html(".status", _('saved'))
            form.set_html(".errors ul", "")

        elif op == 'preview':
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


    @validatedForm(VSrModerator(),
                   VModhash(),
                   name = VCssName('img_name'))
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


    @validatedForm(VSrModerator(),
                   VModhash(),
                   sponsor = VInt("sponsor", min = 0, max = 1))
    def POST_delete_sr_header(self, form, jquery, sponsor):
        """
        Called when the user request that the header on a sr be reset.
        """
        # just in case we need to kill this feature from XSS
        if g.css_killswitch:
            return self.abort(403,'forbidden')
        if sponsor and c.user_is_admin:
            c.site.sponsorship_img = None
            c.site._commit()
        elif c.site.header:
            # reset the header image on the page
            jquery('#header-img').attr("src", DefaultSR.header)
            c.site.header = None
            c.site._commit()
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

    @validate(VSrModerator(),
              VModhash(),
              file = VLength('file', max_length=1024*500),
              name = VCssName("name"),
              form_id = VLength('formid', max_length = 100), 
              header = VInt('header', max=1, min=0),
              sponsor = VInt('sponsor', max=1, min=0))
    def POST_upload_sr_img(self, file, header, sponsor, name, form_id):
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
        try:
            cleaned = cssfilter.clean_image(file,'PNG')
            if header:
                # there is one and only header, and it is unnumbered
                resource = None 
            elif sponsor and c.user_is_admin:
                resource = "sponsor"
            elif not name:
                # error if the name wasn't specified or didn't satisfy
                # the validator
                errors['BAD_CSS_NAME'] = _("bad image name")
            else:
                resource = c.site.add_image(name, max_num = g.max_sr_images)
                c.site._commit()

        except cssfilter.BadImage:
            # if the image doesn't clean up nicely, abort
            errors["IMAGE_ERROR"] = _("bad image")
        except ValueError:
            # the add_image method will raise only on too many images
            errors['IMAGE_ERROR'] = (
                _("too many images (you only get %d)") % g.max_sr_images)

        if any(errors.values()):
            return  UploadedImage("", "", "", errors = errors).render()
        else: 
            # with the image num, save the image an upload to s3.  the
            # header image will be of the form "${c.site._fullname}.png"
            # while any other image will be ${c.site._fullname}_${resource}.png
            new_url = cssfilter.save_sr_image(c.site, cleaned,
                                              resource = resource)
            if header:
                c.site.header = new_url
            elif sponsor and c.user_is_admin:
                c.site.sponsorship_img = new_url
            c.site._commit()

            return UploadedImage(_('saved'), new_url, name, 
                                 errors = errors, form_id = form_id).render()


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
                   description = VMarkdown("description", max_length = 5120),
                   lang = VLang("lang"),
                   over_18 = VBoolean('over_18'),
                   allow_top = VBoolean('allow_top'),
                   show_media = VBoolean('show_media'),
                   show_cname_sidebar = VBoolean('show_cname_sidebar'),
                   type = VOneOf('type', ('public', 'private', 'restricted')),
                   link_type = VOneOf('link_type', ('any', 'link', 'self')),
                   ip = ValidIP(),
                   sponsor_text =VLength('sponsorship-text', max_length = 500),
                   sponsor_name =VLength('sponsorship-name', max_length = 64),
                   sponsor_url = VLength('sponsorship-url', max_length = 500),
                   css_on_cname = VBoolean("css_on_cname"),
                   )
    def POST_site_admin(self, form, jquery, name, ip, sr,
                        sponsor_text, sponsor_url, sponsor_name, **kw):
        # the status button is outside the form -- have to reset by hand
        form.parent().set_html('.status', "")

        redir = False
        kw = dict((k, v) for k, v in kw.iteritems()
                  if k in ('name', 'title', 'domain', 'description', 'over_18',
                           'show_media', 'show_cname_sidebar', 'type', 'link_type', 'lang',
                           "css_on_cname", "header_title", 
                           'allow_top'))

        #if a user is banned, return rate-limit errors
        if c.user._spam:
            time = timeuntil(datetime.now(g.tz) + timedelta(seconds=600))
            c.errors.add(errors.RATELIMIT, {'time': time})

        domain = kw['domain']
        cname_sr = domain and Subreddit._by_domain(domain)
        if cname_sr and (not sr or sr != cname_sr):
            c.errors.add(errors.USED_CNAME)

        if not sr and form.has_errors("ratelimit", errors.RATELIMIT):
            pass
        elif not sr and form.has_errors("name", errors.SUBREDDIT_EXISTS,
                                        errors.BAD_SR_NAME):
            form.find('#example_name').hide()
        elif form.has_errors('title', errors.NO_TEXT, errors.TOO_LONG):
            form.find('#example_title').hide()
        elif form.has_errors('domain', errors.BAD_CNAME, errors.USED_CNAME):
            form.find('#example_domain').hide()
        elif (form.has_errors(None, errors.INVALID_OPTION) or
              form.has_errors('description', errors.TOO_LONG)):
            pass

        #creating a new reddit
        elif not sr:
            #sending kw is ok because it was sanitized above
            sr = Subreddit._new(name = name, author_id = c.user._id, ip = ip,
                                **kw)

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

            if not sr.domain:
                del kw['css_on_cname']
            for k, v in kw.iteritems():
                setattr(sr, k, v)
            sr._commit()

            #update the domain cache if the domain changed
            if sr.domain != old_domain:
                Subreddit._by_domain(old_domain, _update = True)
                Subreddit._by_domain(sr.domain, _update = True)

            # flag search indexer that something has changed
            changed(sr)
            form.parent().set_html('.status', _("saved"))

        # don't go any further until the form validates
        if form.has_error():
            return
        elif redir:
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
        hex = md5(repr(d)).hexdigest()
        key = "indextankfeedback-%s-%s-%s" % (timestamp[:10], request.ip, hex)
        d['timestamp'] = timestamp
        d['approval'] = approval
        g.hardcache.set(key, d, time=86400 * 7)

    @noresponse(VUser(), VModhash(),
                why = VSrCanBan('id'),
                thing = VByName('id'))
    def POST_remove(self, why, thing):
        if getattr(thing, "promoted", None) is None:
            end_trial(thing, why + "-removed")
            admintools.spam(thing, False, not c.user_is_admin, c.user.name)

    @noresponse(VUser(), VModhash(),
                why = VSrCanBan('id'),
                thing = VByName('id'))
    def POST_approve(self, why, thing):
        if not thing: return
        if thing._deleted: return

        end_trial(thing, why + "-approved")
        admintools.unspam(thing, c.user.name)

    @validatedForm(VUser(), VModhash(),
                   VCanDistinguish(('id', 'how')),
                   thing = VByName('id'),
                   how = VOneOf('how', ('yes','no','admin','special')))
    def POST_distinguish(self, form, jquery, thing, how):
        if not thing:return
        thing.distinguished = how
        thing._commit()
        wrapper = default_thing_wrapper(expand_children = True)
        w = wrap_links(thing, wrapper)
        jquery(".content").replace_things(w, True, True)
        jquery(".content .link .rank").hide()

    @noresponse(VUser(),
                VModhash(),
                thing = VByName('id'))
    def POST_save(self, thing):
        if not thing: return
        r = thing._save(c.user)
        if r:
            queries.new_savehide(r)

    @noresponse(VUser(),
                VModhash(),
                thing = VByName('id'))
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

    def unread_handler(self, thing, unread):
        if not thing:
            return
        # if the message has a recipient, try validating that
        # desitination first (as it is cheaper and more common)
        queries.set_unread(thing, c.user, unread)
        # if the message is for a subreddit, check that next
        if hasattr(thing, "sr_id"):
            sr = thing.subreddit_slow
            if sr and sr.is_moderator(c.user):
                queries.set_unread(thing, sr, unread)

    @noresponse(VUser(),
                VModhash(),
                thing = VByName('id'))
    def POST_unread_message(self, thing):
        self.unread_handler(thing, True)

    @noresponse(VUser(),
                VModhash(),
                thing = VByName('id'))
    def POST_read_message(self, thing):
        self.unread_handler(thing, False)

    @noresponse(VUser(),
                VModhash(),
                thing = VByName('id'))
    def POST_hide(self, thing):
        if not thing: return
        r = thing._hide(c.user)
        if r:
            queries.new_savehide(r)

    @noresponse(VUser(),
                VModhash(),
                thing = VByName('id'))
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
    def POST_morechildren(self, form, jquery, link, sort, children,
                          pv_hex, mc_id):
        user = c.user if c.user_is_loggedin else None

        mc_key = "morechildren-%s" % request.ip
        try:
            count = g.cache.incr(mc_key)
        except:
            g.cache.set(mc_key, 1, time=30)
            count = 1

        if count >= 10:
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


    @validatedForm(cache_evt = VHardCacheKey('email-reset', ('key',)),
                   password  = VPassword(['passwd', 'passwd2']))
    def POST_resetpassword(self, form, jquery, cache_evt, password):
        if form.has_errors('name', errors.EXPIRED):
            cache_evt.clear()
            form.redirect('/password?expired=true')
        elif form.has_errors('passwd',  errors.BAD_PASSWORD):
            pass
        elif form.has_errors('passwd2', errors.BAD_PASSWORD_MATCH):
            pass
        elif cache_evt.user:
            # successfully entered user name and valid new password
            change_password(cache_evt.user, password)
            g.hardcache.delete("%s_%s" % (cache_evt.cache_prefix, cache_evt.key))
            print "%s did a password reset for %s via %s" % (
                request.ip, cache_evt.user.name, cache_evt.key)
            self._login(jquery, cache_evt.user, '/')
            cache_evt.clear()


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


    @noresponse(VAdmin(),
                tr = VTranslation("lang"), 
                user = nop('user'))
    def POST_deltranslator(self, tr, user):
        if tr:
            tr.author.remove(user)
            tr.save()

    @noresponse(VUser(),
                VModhash(),
                action = VOneOf('action', ('sub', 'unsub')),
                sr = VByName('sr'))
    def POST_subscribe(self, action, sr):
        # only users who can make edits are allowed to subscribe.
        # Anyone can leave.
        if action != 'sub' or sr.can_comment(c.user):
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

    @noresponse(VAdmin(),
                tr = VTranslation("id"))
    def POST_disable_lang(self, tr):
        if tr:
            tr._is_enabled = False

    @noresponse(VAdmin(),
                tr = VTranslation("id"))
    def POST_enable_lang(self, tr):
        if tr:
            tr._is_enabled = True


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
                   award = VByName("fullname"),
                   colliding_award=VAwardByCodename(("codename", "fullname")),
                   codename = VLength("codename", max_length = 100),
                   title = VLength("title", max_length = 100),
                   awardtype = VOneOf("awardtype",
                                      ("regular", "manual", "invisible")),
                   imgurl = VLength("imgurl", max_length = 1000))
    def POST_editaward(self, form, jquery, award, colliding_award, codename,
                       title, awardtype, imgurl):
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
            Award._new(codename, title, awardtype, imgurl)
            form.set_html(".status", "saved. reload to see it.")
            return

        award.codename = codename
        award.title = title
        award.awardtype = awardtype
        award.imgurl = imgurl
        award._commit()
        form.set_html(".status", _('saved'))

    @validatedForm(VFlairManager(),
                   VModhash(),
                   user = VExistingUname("name", allow_deleted=True),
                   text = VFlairText("text"),
                   css_class = VFlairCss("css_class"))
    def POST_flair(self, form, jquery, user, text, css_class):
        # Check validation.
        if form.has_errors('name', errors.USER_DOESNT_EXIST, errors.NO_USER):
            return
        if form.has_errors('css_class', errors.BAD_CSS_NAME):
            form.set_html(".status:first", _('invalid css class'))
            return
        if form.has_errors('css_class', errors.TOO_MUCH_FLAIR_CSS):
            form.set_html(".status:first", _('too many css classes'))
            return

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

        if new:
            jquery.redirect('?name=%s' % user.name)
        else:
            jquery('input[name="text"]').data('saved', text)
            jquery('input[name="css_class"]').data('saved', css_class)
            form.set_html('.status', _('saved'))
            form.set_html(
                '.tagline',
                WrappedUser(user, force_show_flair=True).render(style='html'))

    @validate(VFlairManager(),
              VModhash(),
              flair_csv = nop('flair_csv'))
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

            user = VExistingUname('name', allow_deleted=True).run(name)
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

            if css_class and not VCssName('css_class').run(css_class):
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

        return BoringPage(_("API"), content = results).render()

    @validatedForm(VUser(),
                   VModhash(),
                   flair_enabled = VBoolean("flair_enabled"))
    def POST_setflairenabled(self, form, jquery, flair_enabled):
        setattr(c.user, 'flair_%s_enabled' % c.site._id, flair_enabled)
        c.user._commit()
        jquery.refresh()

    @validatedForm(VFlairManager(),
                   VModhash(),
                   flair_enabled = VBoolean("flair_enabled"),
                   flair_position = VOneOf("flair_position", ("left", "right")))
    def POST_flairconfig(self, form, jquery, flair_enabled, flair_position):
        c.site.flair_enabled = flair_enabled
        c.site.flair_position = flair_position
        c.site._commit()
        jquery.refresh()

    @paginated_listing(max_page_size=1000)
    @validate(VFlairManager(),
              user = VOptionalExistingUname('name'))
    def GET_flairlist(self, num, after, reverse, count, user):
        flair = FlairList(num, after, reverse, '', user)
        return BoringPage(_("API"), content = flair).render()

    @validatedForm(VAdminOrAdminSecret("secret"),
                   award = VByName("fullname"),
                   description = VLength("description", max_length=1000),
                   url = VLength("url", max_length=1000),
                   cup_hours = VFloat("cup_hours",
                                      coerce=False, min=0, max=24 * 365),
                   recipient = VExistingUname("recipient"))
    def POST_givetrophy(self, form, jquery, award, description,
                        url, cup_hours, recipient):
        if form.has_errors("award", errors.NO_TEXT):
            pass

        if form.has_errors("recipient", errors.USER_DOESNT_EXIST,
                                        errors.NO_USER):
            pass

        if form.has_errors("fullname", errors.NO_TEXT):
            pass

        if form.has_errors("cup_hours", errors.BAD_NUMBER):
            pass

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

    @validatedForm(VAdmin(),
                   account = VExistingUname("account"))
    def POST_removecup(self, form, jquery, account):
        if not account:
            return self.abort404()
        account.remove_cup()

    @validatedForm(VAdmin(),
                   trophy = VTrophy("trophy_fn"))
    def POST_removetrophy(self, form, jquery, trophy):
        if not trophy:
            return self.abort404()
        recipient = trophy._thing1
        award = trophy._thing2

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
    def POST_search_reddit_names(self, query):
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

    @validatedForm(link = VByName('name', thing_cls = Link, multiple = False),
                   color = VOneOf('color', spreadshirt.ShirtPane.colors),
                   style = VOneOf('style', spreadshirt.ShirtPane.styles),
                   size  = VOneOf("size", spreadshirt.ShirtPane.sizes),
                   quantity = VInt("quantity", min = 1))
    def POST_shirt(self, form, jquery, link, color, style, size, quantity):
        if not g.spreadshirt_url:
            return self.abort404()
        else:
            res = spreadshirt.shirt_request(link, color, style, size, quantity)
            if res:
                form.set_html(".status", _("redirecting..."))
                jquery.redirect(res)
            else:    
                form.set_html(".status", _("error (sorry)"))
