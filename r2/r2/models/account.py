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
from r2.lib.db.thing     import Thing, Relation, NotFound
from r2.lib.db.operators import lower
from r2.lib.db.userrel   import UserRel
from r2.lib.memoize      import memoize, clear_memo
from r2.lib.utils        import modhash, valid_hash, randstr 

from pylons import g
import time, sha
from copy import copy

class AccountExists(Exception): pass

class Account(Thing):
    _data_int_props = Thing._data_int_props + ('link_karma', 'comment_karma',
                                               'report_made', 'report_correct',
                                               'report_ignored', 'spammer',
                                               'reported')
    _int_prop_suffix = '_karma'
    _defaults = dict(pref_numsites = 25,
                     pref_frame = False,
                     pref_newwindow = False,
                     pref_public_votes = False,
                     pref_hide_ups = False,
                     pref_hide_downs = True,
                     pref_min_link_score = -4,
                     pref_min_comment_score = -4,
                     pref_num_comments = g.num_comments,
                     pref_lang = 'en',
                     pref_content_langs = ('en',),
                     pref_over_18 = False,
                     pref_compress = False,
                     pref_organic = True,
                     reported = 0,
                     report_made = 0,
                     report_correct = 0,
                     report_ignored = 0,
                     spammer = 0,
                     sort_options = {},
                     has_subscribed = False
                     )
    
    def karma(self, kind, sr = None):
        suffix = '_' + kind + '_karma'
        
        #if no sr, return the sum
        if sr is None:
            total = 0
            for k, v in self._t.iteritems():
                if k.endswith(suffix):
                    total += v
            return total
        else:
            try:
                return getattr(self, sr.name + suffix)
            except AttributeError:
                #if positive karma elsewhere, you get min_up_karma
                if self.karma(kind) > 0:
                    return g.MIN_UP_KARMA
                else:
                    return 0

    def incr_karma(self, kind, sr, amt):
        prop = '%s_%s_karma' % (sr.name, kind)
        if hasattr(self, prop):
            return self._incr(prop, amt)
        else:
            default_val = self.karma(kind, sr)
            setattr(self, prop, default_val + amt)
            self._commit()

    @property
    def link_karma(self):
        return self.karma('link')

    @property
    def comment_karma(self):
        return self.karma('comment')

    @property
    def safe_karma(self):
        karma = self.link_karma
        return max(karma, 1) if karma > -1000 else karma

    def all_karmas(self):
        """returns a list of tuples in the form (name, link_karma,
        comment_karma)"""
        link_suffix = '_link_karma'
        comment_suffix = '_comment_karma'
        karmas = []
        sr_names = set()
        for k in self._t.keys():
            if k.endswith(link_suffix):
                sr_names.add(k[:-len(link_suffix)])
            elif k.endswith(comment_suffix):
                sr_names.add(k[:-len(comment_suffix)])
        for sr_name in sr_names:
            karmas.append((sr_name,
                           self._t.get(sr_name + link_suffix, 0),
                           self._t.get(sr_name + comment_suffix, 0)))
        karmas.sort(key = lambda x: x[1] + x[2])

        karmas.insert(0, ('total',
                          self.karma('link'),
                          self.karma('comment')))

        karmas.append(('old',
                       self._t.get('link_karma', 0),
                       self._t.get('comment_karma', 0)))

        return karmas
        
    def make_cookie(self, timestr = None, admin = False):
        if not self._loaded:
            self._load()
        timestr = timestr or time.strftime('%Y-%m-%dT%H:%M:%S')
        id_time = str(self._id) + ',' + timestr
        to_hash = ','.join((id_time, self.password, g.SECRET))
        if admin:
            to_hash += 'admin'
        return id_time + ',' + sha.new(to_hash).hexdigest()

    def needs_captcha(self):
        return self.link_karma < 1

    def modhash(self, rand=None, test=False):
        return modhash(self, rand = rand, test = test)
    
    def valid_hash(self, hash):
        return valid_hash(self, hash)

    @classmethod
    @memoize('account._by_name')
    def _by_name_cache(cls, name, allow_deleted = False):
        #relower name here, just in case
        deleted = (True, False) if allow_deleted else False
        q = cls._query(lower(Account.c.name) == name.lower(),
                       Account.c._spam == (True, False),
                       Account.c._deleted == deleted)

        q._limit = 1
        l = list(q)
        if l:
            return l[0]._id

    @classmethod
    def _by_name(cls, name, allow_deleted = False):
        #lower name here so there is only one cache
        uid = cls._by_name_cache(name.lower(), allow_deleted)
        if uid:
            return cls._byID(uid, True)
        else:
            raise NotFound, 'Account %s' % name

    @property
    def friends(self):
        return self.friend_ids()

    def delete(self):
        self._deleted = True
        self._commit()
        clear_memo('account._by_name', Account, self.name.lower(), False)
        
        #remove from friends lists
        q = Friend._query(Friend.c._thing2_id == self._id,
                          Friend.c._name == 'friend',
                          eager_load = True)
        for f in q:
            f._thing1.remove_friend(f._thing2)

    @property
    def subreddits(self):
        from subreddit import Subreddit
        return Subreddit.user_subreddits(self)


class FakeAccount(Account):
    _nodb = True


def valid_cookie(cookie):
    try:
        uid, timestr, hash = cookie.split(',')
        uid = int(uid)
    except:
        return (False, False)

    try:
        account = Account._byID(uid, True)
        if account._deleted:
            return (False, False)
    except NotFound:
        return (False, False)

    if cookie == account.make_cookie(timestr, admin = False):
        return (account, False)
    elif cookie == account.make_cookie(timestr, admin = True):
        return (account, True)
    return (False, False)

def valid_login(name, password):
    try:
        a = Account._by_name(name)
    except NotFound:
        return False

    if not a._loaded: a._load()
    return valid_password(a, password)

def valid_password(a, password):
    try:
        if a.password == passhash(a.name, password, ''):
            #add a salt
            a.password = passhash(a.name, password, True)
            a._commit()
            return a
        else:
            salt = a.password[:3]
            if a.password == passhash(a.name, password, salt):
                return a
    except AttributeError:
        return False

def passhash(username, password, salt = ''):
    if salt is True:
        salt = randstr(3)
    tohash = '%s%s %s' % (salt, username, password)
    return salt + sha.new(tohash).hexdigest()

def change_password(user, newpassword):
    user.password = passhash(user.name, newpassword, True)
    user._commit()
    return True

#TODO reset the cache
def register(name, password):
    try:
        a = Account._by_name(name)
        raise AccountExists
    except NotFound:
        a = Account(name = name,
                    password = passhash(name, password, True))

        a._commit()
        clear_memo('account._by_name', Account, name.lower(), False)
        return a

class Friend(Relation(Account, Account)): pass
Account.__bases__ += (UserRel('friend', Friend),)
