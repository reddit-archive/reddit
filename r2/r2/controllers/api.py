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
from reddit_base import RedditController

from pylons.i18n import _
from pylons import c, request

from validator import *

from r2.models import *
import r2.models.thing_changes as tc

from r2.lib.utils import get_title, sanitize_url, timeuntil
from r2.lib.wrapped import Wrapped
from r2.lib.pages import FriendList, ContributorList, ModList, \
    BannedList, BoringPage, FormPage, NewLink

from r2.lib.menus import CommentSortMenu
from r2.lib.translation import Translator
from r2.lib.normalized_hot import expire_hot, is_top_link
from r2.lib.captcha import get_iden
from r2.lib import emailer
from r2.lib.strings import strings
from r2.config import cache

from simplejson import dumps

from r2.lib.jsonresponse import JsonResponse, Json
from r2.lib.jsontemplates import api_type

from datetime import datetime, timedelta
from r2.lib.organic import update_pos

def link_listing_by_url(url, count = None):
    try:
        links = tup(Link._by_url(url, sr = c.site))
        links.sort(key = lambda x: -x._score)
        if count is not None:
            links = links[:count]
    except NotFound:
        links = ()
        
    names = [l._fullname for l in links]
    builder = IDBuilder(names, num = 25)
    listing = LinkListing(builder).listing()
    return listing
            
    
class ApiController(RedditController):
    def response_func(self, **kw):
        return self.sendstring(dumps(kw))

    def link_exists(self, url, sr, message = False):
        try:    
            l = Link._by_url(url, sr)
            if message:
                return l.permalink + '?already_submitted=true'
            else:
                return l.permalink
        except NotFound:
            pass


    @validate(url = nop("url"),
              sr = VSubredditName,
              count = VLimit('limit'))
    def GET_info(self, url, sr, count):
        listing = link_listing_by_url(url, count = count)
        res = BoringPage(_("API"),
                         content = listing).render()
        return res
    
    @Json
    @validate(dest = nop('dest'))
    def POST_subscriptions(self, res, dest):
        """Updates a user's subscriptions after fiddling with them in the sr
        sidebar"""
        subs = {}
        for k, v in request.post.iteritems():
            if k.startswith('sr_sel_chx_'):
                subs[k[11:]] = (v == 'on')

        for sr in Subreddit._by_fullname(subs.keys(), data = True, 
                                         return_dict = False):
            self._subscribe(sr, subs[sr._fullname])
        res._redirect(dest)

    @Json
    @validate(VCaptcha(),
              name=VRequired('name', errors.NO_NAME),
              email=VRequired('email', errors.NO_EMAIL),
              replyto = nop('replyto'),
              reason = nop('reason'),
              message=VRequired('message', errors.NO_MESSAGE))
    def POST_feedback(self, res, name, email, replyto, reason, message):
        res._update('status', innerHTML = '')
        if res._chk_error(errors.NO_NAME):
            res._focus("name")
        elif res._chk_error(errors.NO_EMAIL):
            res._focus("email")
        elif res._chk_error(errors.NO_MESSAGE):
            res._focus("personal")
        elif res._chk_captcha(errors.BAD_CAPTCHA):
            pass

        if not res.error:
            if reason != 'ad_inq':
                emailer.feedback_email(email, message, name = name or '')
            else:
                emailer.ad_inq_email(email, message, name = name or '')
            res._update('success',
                        innerHTML=_("thanks for your message! you should hear back from us shortly."))
            res._update("personal", value='')
            res._update("captcha", value='')
            res._hide("wtf")


    POST_ad_inq = POST_feedback


    @Json
    @validate(VUser(),
              VModhash(),
              ip = ValidIP(),
              to = VExistingUname('to'),
              subject = VRequired('subject', errors.NO_SUBJECT),
              body = VMessage('message'))
    def POST_compose(self, res, to, subject, body, ip):
        res._update('status', innerHTML='')
        if (res._chk_error(errors.NO_USER) or
            res._chk_error(errors.USER_DOESNT_EXIST)):
            res._focus('to')
        elif res._chk_error(errors.NO_SUBJECT):
            res._focus('subject')
        elif (res._chk_error(errors.NO_MSG_BODY) or
              res._chk_error(errors.COMMENT_TOO_LONG)):
            res._focus('message')
        if not res.error:
            spam = (c.user._spam or
                    errors.BANNED_IP in c.errors or
                    errors.BANNED_DOMAIN in c.errors)
            
            m = Message._new(c.user, to, subject, body, ip, spam)
            res._update('success',
                        innerHTML=_("your message has been delivered"))
            res._update('to', value='')
            res._update('subject', value='')
            res._update('message', value='')
        else:
            res._update('success', innerHTML='')


    @validate(VUser(),
              VSRSubmitPage(),
              url = VRequired('url', None),
              title = VRequired('title', None))
    def GET_submit(self, url, title):
        if url and not request.get.get('resubmit'):
            listing = link_listing_by_url(url)
            redirect_link = None
            if listing.things:
                if len(listing.things) == 1:
                    redirect_link = listing.things[0]
                else:
                    subscribed = [l for l in listing.things
                                  if c.user_is_loggedin 
                                  and l.subreddit.is_subscriber_defaults(c.user)]
                    
                    #if there is only 1 link to be displayed, just go there
                    if len(subscribed) == 1:
                        redirect_link = subscribed[0]
                    else:
                        infotext = strings.multiple_submitted % \
                                   listing.things[0].resubmit_link()
                        res = BoringPage(_("seen it"),
                                         content = listing,
                                         infotext = infotext).render()
                        return res
                        
            if redirect_link:
                return self.redirect(redirect_link.already_submitted_link)
            
        captcha = Captcha() if c.user.needs_captcha() else None
        sr_names = Subreddit.submit_sr_names(c.user) if c.default_sr else ()

        return FormPage(_("submit"), 
                        content=NewLink(url=url or '',
                                        title=title or '',
                                        subreddits = sr_names,
                                        captcha=captcha)).render()


    @Json
    @validate(VUser(),
              VCaptcha(),
              ValidDomain('url'),
              VRatelimit(rate_user = True, rate_ip = True),
              ip = ValidIP(),
              sr = VSubmitSR('sr'),
              url = VUrl(['url', 'sr']),
              title = VTitle('title'),
              save = nop('save'),
              )
    def POST_submit(self, res, url, title, save, sr, ip):
        res._update('status', innerHTML = '')
        if url:
            res._update('url', value=url)
            
        should_ratelimit = sr.should_ratelimit(c.user, 'link')

        #remove the ratelimit error if the user's karma is high
        if not should_ratelimit:
            c.errors.remove(errors.RATELIMIT)

        # check for no url, or clear that error field on return
        if res._chk_errors((errors.NO_URL, errors.BAD_URL)):
            res._focus('url')
        elif res._chk_error(errors.ALREADY_SUB):
            link = Link._by_url(url, sr)
            res._redirect(link.already_submitted_link)
        #ratelimiter
        elif res._chk_error(errors.RATELIMIT):
            pass
        # check for title, otherwise look it up and return it
        elif res._chk_error(errors.NO_TITLE):
            # clear out this error
            res._chk_error(errors.TITLE_TOO_LONG)
            # try to fetch the title
            title = get_title(url)
            if title:
                res._update('title', value = title)
                res._focus('title')
                res._clear_error(errors.NO_TITLE)
                c.errors.remove(errors.NO_TITLE)
                return 
            res._focus('title')
        elif res._chk_error(errors.TITLE_TOO_LONG):
            res._focus('title')
        elif res._chk_captcha(errors.BAD_CAPTCHA):
            pass

        if res.error or not title: return

        # check whether this is spam:
        spam = (c.user._spam or
                errors.BANNED_IP in c.errors or
                errors.BANNED_DOMAIN in c.errors)

        # well, nothing left to do but submit it
        l = Link._submit(request.post.title, url, c.user, sr, ip, spam)
        if url.lower() == 'self':
            l.url = l.permalink
            l.is_self = True
            l._commit()
        Vote.vote(c.user, l, True, ip, spam)
        if save == 'on':
            l._save(c.user)
        #set the ratelimiter
        if should_ratelimit:
            VRatelimit.ratelimit(rate_user=True, rate_ip = True)

        # flag search indexer that something has changed
        tc.changed(l)

        res._redirect(l.permalink)


    def _login(self, res, user, dest='', rem = None):
        self.login(user, rem = rem)
        dest = dest or request.referer or '/'
        res._redirect(dest)

    @Json
    @validate(user = VLogin(['user_login', 'passwd_login']),
              op = VOneOf('op', options = ("login-main", "reg", "login"),
                          default = 'login'),
              dest = nop('dest'),
              rem = nop('rem'),
              reason = VReason('reason'))
    def POST_login(self, res, user, op, dest, rem, reason):
        if reason and reason[0] == 'redirect':
            dest = reason[1]

        res._update('status_' + op, innerHTML='')
        if res._chk_error(errors.WRONG_PASSWORD, op):
            res._focus('passwd_' + op)
        else:
            self._login(res, user, dest, rem == 'on')


    @Json
    @validate(VCaptcha(),
              VRatelimit(rate_ip = True),
              name = VUname(['user_reg']),
              email = nop('email_reg'),
              password = VPassword(['passwd_reg', 'passwd2_reg']),
              op = VOneOf('op', options = ("login-main", "reg", "login"),
                          default = 'login'),
              dest = nop('dest'),
              rem = nop('rem'),
              reason = VReason('reason'))
    def POST_register(self, res, name, email, password, op, dest, rem, reason):
        res._update('status_' + op, innerHTML='')
        if res._chk_error(errors.BAD_USERNAME, op):
            res._focus('user_reg')
        elif res._chk_error(errors.USERNAME_TAKEN, op):
            res._focus('user_reg')
        elif res._chk_error(errors.BAD_PASSWORD, op):
            res._focus('passwd_reg')
        elif res._chk_error(errors.BAD_PASSWORD_MATCH, op):
            res._focus('passwd2_reg')
        elif res._chk_error(errors.DRACONIAN, op):
            res._focus('legal_reg')
        elif res._chk_captcha(errors.BAD_CAPTCHA):
            pass
        elif res._chk_error(errors.RATELIMIT, op):
            pass

        if res.error:
            return

        user = register(name, password)
        VRatelimit.ratelimit(rate_ip = True)

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
            
        c.user = user
        if reason:
            if reason[0] == 'redirect':
                dest = reason[1]
            elif reason[0] == 'subscribe':
                for sr, sub in reason[1].iteritems():
                    self._subscribe(sr, sub)

        self._login(res, user, dest, rem)
    


    @validate(VUser(),
              VModhash(),
              container = VByName('id'),
              type = VOneOf('location', ('moderator',  'contributor')))
    @Json
    def POST_leave(self, res, container, type):
        if container and c.user:
            res._hide("pre_" + container._fullname)
            res._hide("thingrow_" + container._fullname)
            fn = getattr(container, 'remove_' + type)
            fn(c.user)

    @Json
    @validate(VUser(),
              VModhash(),
              ip = ValidIP(),
              action = VOneOf('action', ('add', 'remove')),
              redirect = nop('redirect'),
              friend = VExistingUname('name'),
              container = VByName('container'),
              type = VOneOf('type', ('friend', 'moderator', 'contributor', 'banned')))
    def POST_friend(self, res, ip, friend, action, redirect, container, type):
        res._update('status', innerHTML='')

        fn = getattr(container, action + '_' + type)

        if (not c.user_is_admin
            and (type in ('moderator','contributer','banned')
                 and not c.site.is_moderator(c.user))):

            abort(403,'forbidden')
        elif action == 'add':
            if res._chk_errors((errors.USER_DOESNT_EXIST,
                                errors.NO_USER)):
                res._focus('name')
            else:
                new = fn(friend)
                cls = dict(friend=FriendList,
                           moderator=ModList,
                           contributor=ContributorList,
                           banned=BannedList).get(type)
                res._update('name', value = '')
                
                #subscribing doesn't need a response
                if new and cls:
                    res.object = cls().ajax_user(friend).for_ajax('add')

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
                            Message._new(c.user, friend, subj, msg, ip,
                                         c.user._spam)
        elif action == 'remove' and friend:
            fn(friend)


    @Json
    @validate(VUser('curpass', default = ''),
              VModhash(),
              curpass = nop('curpass'),
              email = nop("email"),
              newpass = nop("newpass"),
              verpass = nop("verpass"),
              password = VPassword(['newpass', 'verpass']))
    def POST_update(self, res, email, curpass, password, newpass, verpass):
        res._update('status', innerHTML='')
        if res._chk_error(errors.WRONG_PASSWORD):
            res._focus('curpass')
            res._update('curpass', value='')
            return 
        updated = False
        if email and (not hasattr(c.user,'email')
                      or c.user.email != email):
            c.user.email = email
            c.user._commit()
            res._update('status', 
                        innerHTML=_('your email has been updated'))
            updated = True
            
        if newpass or verpass:
            if res._chk_error(errors.BAD_PASSWORD):
                res._focus('newpass')
            elif res._chk_error(errors.BAD_PASSWORD_MATCH):
                res._focus('verpass')
                res._update('verpass', value='')
            else:
                change_password(c.user, curpass, password)
                if updated:
                    res._update('status', 
                                innerHTML=_('your email and password have been updated'))
                else:
                    res._update('status', 
                                innerHTML=_('your password has been updated'))
                self.login(c.user)

    @Json
    @validate(VUser(),
              VModhash(),
              areyousure1 = nop('areyousure1'),
              areyousure2 = nop('areyousure2'),
              areyousure3 = nop('areyousure3'))
    def POST_delete_user(self, res, areyousure1, areyousure2, areyousure3):
        if areyousure1 == areyousure2 == areyousure3 == 'yes':
            c.user.delete()
            res._redirect('/?deleted=true')
        else:
            res._update('status', 
                        innerHTML = _("see? you don't really want to leave"))


    @Json
    @validate(VUser(),
              VModhash(),
              thing = VByNameIfAuthor('id'))
    def POST_del(self, res, thing):
        '''for deleting all sorts of things'''
        thing._deleted = True
        thing._commit()

        # flag search indexer that something has changed
        tc.changed(thing)

        #expire the item from the sr cache
        if isinstance(thing, Link):
            sr = thing.subreddit_slow
            expire_hot(sr)

        #comments have special delete tasks
        elif isinstance(thing, Comment):
            thing._delete()


    @Json
    @validate(VUser(), VModhash(),
              thing = VByName('id'))
    def POST_report(self, res, thing):
        '''for reporting...'''
        Report.new(c.user, thing)


    @Json
    @validate(VUser(), VModhash(),
              comment = VByNameIfAuthor('id'),
              body = VComment('comment'))
    def POST_editcomment(self, res, comment, body):
        res._update('status_' + comment._fullname, innerHTML = '')
        if (not res._chk_error(errors.BAD_COMMENT, comment._fullname) and 
            not res._chk_error(errors.NOT_AUTHOR, comment._fullname)):
            comment.body = body
            if not c.user_is_admin: comment.editted = True
            comment._commit()
            res._send_things(comment)

            # flag search indexer that something has changed
            tc.changed(comment)



    @Json
    @validate(VUser(),
              VModhash(),
              VRatelimit(rate_user = True, rate_ip = True, 
                         prefix = "rate_comment_"),
              ip = ValidIP(),
              parent = VSubmitParent('id'),
              comment = VComment('comment'))
    def POST_comment(self, res, parent, comment, ip):
        res._update('status_' + parent._fullname, innerHTML = '')

        should_ratelimit = True
        #check the parent type here cause we need that for the
        #ratelimit checks
        if isinstance(parent, Message):
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
            if not sr.should_ratelimit(c.user, 'comment'):
                should_ratelimit = False

        #remove the ratelimit error if the user's karma is high
        if not should_ratelimit:
            c.errors.remove(errors.RATELIMIT)

        if res._chk_error(errors.BAD_COMMENT, parent._fullname) or \
           res._chk_error(errors.COMMENT_TOO_LONG, parent._fullname) or \
           res._chk_error(errors.RATELIMIT, parent._fullname):
            res._focus("comment_reply_" + parent._fullname)
            return 
        res._show('reply_' + parent._fullname)
        res._update("comment_reply_" + parent._fullname, rows = 2)

        spam = (c.user._spam or
                errors.BANNED_IP in c.errors)
        
        if is_message:
            to = Account._byID(parent.author_id)
            subject = parent.subject
            re = "re: "
            if not subject.startswith(re):
                subject = re + subject
            item = Message._new(c.user, to, subject, comment, ip, spam)
            item.parent_id = parent._id
            res._send_things(item)
        else:
            item =  Comment._new(c.user, link, parent_comment, comment,
                                 ip, spam)
            Vote.vote(c.user, item, True, ip)
            res._update("comment_reply_" + parent._fullname, 
                        innerHTML='', value='')
            res._send_things(item)
            res._hide('noresults')
            # flag search indexer that something has changed
            tc.changed(item)

        #set the ratelimiter
        if should_ratelimit:
            VRatelimit.ratelimit(rate_user=True, rate_ip = True, prefix = "rate_comment_")

    @Json
    @validate(VUser(),
              VModhash(),
              vote_type = VVotehash(('vh', 'id')),
              ip = ValidIP(),
              dir = VInt('dir', min=-1, max=1),
              thing = VByName('id'))
    def POST_vote(self, res, dir, thing, ip, vote_type):
        ip = request.ip
        user = c.user
        spam = (c.user._spam or
                errors.BANNED_IP in c.errors or
                errors.CHEATER in c.errors)

        if thing:
            dir = (True if dir > 0
                   else False if dir < 0
                   else None)
            organic = vote_type == 'organic'
            Vote.vote(user, thing, dir, ip, spam, organic)

            # flag search indexer that something has changed
            tc.changed(thing)

    @Json
    @validate(VUser(),
              VModhash(),
              VRatelimit(rate_user = True,
                         rate_ip = True,
                         prefix = 'create_reddit_'),
              name = VSubredditName("name"),
              title = VSubredditTitle("title"),
              description = VSubredditDesc("description"),
              firsttext = nop("firsttext"),
              header = nop("headerfile"),
              lang = VLang("lang"),
              stylesheet = nop("stylesheet"),
              static_path = nop("staticdir"),
              ad_file = nop("ad_file"),
              sr = VByName('sr'),
              over_18 = VBoolean('over_18'),
              type = VOneOf('type', ('public', 'private', 'restricted'))
              )
    def POST_site_admin(self, res, name ='', sr = None, **kw):
        res._update('status', innerHTML = '')
        redir = False
        kw = dict((k, v) for k, v in kw.iteritems()
                  if v is not None
                  and k in ('name', 'title', 'description', 'firsttext',
                            'static_path', 'ad_file', 'over_18',
                            'type', 'header', 'lang', 'stylesheet'))

        #if a user is banned, return rate-limit errors
        if c.user._spam:
            time = timeuntil(datetime.now(g.tz) + timedelta(seconds=600))
            c.errors.add(errors.RATELIMIT, {'time': time})

        if not sr and res._chk_error(errors.RATELIMIT):
            pass
        elif not sr and res._chk_errors((errors.SUBREDDIT_EXISTS,
                                         errors.BAD_SR_NAME)):
            res._hide('example_name')
            res._focus('name')
        elif res._chk_errors((errors.NO_TITLE, errors.TITLE_TOO_LONG)):
            res._hide('example_title')
            res._focus('title')
        elif res._chk_error(errors.INVALID_SUBREDDIT_TYPE):
            pass
        elif res._chk_error(errors.DESC_TOO_LONG):
            res._focus('description')

        if not sr and not res.error:
            #sending kw is ok because it was sanitized above
            sr = Subreddit._new(name = name, **kw)
            Subreddit.subscribe_defaults(c.user)
            # make sure this user is on the admin list of that site!
            if sr.add_subscriber(c.user):
                sr._incr('_ups', 1)
            sr.add_moderator(c.user)
            sr.add_contributor(c.user)
            redir =  sr.path + "about/edit/"
            if not c.user_is_admin:
                VRatelimit.ratelimit(rate_user=True,
                                     rate_ip = True,
                                     prefix = "create_reddit_")

        if not res.error:
            #assume sr existed, or was just built
            for k, v in kw.iteritems():
                setattr(sr, k, v)
            sr._commit()

            # flag search indexer that something has changed
            tc.changed(sr)

        if redir:
            res._redirect(redir)

    @Json
    @validate(VModhash(),
              VSrCanBan('id'),
              thing = VByName('id'))
    def POST_ban(self, res, thing):
        thing.moderator_banned = not c.user_is_admin
        thing.banner = c.user.name
        thing._commit()
        # NB: change table updated by reporting
        unreport(thing, correct=True, auto=False)

    @Json
    @validate(VModhash(),
              VSrCanBan('id'),
              thing = VByName('id'))
    def POST_unban(self, res, thing):
        # NB: change table updated by reporting
        unreport(thing, correct=False)

    @Json
    @validate(VModhash(),
              VSrCanBan('id'),
              thing = VByName('id'))
    def POST_ignore(self, res, thing):
        # NB: change table updated by reporting
        unreport(thing, correct=False)

    @Json
    @validate(VUser(),
              VModhash(),
              thing = VByName('id'))
    def POST_save(self, res, thing):
        user = c.user
        thing._save(user)


    @Json
    @validate(VUser(),
              VModhash(),
              thing = VByName('id'))
    def POST_unsave(self, res, thing):
        user = c.user
        thing._unsave(user)


    @Json
    @validate(VUser(),
              VModhash(),
              thing = VByName('id'))
    def POST_hide(self, res, thing):
        thing._hide(c.user)


    @Json
    @validate(VUser(),
              VModhash(),
              thing = VByName('id'))
    def POST_unhide(self, res, thing):
        thing._unhide(c.user)

    @Json
    @validate(link = VByName('link_id'),
              sort = VMenu('where', CommentSortMenu),
              children = VCommentIDs('children'),
              depth = VInt('depth', min = 0, max = 8),
              mc_id = nop('id'))
    def POST_morechildren(self, res, link, sort, children, depth, mc_id):
        if children:
            builder = CommentBuilder(link, CommentSortMenu.operator(sort), children)
            items = builder.get_items(starting_depth = depth, num = 20)
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
#            a = _children(items[0].child.things)
            a = []
            for item in items:
                a.append(item)
                if hasattr(item, 'child'):
                    a.extend(_children(item.child.things))
                    item.child = None

            # the result is not always sufficient to replace the 
            # morechildren link
            if mc_id not in [x._fullname for x in a]:
                res._hide('thingrow_' + str(mc_id))
            res._send_things(a)


    def GET_bookmarklet(self, what):
        '''Controller for the functionality of the bookmarklets (not the distribution page)'''
        action = ''
        for type in ['like', 'dislike', 'save']:
            if what.startswith(type):
                action = type
                break
            
        url = sanitize_url(request.get.u)
        uh = request.get.get('uh', "")

        try:
            links = Link._by_url(url)
        except:
            links = []

        Subreddit.load_subreddits(links, return_dict = False)
        user = c.user if c.user_is_loggedin else None
        links = [l for l in links if l.subreddit_slow.can_view(user)]

        if links and not c.user_is_loggedin:
            return self.redirect("/static/css_login.png")
        elif links and c.user_is_loggedin:
            if not c.user.valid_hash(uh):
                return self.redirect("/static/css_update.png")
            elif action in ['like', 'dislike']:
                #vote up all of the links
                for link in links:
                    Vote.vote(c.user, link, action == 'like', request.ip)
            elif action == 'save':
                link = max(links, key = lambda x: x._score)
                link._save(c.user)
            return self.redirect("/static/css_%sd.png" % action)
        return self.redirect("/static/css_submit.png")


    @Json
    @validate(user = VUserWithEmail('name'))
    def POST_password(self, res, user):
        res._update('status', innerHTML = '')
        if res._chk_error(errors.USER_DOESNT_EXIST):
            res._focus('name')
        elif res._chk_error(errors.NO_EMAIL_FOR_USER):
            res._focus('name')
        else:
            emailer.password_email(user)
            res._success()
            
    @Json
    @validate(user = VCacheKey('reset', ('key', 'name')),
              key= nop('key'),
              password = VPassword(['passwd', 'passwd2']))
    def POST_resetpassword(self, res, user, key, password):
        res._update('status', innerHTML = '')
        if res._chk_error(errors.BAD_PASSWORD):
            res._focus('passwd')
        elif res._chk_error(errors.BAD_PASSWORD_MATCH):
            res._focus('passwd2')
        elif errors.BAD_USERNAME in c.errors:
            cache.delete(str('reset_%s' % key))
            return res._redirect('/password')
        elif user:
            cache.delete(str('reset_%s' % key))
            change_password(user, password)
            self._login(res, user, '/resetpassword')


    @Json
    @validate(VUser())
    def POST_frame(self, res):
        c.user.pref_frame = True
        c.user._commit()


    @Json
    @validate(VUser())
    def POST_noframe(self, res):
        c.user.pref_frame = False
        c.user._commit()


    @Json
    @validate(VUser(),
              where=nop('where'),
              sort = nop('sort'))
    def POST_sort(self, res, where, sort):
        if where.startswith('sort_'):
            setattr(c.user, where, sort)
        c.user._commit()

    @Json
    def POST_new_captcha(self, res, *a, **kw):
        res.captcha = dict(iden = get_iden(), refresh = True)

    @Json
    @validate(VAdmin(),
              l = nop('id'))
    def POST_deltranslator(self, res, l):
        lang, a = l.split('_')
        if a and Translator.exists(lang):
            tr = Translator(locale = lang)
            tr.author.remove(a)
            tr.save()


    @Json
    @validate(VUser(),
              VModhash(),
              action = VOneOf('action', ('sub', 'unsub')),
              sr = VByName('sr'))
    def POST_subscribe(self, res, action, sr):
        self._subscribe(sr, action == 'sub')
    
    def _subscribe(self, sr, sub):
        Subreddit.subscribe_defaults(c.user)

        if sub:
            if sr.add_subscriber(c.user):
                sr._incr('_ups', 1)
        else:
            if sr.remove_subscriber(c.user):
                sr._incr('_ups', -1)
        tc.changed(sr)


    @Json
    @validate(VAdmin(),
              lang = nop("id"))
    def POST_disable_lang(self, res, lang):
        if lang and Translator.exists(lang):
            tr = Translator(locale = lang)
            tr._is_enabled = False
        

    @Json
    @validate(VAdmin(),
              lang = nop("id"))
    def POST_enable_lang(self, res, lang):
        if lang and Translator.exists(lang):
            tr = Translator(locale = lang)
            tr._is_enabled = True

    def action_cookie(action):
        s = action + request.ip + request.user_agent
        return sha.new(s).hexdigest()


    @Json
    @validate(num_margin = VCssMeasure('num_margin'),
              mid_margin = VCssMeasure('mid_margin'),
              links = VFullNames('links'))
    def POST_fetch_links(self, res, num_margin, mid_margin, links):
        # TODO: redundant with listingcontroller.  Perhaps part of reddit_base or utils
        def builder_wrapper(thing):
            if c.user.pref_compress and isinstance(thing, Link):
                thing.__class__ = LinkCompressed
                thing.score_fmt = Score.points
            return Wrapped(thing)

        b = IDBuilder([l._fullname for l in links], 
                      wrap = builder_wrapper)
        l = OrganicListing(b)
        l.num_margin = num_margin
        l.mid_margin = mid_margin
        res.object = res._thing(l.listing(), action = 'populate')

    @Json
    @validate(pos = VInt('pos', min = 0, max = 100))
    def POST_update_pos(self, res, pos):
        if pos is not None:
            update_pos(c.user, pos)


    @Json
    @validate(VUser(),
              ui_elem = VOneOf('id', ('organic',)))
    def POST_disable_ui(self, res, ui_elem):
        if ui_elem:
            pref = "pref_%s" % ui_elem
            if getattr(c.user, pref):
                setattr(c.user, "pref_" + ui_elem, False)
                c.user._commit()
