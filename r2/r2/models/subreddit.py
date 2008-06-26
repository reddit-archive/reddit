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
from pylons import c, g
from pylons.i18n import _

from r2.lib.db.thing import Thing, Relation, NotFound
from account import Account
from printable import Printable
from r2.lib.db.userrel import UserRel
from r2.lib.db.operators import lower, or_, and_, desc
from r2.lib.memoize import memoize, clear_memo
from r2.lib.utils import tup
from r2.lib.strings import strings, Score
import os.path

class Subreddit(Thing, Printable):
    _defaults = dict(static_path = g.static_path,
                     stylesheet = None,
                     stylesheet_rtl = None,
                     description = None,
                     firsttext = strings.firsttext,
                     header = os.path.join(g.static_path,
                                           'base.reddit.com.header.png'),
                     ad_file = os.path.join(g.static_path, 'ad_default.html'),
                     reported = 0,
                     valid_votes = 0,
                     )

    @classmethod
    def _new(self, name, title, lang = 'en', type = 'public',
             over_18 = False, **kw):
        try:
            sr = Subreddit._by_name(name)
            raise SubredditExists
        except NotFound:
            sr = Subreddit(name = name,
                           title = title,
                           lang = lang,
                           type = type,
                           over_18 = over_18,
                           **kw)
            sr._commit()
            clear_memo('subreddit._by_name', Subreddit, name.lower())
            clear_memo('subreddit.subreddits', Subreddit)
            return sr

    @classmethod
    @memoize('subreddit._by_name')
    def _by_name_cache(cls, name):
        q = cls._query(lower(cls.c.name) == name.lower(),
                       cls.c._spam == (True, False),
                       limit = 1)
        l = list(q)
        if l:
            return l[0]._id

    @classmethod
    def _by_name(cls, name):
        #lower name here so there is only one cache
        name = name.lower()

        if name == 'friends':
            return Friends
        elif name == 'all':
            return All
        else:
            sr_id = cls._by_name_cache(name)
            if sr_id:
                return cls._byID(sr_id, True)
            else:
                raise NotFound, 'Subreddit %s' % name

    @property
    def moderators(self):
        return self.moderator_ids()

    @property
    def contributors(self):
        return self.contributor_ids()

    @property
    def banned(self):
        return self.banned_ids()

    @property
    def subscribers(self):
        return self.subscriber_ids()

    def can_comment(self, user):
        if c.user_is_admin:
            return True
        elif self.is_banned(user):
            return False
        elif self.type in ('public','restricted'):
            return True
        elif self.is_moderator(user) or self.is_contributor(user):
            #private requires contributorship
            return True
        else:
            return False

    def can_submit(self, user):
        if c.user_is_admin:
            return True
        elif self.is_banned(user):
            return False
        elif self.type == 'public':
            return True
        elif self.is_moderator(user) or self.is_contributor(user):
            #restricted/private require contributorship
            return True
        else:
            return False

    def can_ban(self,user):
        return (user
                and (c.user_is_admin
                     or self.is_moderator(user)))

    def is_special(self, user):
        return (user
                and (c.user_is_admin
                     or self.is_moderator(user)
                     or (self.type in ('restricted', 'private')
                         and self.is_contributor(user))))

    def can_give_karma(self, user):
        return self.is_special(user)

    def should_ratelimit(self, user, kind):
        if c.user_is_admin:
            return False

        if kind == 'comment':
            rl_karma = g.MIN_RATE_LIMIT_COMMENT_KARMA
        else:
            rl_karma = g.MIN_RATE_LIMIT_KARMA
            
        return not (self.is_special(user) or 
                    user.karma(kind, self) >= rl_karma)

    def can_view(self, user):
        if c.user_is_admin:
            return True

        if self.type in ('public', 'restricted'):
            return True
        elif c.user_is_loggedin:
            #private requires contributorship
            return self.is_contributor(user) or self.is_moderator(user)

    @classmethod
    def load_subreddits(cls, links, return_dict = True):
        """returns the subreddits for a list of links. it also preloads the
        permissions for the current user."""
        srids = set(l.sr_id for l in links if hasattr(l, "sr_id"))
        subreddits = {}
        if srids:
            subreddits = cls._byID(srids, True)

        if subreddits and c.user_is_loggedin:
            # dict( {Subreddit,Account,name} -> Relationship )
            SRMember._fast_query(subreddits.values(), (c.user,),
                                 ('subscriber','contributor','moderator'))

        return subreddits if return_dict else subreddits.values()

    #rising uses this to know which subreddits to include, doesn't
    #work for all/friends atm
    def rising_srs(self):
        if c.default_sr or not hasattr(self, '_id'):
            user = c.user if c.user_is_loggedin else None
            sr_ids = self.user_subreddits(user)
        else:
            sr_ids = (self._id,)
        return sr_ids

    def query_rules(self):
        #really we mean Link.c.sr_id, but rules are type agnostic
        return (self.c.sr_id == self._id,)

    @classmethod
    def add_props(cls, user, wrapped):
        names = ('subscriber', 'moderator', 'contributor')
        rels = (SRMember._fast_query(wrapped, [user], names) if user else {})
        defaults = Subreddit.default_srs(c.content_langs, ids = True)
        for item in wrapped:
            if user and not user.has_subscribed:
                item.subscriber = item._id in defaults
            else:
                item.subscriber = rels.get((item, user, 'subscriber'))
            item.moderator = rels.get((item, user, 'moderator'))
            item.contributor = item.moderator or \
                rels.get((item, user, 'contributor'))
            item.score = item._ups
            item.score_fmt = Score.subscribers

    #TODO: make this work
    def cache_key(self, wrapped):
        if c.user_is_admin:
            return False

        s = (str(i) for i in (self._fullname,
                              bool(c.user_is_loggedin),
                              wrapped.subscriber,
                              wrapped.moderator,
                              wrapped.contributor,
                              wrapped._spam))
        s = ''.join(s)
        return s

    #TODO: make this work
    #@property
    #def author_id(self):
        #return 1

    @classmethod
    def default_srs(cls, lang, ids = False, limit = 10):
        """Returns the default list of subreddits for a given language, sorted
        by popularity"""
        pop_reddits = Subreddit._query(Subreddit.c.type == ('public', 'restricted'),
                                       sort=desc('_downs'),
                                       limit = limit,
                                       data = True,
                                       read_cache = True,
                                       write_cache = True,
                                       cache_time = g.page_cache_time)
        if lang != 'all':
            pop_reddits._filter(Subreddit.c.lang == lang)

        if not c.over18:
            pop_reddits._filter(Subreddit.c.over_18 == False)

        pop_reddits = list(pop_reddits)

        if not pop_reddits and lang != 'en':
            pop_reddits = cls.default_srs('en')
            
        return [s._id for s in pop_reddits] if ids else list(pop_reddits)

    @classmethod
    def user_subreddits(cls, user):
        """subreddits that appear in a user's listings. returns the default
        srs if there are no subscriptions."""
        if user and user.has_subscribed:
            return Subreddit.reverse_subscriber_ids(user)
        else:
            return cls.default_srs(c.content_langs, ids = True)

    def is_subscriber_defaults(self, user):
        if user.has_subscribed:
            return self.is_subscriber(user)
        else:
            return self in self.default_srs(c.content_langs)

    @classmethod
    def subscribe_defaults(cls, user):
        if not user.has_subscribed:
            for sr in Subreddit.default_srs(c.content_langs):
                if sr.add_subscriber(c.user):
                    sr._incr('_ups', 1)
            user.has_subscribed = True
            user._commit()

    @classmethod
    def submit_sr_names(cls, user):
        """subreddit names that appear in a user's submit page. basically a
        sorted/rearranged version of user_subreddits()."""
        sub_ids = cls.user_subreddits(user)
        srs = Subreddit._byID(sub_ids, True,
                              return_dict = False)
        names = [s.name for s in srs if s.can_submit(user)]
        names.sort()

        #add the current site to the top (default_sr)
        if g.default_sr in names:
            names.remove(g.default_sr)
            names.insert(0, g.default_sr)

        if c.lang in names:
            names.remove(c.lang)
            names.insert(0, c.lang)

        return names

    @property
    def path(self):
        return "/r/%s/" % self.name


    def keep_item(self, wrapped):
        if c.user_is_admin:
            return True

        user = c.user if c.user_is_loggedin else None
        return self.can_view(user)

class FakeSubreddit(Subreddit):
    over_18 = False
    title = ''
    _nodb = True

    def is_moderator(self, user):
        return c.user_is_loggedin and c.user_is_admin

    def can_view(self, user):
        return True

    def can_comment(self, user):
        return False

    def can_submit(self, user):
        return False

    def is_banned(self, user):
        return False

class FriendsSR(FakeSubreddit):
    name = 'friends'
    title = 'friends'

    def query_rules(self):
        if c.user_is_loggedin:
            return (self.c.author_id == c.user.friends,)
        else:
            return (self.c.sr_id == self.default_srs(c.content_langs, ids = True),)

class AllSR(FakeSubreddit):
    name = 'all'
    title = 'all'

    def query_rules(self):
        if c.content_langs != 'all':
            return (self.c.lang == c.content_langs,)
        else:
            return ()

class DefaultSR(FakeSubreddit):
    #notice the space before reddit.com
    name = ' reddit.com'
    path = '/'
    header = 'http://static.reddit.com/reddit.com.header.png'

    def query_rules(self):
        user = c.user if c.user_is_loggedin else None
        subreddits = Subreddit.user_subreddits(user)
        return (self.c.sr_id == subreddits,)

    @property
    def title(self):
        return _("reddit.com: what's new online!")

#TODO: I'm not sure this is the best way to do this
class MaskedSR(DefaultSR):
    def set_mask(self, mask):
        self.show_sr = []
        self.hide_sr = []
        for k, v in mask.iteritems():
            if v:
                self.show_sr.append(k)
            else:
                self.hide_sr.append(k)
        self.show_sr = Subreddit._by_fullname(self.show_sr, 
                                              return_dict = False)
        self.show_sr = [s._id for s in self.show_sr]
        self.hide_sr = Subreddit._by_fullname(self.hide_sr, 
                                              return_dict = False)
        self.hide_sr = [s._id for s in self.hide_sr]
        
    def query_rules(self):
        user = c.user if c.user_is_loggedin else None
        subreddits = Subreddit.user_subreddits(user)
        subreddits = [s for s in subreddits if s not in self.hide_sr]
        subreddits.extend(self.show_sr)
        return (self.c.sr_id == subreddits,)


class SubSR(FakeSubreddit):
    stylesheet = 'subreddit.css'
    #this will make the javascript not send an SR parameter
    name = ''

    def can_view(self, user):
        return True

    def can_comment(self, user):
        return False

    def can_submit(self, user):
        return True

    @property
    def path(self):
        return "/reddits/"
        
Sub = SubSR()
Friends = FriendsSR()
All = AllSR()
Default = DefaultSR()

class SRMember(Relation(Subreddit, Account)): pass
Subreddit.__bases__ += (UserRel('moderator', SRMember),
                        UserRel('contributor', SRMember),
                        UserRel('subscriber', SRMember),
                        UserRel('banned', SRMember))
