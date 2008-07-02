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
from r2.lib.db.thing import Thing, Relation, NotFound, MultiRelation
from r2.lib.utils import base_url, tup, domain, worker
from account import Account
from subreddit import Subreddit
from printable import Printable
from r2.config import cache
from r2.lib.memoize import memoize, clear_memo
from r2.lib import utils
from r2.lib.db.operators import lower, base_url
from mako.filters import url_escape
from r2.lib.strings import strings, Score

from pylons import c, g, request
from pylons.i18n import ungettext

import random

class LinkExists(Exception): pass

# defining types
class Link(Thing, Printable):
    _data_int_props = Thing._data_int_props + ('num_comments', 'reported')
    _defaults = dict(is_self = False,
                     reported = 0, num_comments = 0,
                     moderator_banned = False,
                     banned_before_moderator = False,
                     ip = '0.0.0.0')

    def __init__(self, *a, **kw):
        Thing.__init__(self, *a, **kw)

    @classmethod
    @memoize('link._by_url')
    def _by_url_cache(cls, url, sr):
        q = cls._query(base_url(lower(cls.c.url)) == utils.base_url(url.lower()))
        if sr:
            q._filter(cls.c.sr_id == sr._id)
        q = list(q)
        return [l._id for l in q]

    #TODO get the subreddit?
    @classmethod
    def _by_url(cls, url, sr = None):
        from subreddit import Default
        #force sr to be None for caching purposes
        if sr in (False, Default):
            sr = None

        lid = cls._by_url_cache(url, sr)
        if lid and sr:
            return cls._byID(lid[0], True)
        elif lid:
            return cls._byID(lid, True, return_dict = False)
        else:
            raise NotFound, 'Link "%s"' % url

    @property
    def already_submitted_link(self):
        return self.permalink + '?already_submitted=true'

    def resubmit_link(self, sr_url = False):
        submit_url  = self.subreddit_slow.path if sr_url else '/'
        submit_url += 'submit?resubmit=true&url=' + url_escape(self.url)
        return submit_url

    @classmethod
    def _submit(cls, title, url, author, sr, ip, spam = False):
        from admintools import admintools
        if url != u'self':
            try:
                l = Link._by_url(url, sr)
                raise LinkExists
            except NotFound:
                pass

        l = cls(title = title,
                url = url,
                _spam = spam,
                author_id = author._id,
                sr_id = sr._id, 
                lang = sr.lang,
                ip = ip)
        l._commit()

        clear_memo('link._by_url', Link, url, sr)
        # clear cache for lookups without sr
        clear_memo('link._by_url', Link, url, None)

        utils.worker.do(lambda: admintools.add_thing(l))

        return l

    @classmethod
    def _somethinged(cls, rel, user, link, name):
        return rel._fast_query(tup(user), tup(link), name = name)

    def _something(self, rel, user, somethinged, name):
        saved = somethinged(user, self)[(user, self, name)]
        if not saved:
            saved = rel(user, self, name=name)
            saved._commit()
        return saved

    def _unsomething(self, user, somethinged, name):
        saved = somethinged(user, self)[(user, self, name)]
        if saved:
            saved._delete()

    @classmethod
    def _saved(cls, user, link):
        return cls._somethinged(SaveHide, user, link, 'save')

    def _save(self, user):
        return self._something(SaveHide, user, self._saved, 'save')

    def _unsave(self, user):
        return self._unsomething(user, self._saved, 'save')

    @classmethod
    def _clicked(cls, user, link):
        return cls._somethinged(Click, user, link, 'click')

    def _click(self, user):
        return self._something(Click, user, self._clicked, 'click')

    @classmethod
    def _hidden(cls, user, link):
        return cls._somethinged(SaveHide, user, link, 'hide')

    def _hide(self, user):
        return self._something(SaveHide, user, self._hidden, 'hide')

    def _unhide(self, user):
        return self._unsomething(user, self._hidden, 'hide')

    def keep_item(self, wrapped):
        user = c.user if c.user_is_loggedin else None

        if not c.user_is_admin:
            if self._spam and (not user or
                               (user and self.author_id != user._id)):
                return False
        
            #author_karma = wrapped.author.link_karma
            #if author_karma <= 0 and random.randint(author_karma, 0) != 0:
                #return False

        if user:
            if user.pref_hide_ups and wrapped.likes == True:
                return False
        
            if user.pref_hide_downs and wrapped.likes == False:
                return False

            if wrapped._score < user.pref_min_link_score:
                return False

            if wrapped.hidden:
                return False

        return True

    def cache_key(self, wrapped):
        if c.user_is_admin:
            return False

        s = (str(i) for i in (self._fullname,
                              bool(c.user_is_loggedin),
                              wrapped.subreddit == c.site,
                              c.user.pref_newwindow,
                              c.user.pref_frame,
                              c.user.pref_compress,
                              request.host,
                              wrapped.author == c.user,
                              wrapped.likes,
                              wrapped.saved,
                              wrapped.clicked,
                              wrapped.hidden,
                              wrapped.friend,
                              wrapped.show_spam,
                              wrapped.show_reports,
                              wrapped.can_ban,
                              wrapped.moderator_banned))
        s = ''.join(s)
        return s

#     @property
#     def permalink(self):
#         return "%s/info/%s/comments/" % (self.sr.path, self._id36)

    @property
    def permalink(self):
        return "/info/%s/comments/" % self._id36

    @classmethod
    def add_props(cls, user, wrapped):
        from r2.lib.count import incr_counts
        saved = Link._saved(user, wrapped) if user else {}
        hidden = Link._hidden(user, wrapped) if user else {}
        #clicked = Link._clicked(user, wrapped) if user else {}
        clicked = {}

        for item in wrapped:

            item.score = max(0, item.score)

            item.domain = (domain(item.url) if not item.is_self
                          else 'self.' + item.subreddit.name)
            item.top_link = False
            item.urlprefix = ''
            item.saved = bool(saved.get((user, item, 'save')))
            item.hidden = bool(hidden.get((user, item, 'hide')))
            item.clicked = bool(clicked.get((user, item, 'click')))
            item.num = None
            item.score_fmt = Score.number_only
                
        if c.user_is_loggedin:
            incr_counts(wrapped)

    @property
    def subreddit_slow(self):
        from subreddit import Subreddit
        """return's a link's subreddit. in most case the subreddit is already
        on the wrapped link (as .subreddit), and that should be used
        when possible. """
        return Subreddit._byID(self.sr_id, True, return_dict = False)

class LinkCompressed(Link):
    _nodb = True

class Comment(Thing, Printable):
    _data_int_props = Thing._data_int_props + ('reported',)
    _defaults = dict(reported = 0, 
                     moderator_banned = False,
                     banned_before_moderator = False)

    def _markdown(self):
        pass

    def _delete(self):
        link = Link._byID(self.link_id, data = True)
        link._incr('num_comments', -1)
    
    @classmethod
    def _new(cls, author, link, parent, body, ip, spam = False):
        c = Comment(body = body,
                    link_id = link._id,
                    sr_id = link.sr_id,
                    author_id = author._id,
                    ip = ip)

        c._spam = spam

        #these props aren't relations
        if parent:
            c.parent_id = parent._id

        c._commit()

        link._incr('num_comments', 1)

        if parent:
            to = Account._byID(parent.author_id)
            i = Inbox._add(to, c, 'inbox')

        #clear that chache
        clear_memo('builder.link_comments2', link._id)
        from admintools import admintools
        utils.worker.do(lambda: admintools.add_thing(c))

        return c

    @property
    def subreddit_slow(self):
        from subreddit import Subreddit
        """return's a comments's subreddit. in most case the subreddit is already
        on the wrapped link (as .subreddit), and that should be used
        when possible. if sr_id does not exist, then use the parent link's"""
        self._safe_load()

        if hasattr(self, 'sr_id'):
            sr_id = self.sr_id
        else:
            l = Link._byID(self.link_id, True)
            sr_id = l.sr_id
        return Subreddit._byID(sr_id, True, return_dict = False)

    def keep_item(self, wrapped):
        return True

    def cache_key(self, wrapped):
        if c.user_is_admin:
            return False

        s = (str(i) for i in (c.profilepage,
                              self._fullname,
                              bool(c.user_is_loggedin),
                              c.focal_comment == self._id36,
                              request.host,
                              wrapped.author == c.user,
                              wrapped.likes,
                              wrapped.friend,
                              wrapped.collapsed,
                              wrapped.moderator_banned,
                              wrapped.show_spam,
                              wrapped.show_reports,
                              wrapped.can_ban,
                              wrapped.moderator_banned,
                              wrapped.can_reply,
                              wrapped.deleted))
        s = ''.join(s)
        return s

    @property
    def permalink(self):
        if not self._loaded:
            self._load()

        try:
            l = Link._byID(self.link_id, True)
            return l.permalink + self._id36
        except NotFound:
            return ""


    @classmethod
    def add_props(cls, user, wrapped):
        #fetch parent links
        links = Link._byID(set(l.link_id for l in wrapped), True)

        #get srs for comments that don't have them (old comments)
        for cm in wrapped:
            if not hasattr(cm, 'sr_id'):
                cm.sr_id = links[cm.link_id].sr_id
        
        subreddits = Subreddit._byID(set(cm.sr_id for cm in wrapped),
                                     data=True,return_dict=False)
        can_reply_srs = set(s._id for s in subreddits if s.can_comment(user))

        min_score = c.user.pref_min_comment_score

        cids = dict((w._id, w) for w in wrapped)

        for item in wrapped:
            if hasattr(item, 'parent_id'):
                if cids.has_key(item.parent_id):
                    item.parent_permalink = '#' + utils.to36(item.parent_id)
                else:
                    parent = Comment._byID(item.parent_id)
                    item.parent_permalink = parent.permalink
            else:
                item.parent_permalink = None

            item.can_reply = (item.sr_id in can_reply_srs)

            if not hasattr(item, 'subreddit'):
                item.subreddit = item.subreddit_slow

            # not deleted on profile pages,
            # deleted if spam and not author or admin
            item.deleted = (not c.profilepage and
                           (item._deleted or
                            (item._spam and
                             item.author != c.user and
                             not item.show_spam)))

            # don't collapse for admins, on profile pages, or if deleted
            item.collapsed = ((item.score < min_score) and
                             not (c.profilepage or
                                  item.deleted or
                                  c.user_is_admin))
                
            item.link = links.get(item.link_id)
            item.editted = False
            #will get updated in builder
            item.num_children = 0
            item.score_fmt = Score.points

class MoreComments(object):
    show_spam = False
    show_reports = False
    is_special = False
    can_ban = False
    deleted = False
    rowstyle = 'even'
    reported = False
    collapsed = False
    author = None
    margin = 0

    def cache_key(self, item):
        return False
    
    def __init__(self, link, depth, parent=None):
        if parent:
            self.parent_id = parent._id
            self.parent_name = parent._fullname
            self.parent_permalink = parent.permalink
        self.link_name = link._fullname
        self.link_id = link._id
        self.depth = depth
        self.children = []
        self.count = 0

    @property
    def _fullname(self):
        return self.children[0]._fullname if self.children else 't0_blah'

    @property
    def _id36(self):
        return self.children[0]._id36 if self.children else 't0_blah'


class MoreRecursion(MoreComments):
    pass

class MoreChildren(MoreComments):
    pass
    
class Message(Thing, Printable):
    _defaults = dict(reported = 0,)
    _data_int_props = Thing._data_int_props + ('reported', )

    @classmethod
    def _new(cls, author, to, subject, body, ip, spam = False):
        m = Message(subject = subject,
                    body = body,
                    author_id = author._id,
                    ip = ip)
        m._spam = spam
        m.to_id = to._id
        m._commit()

        #author = Author(author, m, 'author')
        #author._commit()

        i = Inbox._add(to, m, 'inbox')

        from admintools import admintools
        utils.worker.do(lambda: admintools.add_thing(m))

        return m

    @classmethod
    def add_props(cls, user, wrapped):
        #TODO global-ish functions that shouldn't be here?
        #reset msgtime after this request
        msgtime = c.have_messages
        
        #load the "to" field if required
        to_ids = set(w.to_id for w in wrapped)
        tos = Account._byID(to_ids, True) if to_ids else {}

        for item in wrapped:
            item.to = tos[item.to_id]
            if msgtime and item._date >= msgtime:
                item.new = True
            else:
                item.new = False
            item.score_fmt = Score.none
               
 
    def cache_key(self, wrapped):
        #warning: inbox/sent messages
        #comments as messages
        return False

    def keep_item(self, wrapped):
        return True

class SaveHide(Relation(Account, Link)): pass
class Click(Relation(Account, Link)): pass

class Inbox(MultiRelation('inbox',
                          Relation(Account, Comment),
                          Relation(Account, Message))):
    @classmethod
    def _add(cls, to, obj, *a, **kw):
        i = Inbox(to, obj, *a, **kw)
        i._commit()

        if not to._loaded:
            to._load()
            
        #if there is not msgtime, or it's false, set it
        if not hasattr(to, 'msgtime') or not to.msgtime:
            to.msgtime = obj._date
            to._commit()
            
        return i
