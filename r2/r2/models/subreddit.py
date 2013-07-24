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

from __future__ import with_statement

import base64
import collections
import datetime
import hashlib
import itertools
import json

from pylons import c, g
from pylons.i18n import _

from r2.lib.db.thing import Thing, Relation, NotFound
from account import Account, AccountsActiveBySR
from printable import Printable
from r2.lib.db.userrel import UserRel
from r2.lib.db.operators import lower, or_, and_, desc
from r2.lib.errors import UserRequiredException
from r2.lib.memoize import memoize
from r2.lib.permissions import ModeratorPermissionSet
from r2.lib.utils import tup, interleave_lists, last_modified_multi, flatten
from r2.lib.utils import timeago, summarize_markdown
from r2.lib.cache import sgm
from r2.lib.strings import strings, Score
from r2.lib.filters import _force_unicode
from r2.lib.db import tdb_cassandra
from r2.models.wiki import WikiPage
from r2.lib.merge import ConflictException
from r2.lib.cache import CL_ONE
from r2.lib.contrib.rcssmin import cssmin
from r2.lib import s3cp
from r2.models.query_cache import MergedCachedQuery
import pycassa

import math

from r2.lib.utils import set_last_modified
from r2.models.wiki import WikiPage
import os.path
import random


def get_links_sr_ids(sr_ids, sort, time):
    from r2.lib.db import queries

    if not sr_ids:
        return []
    else:
        srs = Subreddit._byID(sr_ids, data=True, return_dict = False)

    results = [queries.get_links(sr, sort, time)
               for sr in srs]
    return queries.merge_results(*results)


class BaseSite(object):
    _defaults = dict(
        static_path=g.static_path,
        stylesheet=None,
        stylesheet_hash='',
        header=None,
        header_title='',
    )

    def __getattr__(self, name):
        if name in self._defaults:
            return self._defaults[name]
        raise AttributeError

    @property
    def path(self):
        return "/r/%s/" % self.name

    @property
    def user_path(self):
        return self.path

    @property
    def analytics_name(self):
        return self.name

    def is_moderator_with_perms(self, user, *perms):
        rel = self.is_moderator(user)
        if rel:
            return all(rel.has_permission(perm) for perm in perms)

    def is_limited_moderator(self, user):
        rel = self.is_moderator(user)
        return bool(rel and not rel.is_superuser())

    def is_unlimited_moderator(self, user):
        rel = self.is_moderator(user)
        return bool(rel and rel.is_superuser())

    def get_links(self, sort, time):
        from r2.lib.db import queries
        return queries.get_links(self, sort, time)

    def get_spam(self, include_links=True, include_comments=True):
        from r2.lib.db import queries
        return queries.get_spam(self, user=c.user, include_links=include_links,
                                include_comments=include_comments)

    def get_reported(self, include_links=True, include_comments=True):
        from r2.lib.db import queries
        return queries.get_reported(self, user=c.user,
                                    include_links=include_links,
                                    include_comments=include_comments)

    def get_modqueue(self, include_links=True, include_comments=True):
        from r2.lib.db import queries
        return queries.get_modqueue(self, user=c.user,
                                    include_links=include_links,
                                    include_comments=include_comments)

    def get_unmoderated(self):
        from r2.lib.db import queries
        return queries.get_unmoderated(self, user=c.user)

    def get_all_comments(self):
        from r2.lib.db import queries
        return queries.get_sr_comments(self)

    def get_gilded_comments(self):
        from r2.lib.db import queries
        return queries.get_gilded_comments(self)

    @classmethod
    def get_modactions(cls, srs, mod=None, action=None):
        # Get a query that will yield ModAction objects with mod and action
        from r2.models import ModAction
        return ModAction.get_actions(srs, mod=mod, action=action)

    @property
    def stylesheet_is_static(self):
        """Is the subreddit using the newer static file based stylesheets?"""
        return g.static_stylesheet_bucket and len(self.stylesheet_hash) == 27

    static_stylesheet_prefix = "subreddit-stylesheet/"

    @property
    def static_stylesheet_name(self):
        return "".join((self.static_stylesheet_prefix,
                        self.stylesheet_hash,
                        ".css"))

    @property
    def stylesheet_url(self):
        from r2.lib.template_helpers import static, get_domain

        if self.stylesheet_is_static:
            return static(self.static_stylesheet_name, kind='sr_stylesheet')
        else:
            return "http://%s/stylesheet.css?v=%s" % (get_domain(cname=False,
                                                                 subreddit=True),
                                                      self.stylesheet_hash)


class SubredditExists(Exception): pass


class Subreddit(Thing, Printable, BaseSite):
    # Note: As of 2010/03/18, nothing actually overrides the static_path
    # attribute, even on a cname. So c.site.static_path should always be
    # the same as g.static_path.
    _defaults = dict(BaseSite._defaults,
        stylesheet_rtl=None,
        stylesheet_contents='',
        stylesheet_modified=None,
        header_size=None,
        allow_top=False, # overridden in "_new"
        images={},
        reported=0,
        valid_votes=0,
        show_media=False,
        show_cname_sidebar=False,
        css_on_cname=True,
        domain=None,
        wikimode="disabled",
        wiki_edit_karma=100,
        wiki_edit_age=0,
        over_18=False,
        exclude_banned_modqueue=False,
        mod_actions=0,
        # do we allow self-posts, links only, or any?
        link_type='any', # one of ('link', 'self', 'any')
        submit_link_label='',
        submit_text_label='',
        comment_score_hide_mins=0,
        flair_enabled=True,
        flair_position='right', # one of ('left', 'right')
        link_flair_position='', # one of ('', 'left', 'right')
        flair_self_assign_enabled=False,
        link_flair_self_assign_enabled=False,
        use_quotas=True,
        description="",
        public_description="",
        prev_description_id="",
        prev_public_description_id="",
        allow_comment_gilding=True,
        hide_subscribers=False,
        public_traffic=False,
    )
    _essentials = ('type', 'name', 'lang')
    _data_int_props = Thing._data_int_props + ('mod_actions', 'reported',
                                               'wiki_edit_karma', 'wiki_edit_age')

    sr_limit = 50
    gold_limit = 100
    DEFAULT_LIMIT = object()

    MAX_SRNAME_LENGTH = 200 # must be less than max memcached key length

    # note: for purposely unrenderable reddits (like promos) set author_id = -1
    @classmethod
    def _new(cls, name, title, author_id, ip, lang = g.lang, type = 'public',
             over_18 = False, **kw):
        with g.make_lock("create_sr", 'create_sr_' + name.lower()):
            try:
                sr = Subreddit._by_name(name)
                raise SubredditExists
            except NotFound:
                if "allow_top" not in kw:
                    kw['allow_top'] = True
                sr = Subreddit(name = name,
                               title = title,
                               lang = lang,
                               type = type,
                               over_18 = over_18,
                               author_id = author_id,
                               ip = ip,
                               **kw)
                sr._commit()

                #clear cache
                Subreddit._by_name(name, _update = True)
                return sr


    _specials = {}

    @classmethod
    def _by_name(cls, names, stale=False, _update = False):
        '''
        Usages: 
        1. Subreddit._by_name('funny') # single sr name
        Searches for a single subreddit. Returns a single Subreddit object or 
        raises NotFound if the subreddit doesn't exist.
        2. Subreddit._by_name(['aww','iama']) # list of sr names
        Searches for a list of subreddits. Returns a dict mapping srnames to 
        Subreddit objects. Items that were not found are ommitted from the dict.
        If no items are found, an empty dict is returned.
        '''
        #lower name here so there is only one cache
        names, single = tup(names, True)

        to_fetch = {}
        ret = {}

        for name in names:
            ascii_only = str(name.decode("ascii", errors="ignore"))
            lname = ascii_only.lower()

            if lname in cls._specials:
                ret[name] = cls._specials[lname]
            elif len(lname) > Subreddit.MAX_SRNAME_LENGTH:
                g.log.debug("Subreddit._by_name() ignoring invalid srname (too long): %s", lname)
            else:
                to_fetch[lname] = name

        if to_fetch:
            def _fetch(lnames):
                q = cls._query(lower(cls.c.name) == lnames,
                               cls.c._spam == (True, False),
                               limit = len(lnames),
                               data=True)
                try:
                    srs = list(q)
                except UnicodeEncodeError:
                    print "Error looking up SRs %r" % (lnames,)
                    raise

                return dict((sr.name.lower(), sr._id)
                            for sr in srs)

            srs = {}
            srids = sgm(g.cache, to_fetch.keys(), _fetch, prefix='subreddit.byname', stale=stale)
            if srids:
                srs = cls._byID(srids.values(), data=True, return_dict=False, stale=stale)

            for sr in srs:
                ret[to_fetch[sr.name.lower()]] = sr

        if ret and single:
            return ret.values()[0]
        elif not ret and single:
            raise NotFound, 'Subreddit %s' % name
        else:
            return ret

    @classmethod
    @memoize('subreddit._by_domain')
    def _by_domain_cache(cls, name):
        q = cls._query(cls.c.domain == name,
                       limit = 1)
        l = list(q)
        if l:
            return l[0]._id

    @classmethod
    def _by_domain(cls, domain, _update = False):
        sr_id = cls._by_domain_cache(_force_unicode(domain).lower(),
                                     _update = _update)
        if sr_id:
            return cls._byID(sr_id, True)
        else:
            return None

    @property
    def moderators(self):
        return self.moderator_ids()

    def moderators_with_perms(self):
        return collections.OrderedDict(
            (r._thing2_id, r.get_permissions())
            for r in self.each_moderator())

    def moderator_invites_with_perms(self):
        return collections.OrderedDict(
            (r._thing2_id, r.get_permissions())
            for r in self.each_moderator_invite())

    @property
    def stylesheet_contents_user(self):
        try:
            return WikiPage.get(self, 'config/stylesheet')._get('content','')
        except tdb_cassandra.NotFound:
           return  self._t.get('stylesheet_contents_user')

    @property
    def prev_stylesheet(self):
        try:
            return WikiPage.get(self, 'config/stylesheet')._get('revision','')
        except tdb_cassandra.NotFound:
            return ''

    @property
    def contributors(self):
        return self.contributor_ids()

    @property
    def banned(self):
        return self.banned_ids()
    
    @property
    def wikibanned(self):
        return self.wikibanned_ids()
    
    @property
    def wikicontributor(self):
        return self.wikicontributor_ids()
    
    @property
    def _should_wiki(self):
        return True

    @property
    def subscribers(self):
        return self.subscriber_ids()

    @property
    def flair(self):
        return self.flair_ids()

    @property
    def accounts_active(self):
        return self.get_accounts_active()[0]

    @property
    def wiki_use_subreddit_karma(self):
        return True

    def get_accounts_active(self):
        fuzzed = False
        count = AccountsActiveBySR.get_count(self)
        key = 'get_accounts_active-' + self._id36

        # Fuzz counts having low values, for privacy reasons
        if count < 100 and not c.user_is_admin:
            fuzzed = True
            cached_count = g.cache.get(key)
            if not cached_count:
                # decay constant is e**(-x / 60)
                decay = math.exp(float(-count) / 60)
                jitter = round(5 * decay)
                count = count + random.randint(0, jitter)
                g.cache.set(key, count, time=5*60)
            else:
                count = cached_count
        return count, fuzzed

    def spammy(self):
        return self._spam

    def is_contributor(self, user):
        if self.name.lower() == g.lounge_reddit.lower():
            return user.gold or user.gold_charter
        else:
            return super(Subreddit, self).is_contributor(user)

    def can_comment(self, user):
        if c.user_is_admin:
            return True
        elif self.is_banned(user):
            return False
        elif self.type == 'gold_restricted' and user.gold:
            return True
        elif self.type in ('public','restricted'):
            return True
        elif self.is_moderator(user) or self.is_contributor(user):
            #private requires contributorship
            return True
        else:
            return False

    def wiki_can_submit(self, user):
        return self.can_submit(user)

    def can_submit(self, user, promotion=False):
        if c.user_is_admin:
            return True
        elif self.is_banned(user) and not promotion:
            return False
        elif self.spammy():
            return False
        elif self.type == 'public':
            return True
        elif self.is_moderator(user) or self.is_contributor(user):
            #restricted/private require contributorship
            return True
        elif self.type == 'gold_restricted' and user.gold:
            return True
        else:
            return False

    def can_ban(self, user):
        return (user
                and (c.user_is_admin
                     or self.is_moderator_with_perms(user, 'posts')))

    def can_distinguish(self,user):
        return (user
                and (c.user_is_admin
                     or self.is_moderator_with_perms(user, 'posts')))

    def can_change_stylesheet(self, user):
        if c.user_is_loggedin:
            return (
                c.user_is_admin or self.is_moderator_with_perms(user, 'config'))
        else:
            return False
    
    def parse_css(self, content, verify=True):
        from r2.lib import cssfilter
        if g.css_killswitch or (verify and not self.can_change_stylesheet(c.user)):
            return (None, None)
    
        parsed, report = cssfilter.validate_css(content)
        parsed = parsed.cssText if parsed else ''
        return (report, parsed)

    def change_css(self, content, parsed, prev=None, reason=None, author=None, force=False):
        from r2.models import ModAction
        author = author if author else c.user._id36
        if content is None:
            content = ''
        try:
            wiki = WikiPage.get(self, 'config/stylesheet')
        except tdb_cassandra.NotFound:
            wiki = WikiPage.create(self, 'config/stylesheet')
        wr = wiki.revise(content, previous=prev, author=author, reason=reason, force=force)

        minified = cssmin(parsed)
        if minified:
            if g.static_stylesheet_bucket:
                digest = hashlib.sha1(minified).digest()
                self.stylesheet_hash = (base64.urlsafe_b64encode(digest)
                                              .rstrip("="))

                s3cp.send_file(g.static_stylesheet_bucket,
                               self.static_stylesheet_name,
                               minified,
                               content_type="text/css",
                               never_expire=True,
                               replace=False,
                              )

                self.stylesheet_contents = ""
                self.stylesheet_modified = None
            else:
                self.stylesheet_hash = hashlib.md5(minified).hexdigest()
                self.stylesheet_contents = minified
                self.stylesheet_modified = datetime.datetime.now(g.tz)
        else:
            self.stylesheet_contents = ""
            self.stylesheet_hash = ""
            self.stylesheet_modified = datetime.datetime.now(g.tz)
        self.stylesheet_contents_user = ""  # reads from wiki; ensure pg clean
        self._commit()

        ModAction.create(self, c.user, action='wikirevise', details='Updated subreddit stylesheet')
        return wr

    def is_special(self, user):
        return (user
                and (c.user_is_admin
                     or self.is_moderator(user)
                     or self.is_contributor(user)))

    def can_give_karma(self, user):
        return self.is_special(user)

    def should_ratelimit(self, user, kind):
        if c.user_is_admin or self.is_special(user):
            return False

        if kind == 'comment':
            rl_karma = g.MIN_RATE_LIMIT_COMMENT_KARMA
        else:
            rl_karma = g.MIN_RATE_LIMIT_KARMA

        return user.karma(kind, self) < rl_karma

    def can_view(self, user):
        if c.user_is_admin:
            return True
        
        if self.spammy():
            return False
        elif self.type in ('public', 'restricted',
                           'gold_restricted', 'archived'):
            return True
        elif c.user_is_loggedin:
            return (self.is_contributor(user) or
                    self.is_moderator(user) or
                    self.is_moderator_invite(user))

    def can_demod(self, bully, victim):
        bully_rel = self.get_moderator(bully)
        if bully_rel is not None and bully == victim:
            # mods can always demod themselves
            return True
        victim_rel = self.get_moderator(victim)
        return (
            bully_rel is not None
            and victim_rel is not None
            and bully_rel.is_superuser()  # limited mods can't demod
            and bully_rel._date <= victim_rel._date)

    @classmethod
    def load_subreddits(cls, links, return_dict = True, stale=False):
        """returns the subreddits for a list of links. it also preloads the
        permissions for the current user."""
        srids = set(l.sr_id for l in links
                    if getattr(l, "sr_id", None) is not None)
        subreddits = {}
        if srids:
            subreddits = cls._byID(srids, data=True, stale=stale)

        if subreddits and c.user_is_loggedin:
            # dict( {Subreddit,Account,name} -> Relationship )
            SRMember._fast_query(subreddits.values(), (c.user,),
                                 ('subscriber','contributor','moderator'),
                                 data=True, eager_load=True, thing_data=True)

        return subreddits if return_dict else subreddits.values()

    def keep_for_rising(self, sr_id):
        """Return whether or not to keep a thing in rising for this SR."""
        return sr_id == self._id

    @classmethod
    def add_props(cls, user, wrapped):
        names = ('subscriber', 'moderator', 'contributor')
        rels = (SRMember._fast_query(wrapped, [user], names) if c.user_is_loggedin else {})
        defaults = Subreddit.default_subreddits()
        target = "_top" if c.cname else None
        for item in wrapped:
            if not user or not user.has_subscribed:
                item.subscriber = item._id in defaults
            else:
                item.subscriber = bool(rels.get((item, user, 'subscriber')))
            item.moderator = bool(rels.get((item, user, 'moderator')))
            item.contributor = bool(item.type != 'public' and
                                    (item.moderator or
                                     rels.get((item, user, 'contributor'))))

            if item.hide_subscribers and not c.user_is_admin:
                item._ups = 0

            item.score = item._ups

            # override "voting" score behavior (it will override the use of
            # item.score in builder.py to be ups-downs)
            item.likes = item.subscriber or None
            base_score = item.score - (1 if item.likes else 0)
            item.voting_score = [(base_score + x - 1) for x in range(3)]
            item.score_fmt = Score.subscribers

            #will seem less horrible when add_props is in pages.py
            from r2.lib.pages import UserText
            item.description_usertext = UserText(item, item.description, target=target)
            if item.public_description or item.description:
                text = (item.public_description or
                        summarize_markdown(item.description))
                item.public_description_usertext = UserText(item,
                                                            text,
                                                            target=target)
            else:
                item.public_description_usertext = None


        Printable.add_props(user, wrapped)
    #TODO: make this work
    cache_ignore = set(["subscribers"]).union(Printable.cache_ignore)
    @staticmethod
    def wrapped_cache_key(wrapped, style):
        s = Printable.wrapped_cache_key(wrapped, style)
        s.extend([wrapped._spam])
        return s

    @classmethod
    def top_lang_srs(cls, lang, limit, filter_allow_top = False, over18 = True,
                     over18_only = False, ids=False, stale=False):
        from r2.lib import sr_pops
        lang = tup(lang)

        sr_ids = sr_pops.pop_reddits(lang, over18, over18_only, filter_allow_top = filter_allow_top)
        sr_ids = sr_ids[:limit]

        return (sr_ids if ids
                else Subreddit._byID(sr_ids, data=True, return_dict=False, stale=stale))

    @classmethod
    def default_subreddits(cls, ids = True, over18 = False, limit = g.num_default_reddits,
                           stale=True):
        """
        Generates a list of the subreddits any user with the current
        set of language preferences and no subscriptions would see.

        An optional kw argument 'limit' is defaulted to g.num_default_reddits
        """

        # we'll let these be unordered for now
        auto_srs = []
        if g.automatic_reddits:
            auto_srs = map(lambda sr: sr._id,
                           Subreddit._by_name(g.automatic_reddits, stale=stale).values())

        srs = cls.top_lang_srs(c.content_langs, limit + len(auto_srs),
                               filter_allow_top = True,
                               over18 = over18, ids = True,
                               stale=stale)

        rv = []
        for sr in srs:
            if len(rv) >= limit:
                break
            if sr in auto_srs:
                continue
            rv.append(sr)

        rv = auto_srs + rv

        return rv if ids else Subreddit._byID(rv, data=True, return_dict=False, stale=stale)

    @classmethod
    @memoize('random_reddits', time = 1800)
    def random_reddits_cached(cls, user_name, sr_ids, limit):
        return random.sample(sr_ids, limit)

    @classmethod
    def random_reddits(cls, user_name, sr_ids, limit):
        """Select a random subset from sr_ids.

        Used for limiting the number of subscribed subreddits shown on a user's
        front page. Subreddits that are automatically subscribed aren't counted
        against the limit. Selection is cached for a while so the front page
        doesn't jump around.

        """

        if not limit:
            return sr_ids

        if g.automatic_reddits and len(sr_ids) > limit:
            automatics = Subreddit._by_name(g.automatic_reddits).values()
            automatic_ids = [sr._id for sr in automatics]
            for sr_id in automatic_ids:
                try:
                    sr_ids.remove(sr_id)
                except ValueError:
                    automatic_ids.remove(sr_id)
        else:
            automatic_ids = []

        if len(sr_ids) > limit:
            sr_ids = sorted(sr_ids)
            sr_ids = cls.random_reddits_cached(user_name, sr_ids, limit)

        return sr_ids + automatic_ids

    @classmethod
    def random_reddit(cls, limit=2500, over18=False, user=None):
        srs = cls.top_lang_srs(c.content_langs, limit,
                               filter_allow_top = False,
                               over18 = over18,
                               over18_only = over18,
                               ids=True)
        if user:
            excludes = cls.user_subreddits(user, over18=over18, limit=None)
            srs = list(set(srs) - set(excludes))
        return (Subreddit._byID(random.choice(srs))
                if srs else Subreddit._by_name(g.default_sr))

    @classmethod
    def random_subscription(cls, user):
        srs = Subreddit.reverse_subscriber_ids(user)
        return (Subreddit._byID(random.choice(srs))
                if srs else Subreddit._by_name(g.default_sr))

    @classmethod
    def user_subreddits(cls, user, ids=True, over18=False, limit=DEFAULT_LIMIT,
                        stale=False):
        """
        subreddits that appear in a user's listings. If the user has
        subscribed, returns the stored set of subscriptions.
        
        limit - if it's Subreddit.DEFAULT_LIMIT, limits to 50 subs
                (100 for gold users)
                if it's None, no limit is used
                if it's an integer, then that many subs will be returned

        Otherwise, return the default set.
        """
        # Limit the number of subs returned based on user status,
        # if no explicit limit was passed
        if limit is Subreddit.DEFAULT_LIMIT:
            if user and user.gold:
                # Goldies get extra subreddits
                limit = Subreddit.gold_limit
            else:
                limit = Subreddit.sr_limit
        
        # note: for user not logged in, the fake user account has
        # has_subscribed == False by default.
        if user and user.has_subscribed:
            sr_ids = Subreddit.reverse_subscriber_ids(user)
            sr_ids = cls.random_reddits(user.name, sr_ids, limit)

            return sr_ids if ids else Subreddit._byID(sr_ids,
                                                      data=True,
                                                      return_dict=False,
                                                      stale=stale)
        else:
            return cls.default_subreddits(ids = ids, over18=over18,
                                          limit=g.num_default_reddits,
                                          stale=stale)


    # Used to pull all of the SRs a given user moderates or is a contributor
    # to (which one is controlled by query_param)
    @classmethod
    def special_reddits(cls, user, query_param):
        lookup = getattr(cls, 'reverse_%s_ids' % query_param)
        return lookup(user)

    def is_subscriber_defaults(self, user):
        if user.has_subscribed:
            return self.is_subscriber(user)
        else:
            return self in self.default_subreddits(ids = False)

    @classmethod
    def subscribe_defaults(cls, user):
        if not user.has_subscribed:
            for sr in cls.user_subreddits(None, False,
                                          limit = g.num_default_reddits):
                #this will call reverse_subscriber_ids after every
                #addition. if it becomes a problem we should make an
                #add_multiple_subscriber fn
                if sr.add_subscriber(user):
                    sr._incr('_ups', 1)
            user.has_subscribed = True
            user._commit()

    def keep_item(self, wrapped):
        if c.user_is_admin:
            return True

        user = c.user if c.user_is_loggedin else None
        return self.can_view(user)

    def get_images(self):
        """
        Iterator over list of (name, url) pairs which have been
        uploaded for custom styling of this subreddit. 
        """
        for name, img in self.images.iteritems():
            if name != "/empties/":
                yield (name, img)
    
    def get_num_images(self):
        if '/empties/' in self.images:
            return len(self.images) - 1
        else:
            return len(self.images)
    
    def add_image(self, name, url, max_num = None):
        """
        Adds an image to the subreddit's image list.  The resulting
        number of the image is returned.  Note that image numbers are
        non-sequential insofar as unused numbers in an existing range
        will be populated before a number outside the range is
        returned.

        raises ValueError if the resulting number is >= max_num.

        The Subreddit will be _dirty if a new image has been added to
        its images list, and no _commit is called.
        """
        if max_num is not None and self.get_num_images() >= max_num:
            raise ValueError, "too many images"
        
        # copy and blank out the images list to flag as _dirty
        l = self.images
        self.images = None
        # update the dictionary and rewrite to images attr
        l[name] = url
        self.images = l

    def del_image(self, name):
        """
        Deletes an image from the images dictionary assuming an image
        of that name is in the current dictionary.

        The Subreddit will be _dirty if image has been removed from
        its images list, and no _commit is called.
        """
        if self.images.has_key(name):
            l = self.images
            self.images = None

            del l[name]
            self.images = l

    def __eq__(self, other):
        if type(self) != type(other):
            return False

        if isinstance(self, FakeSubreddit):
            return self is other

        return self._id == other._id

    def __ne__(self, other):
        return not self.__eq__(other)

    @staticmethod
    def get_all_mod_ids(srs):
        from r2.lib.db.thing import Merge
        srs = tup(srs)
        queries = [SRMember._query(SRMember.c._thing1_id == sr._id,
                                   SRMember.c._name == 'moderator') for sr in srs]
        merged = Merge(queries)
        # sr_ids = [sr._id for sr in srs]
        # query = SRMember._query(SRMember.c._thing1_id == sr_ids, ...)
        # is really slow
        return [rel._thing2_id for rel in list(merged)]

    def update_moderator_permissions(self, user, **kwargs):
        """Grants or denies permissions to this moderator.

        Does nothing if the given user is not a moderator. Args are named
        parameters with bool or None values (use None to all back to the default
        for a permission).
        """
        rel = self.get_moderator(user)
        if rel:
            rel.update_permissions(**kwargs)
            rel._commit()

    def add_rel_note(self, type, user, note):
        rel = getattr(self, "get_%s" % type)(user)
        if not rel:
            raise ValueError("User is not %s." % type)
        rel.note = note
        rel._commit()

class FakeSubreddit(BaseSite):
    _defaults = dict(Subreddit._defaults,
        link_flair_position='right',
    )

    def __init__(self):
        BaseSite.__init__(self)

    def keep_for_rising(self, sr_id):
        return False

    @property
    def _should_wiki(self):
        return False

    def is_moderator(self, user):
        if c.user_is_loggedin and c.user_is_admin:
            return FakeSRMember(ModeratorPermissionSet)

    def can_view(self, user):
        return True

    def can_comment(self, user):
        return False

    def can_submit(self, user, promotion=False):
        return False

    def can_change_stylesheet(self, user):
        return False

    def is_banned(self, user):
        return False

    def get_all_comments(self):
        from r2.lib.db import queries
        return queries.get_all_comments()

    def get_gilded_comments(self):
        raise NotImplementedError()

    def spammy(self):
        return False

class FriendsSR(FakeSubreddit):
    name = 'friends'
    title = 'friends'

    @classmethod
    @memoize("get_important_friends", 5*60)
    def get_important_friends(cls, user_id, max_lookup = 500, limit = 100):
        a = Account._byID(user_id, data = True)
        # friends are returned chronologically by date, so pick the end of the list
        # for the most recent additions
        friends = Account._byID(a.friends[-max_lookup:], return_dict = False,
                                data = True)

        # if we don't have a last visit for your friends, we don't
        # care about them
        last_visits = last_modified_multi(friends, "submitted")
        friends = [x for x in friends if x in last_visits]

        # sort friends by most recent interactions
        friends.sort(key = lambda x: last_visits[x], reverse = True)
        return [x._id for x in friends[:limit]]

    def get_links(self, sort, time):
        from r2.lib.db import queries

        if not c.user_is_loggedin:
            raise UserRequiredException

        friends = self.get_important_friends(c.user._id)

        if not friends:
            return []

        # with the precomputer enabled, this Subreddit only supports
        # being sorted by 'new'. it would be nice to have a
        # cleaner UI than just blatantly ignoring their sort,
        # though
        sort = 'new'
        time = 'all'

        friends = Account._byID(friends, return_dict=False)

        crs = [queries.get_submitted(friend, sort, time)
               for friend in friends]
        return queries.MergedCachedResults(crs)

    def get_all_comments(self):
        from r2.lib.db import queries

        if not c.user_is_loggedin:
            raise UserRequiredException

        friends = self.get_important_friends(c.user._id)

        if not friends:
            return []

        # with the precomputer enabled, this Subreddit only supports
        # being sorted by 'new'. it would be nice to have a
        # cleaner UI than just blatantly ignoring their sort,
        # though
        sort = 'new'
        time = 'all'

        friends = Account._byID(friends,
                                return_dict=False)

        crs = [queries.get_comments(friend, sort, time)
               for friend in friends]
        return queries.MergedCachedResults(crs)


class AllSR(FakeSubreddit):
    name = 'all'
    title = 'all subreddits'

    def keep_for_rising(self, sr_id):
        return True

    def get_links(self, sort, time):
        from r2.models import Link
        from r2.lib.db import queries
        q = Link._query(
            sort=queries.db_sort(sort),
            read_cache=True,
            write_cache=True,
            cache_time=60,
            data=True,
            filter_primary_sort_only=True,
        )
        if time != 'all':
            q._filter(queries.db_times[time])
        return q

    def get_all_comments(self):
        from r2.lib.db import queries
        return queries.get_all_comments()

    def get_gilded_comments(self):
        from r2.lib.db import queries
        return queries.get_all_gilded_comments()


class AllMinus(AllSR):
    name = _("%s (filtered)") % "all"

    def __init__(self, srs):
        AllSR.__init__(self)
        self.srs = srs
        self.sr_ids = [sr._id for sr in srs]

    def keep_for_rising(self, sr_id):
        return sr_id not in self.sr_ids

    @property
    def title(self):
        return 'all subreddits except ' + ', '.join(sr.name for sr in self.srs)

    @property
    def path(self):
        return '/r/all-' + '-'.join(sr.name for sr in self.srs)

    def get_links(self, sort, time):
        from r2.models import Link
        from r2.lib.db.operators import not_
        q = AllSR.get_links(self, sort, time)
        if c.user.gold:
            q._filter(not_(Link.c.sr_id.in_(self.sr_ids)))
        return q

class _DefaultSR(FakeSubreddit):
    #notice the space before reddit.com
    name = ' reddit.com'
    path = '/'
    header = g.default_header_url

    def _get_sr_ids(self):
        if not c.defaultsr_cached_sr_ids:
            user = c.user if c.user_is_loggedin else None
            c.defaultsr_cached_sr_ids = Subreddit.user_subreddits(user)
        return c.defaultsr_cached_sr_ids

    def keep_for_rising(self, sr_id):
        return sr_id in self._get_sr_ids()

    def is_moderator(self, user):
        return False

    def get_links(self, sort, time):
        sr_ids = self._get_sr_ids()
        return get_links_sr_ids(sr_ids, sort, time)

    @property
    def title(self):
        return _(g.short_description)

# This is the base class for the instantiated front page reddit
class DefaultSR(_DefaultSR):
    def __init__(self):
        _DefaultSR.__init__(self)
        try:
            self._base = Subreddit._by_name(g.default_sr, stale=True)
        except NotFound:
            self._base = None

    def wiki_can_submit(self, user):
        return True

    @property
    def wiki_use_subreddit_karma(self):
        return False

    @property
    def _should_wiki(self):
        return True
    
    @property
    def wikimode(self):
        return self._base.wikimode if self._base else "disabled"
    
    @property
    def wiki_edit_karma(self):
        return self._base.wiki_edit_karma

    @property
    def wiki_edit_age(self):
        return self._base.wiki_edit_age

    def is_wikicontributor(self, user):
        return self._base.is_wikicontributor(user)
    
    def is_wikibanned(self, user):
        return self._base.is_wikibanned(user)
    
    def is_wikicreate(self, user):
        return self._base.is_wikicreate(user)
    
    @property
    def _fullname(self):
        return "t5_6"
    
    @property
    def images(self):
        return self._base.images
    
    @property
    def _id36(self):
        return self._base._id36

    @property
    def type(self):
        return self._base.type if self._base else "public"

    @property
    def header(self):
        return (self._base and self._base.header) or _DefaultSR.header

    @property
    def header_title(self):
        return (self._base and self._base.header_title) or ""

    @property
    def header_size(self):
        return (self._base and self._base.header_size) or None

    @property
    def stylesheet_contents(self):
        return self._base.stylesheet_contents if self._base else ""

    @property
    def stylesheet_hash(self):
        return self._base.stylesheet_hash if self._base else ""


class MultiReddit(FakeSubreddit):
    name = 'multi'
    header = ""

    def __init__(self, path=None, srs=None):
        FakeSubreddit.__init__(self)
        if path is not None:
            self._path = path
        self._srs = srs or []

    @property
    def srs(self):
        return self._srs

    @property
    def sr_ids(self):
        return [sr._id for sr in self.srs]

    @property
    def kept_sr_ids(self):
        return [sr._id for sr in self.srs if not sr._spam]

    @property
    def banned_sr_ids(self):
        return [sr._id for sr in self.srs if sr._spam]

    def keep_for_rising(self, sr_id):
        return sr_id in self.kept_sr_ids

    def is_moderator(self, user):
        if not user:
            return False

        # Get moderator SRMember relations for all in srs
        # if a relation doesn't exist there will be a None entry in the
        # returned dict
        mod_rels = SRMember._fast_query(self.srs, user,
                                        'moderator', data=False)
        if None in mod_rels.values():
            return False
        else:
            return FakeSRMember(ModeratorPermissionSet)

    @property
    def title(self):
        return _('posts from %s') % ', '.join(sr.name for sr in self.srs)

    @property
    def path(self):
        return self._path

    def get_links(self, sort, time):
        return get_links_sr_ids(self.kept_sr_ids, sort, time)

    def get_all_comments(self):
        from r2.lib.db.queries import get_sr_comments, merge_results
        srs = Subreddit._byID(self.kept_sr_ids, return_dict=False)
        results = [get_sr_comments(sr) for sr in srs]
        return merge_results(*results)

    def get_gilded_comments(self):
        from r2.lib.db.queries import get_gilded_comments
        queries = [get_gilded_comments(sr_id) for sr_id in self.kept_sr_ids]
        return MergedCachedQuery(queries)


class TooManySubredditsError(Exception):
    pass


class LabeledMulti(tdb_cassandra.Thing, MultiReddit):
    """Thing with special columns that hold Subreddit ids and properties."""
    _use_db = True
    _views = []
    _defaults = dict(MultiReddit._defaults,
        visibility='private',
        description_md='',
        copied_from=None,  # for internal analysis/bookkeeping purposes
    )
    _extra_schema_creation_args = {
        "key_validation_class": tdb_cassandra.UTF8_TYPE,
        "column_name_class": tdb_cassandra.UTF8_TYPE,
        "default_validation_class": tdb_cassandra.UTF8_TYPE,
        "column_validation_classes": {
            "date": pycassa.system_manager.DATE_TYPE,
        },
    }
    _compare_with = tdb_cassandra.UTF8_TYPE
    _read_consistency_level = tdb_cassandra.CL.ONE
    _write_consistency_level = tdb_cassandra.CL.QUORUM

    SR_PREFIX = 'SR_'
    MAX_SR_COUNT = 100

    def __init__(self, _id=None, *args, **kwargs):
        tdb_cassandra.Thing.__init__(self, _id, *args, **kwargs)
        MultiReddit.__init__(self)
        self._owner = None

    @classmethod
    def _byID(cls, ids, return_dict=True, properties=None):
        ret = super(cls, cls)._byID(ids, return_dict=False,
                                    properties=properties)
        if not ret:
            return
        ret = cls._load(ret)
        if isinstance(ret, cls):
            return ret
        elif return_dict:
            return {thing._id: thing for thing in ret}
        else:
            return ret

    @classmethod
    def _load_no_lookup(cls, things, srs_dict, owners_dict):
        things, single = tup(things, ret_is_single=True)
        for thing in things:
            thing._srs = [srs_dict[sr_id] for sr_id in thing.sr_ids]
            thing._owner = owners_dict[thing.owner_fullname]
        return things[0] if single else things

    @classmethod
    def _load(cls, things):
        things, single = tup(things, ret_is_single=True)
        sr_ids = set(itertools.chain(*[thing.sr_ids for thing in things]))
        owner_fullnames = set((thing.owner_fullname for thing in things))

        srs = Subreddit._byID(sr_ids, data=True, return_dict=True)
        owners = Thing._by_fullname(owner_fullnames, data=True, return_dict=True)
        ret = cls._load_no_lookup(things, srs, owners)
        return ret[0] if single else things

    @property
    def sr_ids(self):
        return self.sr_props.keys()

    @property
    def srs(self):
        return self._srs

    @property
    def owner(self):
        return self._owner

    @property
    def sr_columns(self):
        # limit to max subreddit count, allowing a little fudge room for
        # cassandra inconsistency
        remaining = self.MAX_SR_COUNT + 10
        sr_columns = {}
        for k, v in self._t.iteritems():
            if not k.startswith(self.SR_PREFIX):
                continue

            sr_columns[k] = v

            remaining -= 1
            if remaining <= 0:
                break
        return sr_columns

    @property
    def sr_props(self):
        return self.columns_to_sr_props(self.sr_columns)

    @property
    def path(self):
        if isinstance(self.owner, Account):
            return '/user/%(username)s/m/%(multiname)s' % {
                'username': self.owner.name,
                'multiname': self.name,
            }

    @property
    def user_path(self):
        if self.owner == c.user:
            return '/me/m/%s' % self.name
        else:
            return self.path

    @property
    def name(self):
        return self._id.split('/')[-1]

    @property
    def analytics_name(self):
        # classify as "multi" (as for unnamed multis) until our traffic system
        # is smarter
        return 'multi'

    @property
    def title(self):
        if isinstance(self.owner, Account):
            return _('%s subreddits curated by /u/%s') % (self.name, self.owner.name)
        return _('%s subreddits') % self.name

    def can_view(self, user):
        if c.user_is_admin:
            return True

        return user == self.owner or self.visibility == 'public'

    def can_edit(self, user):
        if c.user_is_admin:
            return True

        return user == self.owner

    @classmethod
    def by_owner(cls, owner):
        return list(LabeledMultiByOwner.query([owner._fullname]))

    @classmethod
    def create(cls, path, owner):
        obj = cls(_id=path, owner_fullname=owner._fullname)
        obj._commit()
        obj._owner = owner
        return obj

    @classmethod
    def copy(cls, path, multi, owner):
        obj = cls(_id=path, **multi._t)
        obj.owner_fullname = owner._fullname
        obj._commit()
        obj._owner = owner
        return obj

    @classmethod
    def sr_props_to_columns(cls, sr_props):
        columns = {}
        sr_ids = []
        for sr_id, props in sr_props.iteritems():
            if isinstance(sr_id, BaseSite):
                sr_id = sr_id._id
            sr_ids.append(sr_id)
            columns[cls.SR_PREFIX + str(sr_id)] = json.dumps(props)
        return sr_ids, columns

    @classmethod
    def columns_to_sr_props(cls, columns):
        ret = {}
        for s, sr_prop_dump in columns.iteritems():
            sr_id = long(s.strip(cls.SR_PREFIX))
            sr_props = json.loads(sr_prop_dump)
            ret[sr_id] = sr_props
        return ret

    def _on_create(self):
        for view in self._views:
            view.add_object(self)

    def add_srs(self, sr_props):
        """Add/overwrite subreddit(s)."""
        sr_ids, sr_columns = self.sr_props_to_columns(sr_props)

        if len(set(sr_columns) | set(self.sr_columns)) > self.MAX_SR_COUNT:
            raise TooManySubredditsError

        new_sr_ids = set(sr_ids) - set(self.sr_ids)
        new_srs = Subreddit._byID(new_sr_ids, data=True, return_dict=False)
        self._srs.extend(new_srs)

        for attr, val in sr_columns.iteritems():
            self.__setattr__(attr, val)

    def del_srs(self, sr_ids):
        """Delete subreddit(s)."""
        sr_props = dict.fromkeys(tup(sr_ids), {})
        sr_ids, sr_columns = self.sr_props_to_columns(sr_props)

        for key in sr_columns.iterkeys():
            self.__delitem__(key)

        self._srs = [sr for sr in self._srs if sr._id not in sr_ids]

    def clear_srs(self):
        self.del_srs(self.sr_ids)

    def delete(self):
        # Do we want to actually delete objects?
        self._destroy()
        for view in self._views:
            rowkey = view._rowkey(self)
            column = view._obj_to_column(self)
            view._remove(rowkey, column)


@tdb_cassandra.view_of(LabeledMulti)
class LabeledMultiByOwner(tdb_cassandra.View):
    _use_db = True

    @classmethod
    def _rowkey(cls, lm):
        return lm.owner_fullname


class RandomReddit(FakeSubreddit):
    name = 'random'
    header = ""

class RandomNSFWReddit(FakeSubreddit):
    name = 'randnsfw'
    header = ""

class RandomSubscriptionReddit(FakeSubreddit):
    name = 'myrandom'
    header = ""

class ModContribSR(MultiReddit):
    name  = None
    title = None
    query_param = None

    def __init__(self):
        # Can't lookup srs right now, c.user not set
        MultiReddit.__init__(self)

    @property
    def sr_ids(self):
        if c.user_is_loggedin:
            return Subreddit.special_reddits(c.user, self.query_param)
        else:
            return []

    @property
    def srs(self):
        return Subreddit._byID(self.sr_ids, data=True, return_dict=False)

class ModSR(ModContribSR):
    name  = "subreddits you moderate"
    title = "subreddits you moderate"
    query_param = "moderator"
    path = "/r/mod"

    def is_moderator(self, user):
        return FakeSRMember(ModeratorPermissionSet)

class ContribSR(ModContribSR):
    name  = "contrib"
    title = "communities you're approved on"
    query_param = "contributor"
    path = "/r/contrib"

class SubSR(FakeSubreddit):
    stylesheet = 'subreddit.css'
    #this will make the javascript not send an SR parameter
    name = ''
    title = ''

    def can_view(self, user):
        return True

    def can_comment(self, user):
        return False

    def can_submit(self, user, promotion=False):
        return True

    @property
    def path(self):
        return "/subreddits/"

class DomainSR(FakeSubreddit):
    @property
    def path(self):
        return '/domain/' + self.domain

    def __init__(self, domain):
        FakeSubreddit.__init__(self)
        self.domain = domain
        self.name = domain 
        self.title = domain + ' ' + _('on reddit.com')

    def get_links(self, sort, time):
        from r2.lib.db import queries
        return queries.get_domain_links(self.domain, sort, time)

Frontpage = DefaultSR()
Sub = SubSR()
Friends = FriendsSR()
Mod = ModSR()
Contrib = ContribSR()
All = AllSR()
Random = RandomReddit()
RandomNSFW = RandomNSFWReddit()
RandomSubscription = RandomSubscriptionReddit()

Subreddit._specials.update(dict(friends = Friends,
                                randnsfw = RandomNSFW,
                                myrandom = RandomSubscription,
                                random = Random,
                                mod = Mod,
                                contrib = Contrib,
                                all = All))

class SRMember(Relation(Subreddit, Account)):
    _defaults = dict(encoded_permissions=None)
    _permission_class = None

    def has_permission(self, perm):
        """Returns whether this member has explicitly been granted a permission.
        """
        return self.get_permissions().get(perm, False)

    def get_permissions(self):
        """Returns permission set for this member (or None if N/A)."""
        if not self._permission_class:
            raise NotImplementedError
        return self._permission_class.loads(self.encoded_permissions)

    def update_permissions(self, **kwargs):
        """Grants or denies permissions to this member.

        Args are named parameters with bool or None values (use None to disable
        granting or denying the permission). After calling this method,
        the relation will be _dirty until _commit is called.
        """
        if not self._permission_class:
            raise NotImplementedError
        perm_set = self._permission_class.loads(self.encoded_permissions)
        if perm_set is None:
            perm_set = self._permission_class()
        for k, v in kwargs.iteritems():
            if v is None:
                if k in perm_set:
                    del perm_set[k]
            else:
                perm_set[k] = v
        self.encoded_permissions = perm_set.dumps()

    def set_permissions(self, perm_set):
        """Assigns a permission set to this relation."""
        self.encoded_permissions = perm_set.dumps()

    def is_superuser(self):
        return self.get_permissions().is_superuser()


class FakeSRMember:
    """All-permission granting stub for SRMember, used by FakeSubreddits."""
    def __init__(self, permission_class):
        self.permission_class = permission_class

    def has_permission(self, perm):
        return True

    def get_permissions(self):
        return self.permission_class(all=True)

    def is_superuser(self):
        return True


Subreddit.__bases__ += (
    UserRel('moderator', SRMember,
            permission_class=ModeratorPermissionSet),
    UserRel('moderator_invite', SRMember,
            permission_class=ModeratorPermissionSet),
    UserRel('contributor', SRMember),
    UserRel('subscriber', SRMember, disable_ids_fn=True),
    UserRel('banned', SRMember),
    UserRel('wikibanned', SRMember),
    UserRel('wikicontributor', SRMember),
)


class SubredditPopularityByLanguage(tdb_cassandra.View):
    _use_db = True
    _value_type = 'pickle'
    _connection_pool = 'main'
    _read_consistency_level = CL_ONE
