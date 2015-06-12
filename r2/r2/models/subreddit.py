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

from __future__ import with_statement

import base64
import collections
import datetime
import itertools
import json
import re
import struct

from pycassa.util import convert_uuid_to_time
from pylons import c, g, request
from pylons.i18n import _, N_

from r2.lib.db.thing import Thing, Relation, NotFound
from account import Account, AccountsActiveBySR, FakeAccount
from printable import Printable
from r2.lib.db.userrel import UserRel
from r2.lib.db.operators import lower, or_, and_, not_, desc
from r2.lib.errors import UserRequiredException, RedditError
from r2.lib.geoip import location_by_ips
from r2.lib.memoize import memoize
from r2.lib.permissions import ModeratorPermissionSet
from r2.lib.utils import tup, last_modified_multi, fuzz_activity, \
    unicode_title_to_ascii
from r2.lib.utils import (
    timeago,
    summarize_markdown,
    in_chunks,
    UrlParser,
)
from r2.lib.cache import sgm
from r2.lib.strings import strings, Score
from r2.lib.filters import _force_unicode
from r2.lib.db import tdb_cassandra
from r2.models.wiki import WikiPage, ImagesByWikiPage
from r2.models.trylater import TryLater, TryLaterBySubject
from r2.lib.merge import ConflictException
from r2.lib.cache import CL_ONE
from r2.lib import hooks
from r2.models.query_cache import MergedCachedQuery
import pycassa

from r2.lib.utils import set_last_modified
from r2.models.keyvalue import NamedGlobals
from r2.models.wiki import WikiPage
import os.path
import random

trylater_hooks = hooks.HookRegistrar()


def get_links_sr_ids(sr_ids, sort, time):
    from r2.lib.db import queries

    if not sr_ids:
        return []

    results = [queries._get_links(sr_id, sort, time) for sr_id in sr_ids]
    return queries.merge_results(*results)


def get_request_location():
    if c.location != '':
        # unset c attributes have the value ''
        return c.location

    c.location = None

    if c.user and c.user.pref_use_global_defaults:
        pass
    elif getattr(request, 'via_cdn', False):
        g.stats.simple_event('geoip.cdn_request')
        edgescape_info = request.environ.get('HTTP_X_AKAMAI_EDGESCAPE')
        if edgescape_info:
            try:
                items = edgescape_info.split(',')
                location_dict = dict(item.split('=') for item in items)
                c.location = location_dict.get('country_code', None)
            except:
                pass
    elif getattr(request, 'ip', None):
        g.stats.simple_event('geoip.non_cdn_request')
        timer = g.stats.get_timer("providers.geoip.location_by_ips")
        timer.start()
        location = location_by_ips(request.ip)
        if location:
            c.location = location.get('country_code', None)
        timer.stop()

    return c.location


subreddit_rx = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_]{2,20}\Z")
language_subreddit_rx = re.compile(r"\A[a-z]{2}\Z")
time_subreddit_rx = re.compile(r"\At:[A-Za-z0-9][A-Za-z0-9_]{2,22}\Z")


class BaseSite(object):
    _defaults = dict(
        static_path=g.static_path,
        stylesheet=None,
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

    @property
    def allows_referrers(self):
        return True

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

    def get_edited(self, include_links=True, include_comments=True):
        from r2.lib.db import queries
        return queries.get_edited(self, user=c.user,
                                  include_links=include_links,
                                  include_comments=include_comments)

    def get_all_comments(self):
        from r2.lib.db import queries
        return queries.get_sr_comments(self)

    def get_gilded(self):
        from r2.lib.db import queries
        return queries.get_gilded(self._id)

    @classmethod
    def get_modactions(cls, srs, mod=None, action=None):
        # Get a query that will yield ModAction objects with mod and action
        from r2.models import ModAction
        return ModAction.get_actions(srs, mod=mod, action=action)

    def get_live_promos(self):
        raise NotImplementedError


class SubredditExists(Exception): pass


class Subreddit(Thing, Printable, BaseSite):
    # Note: As of 2010/03/18, nothing actually overrides the static_path
    # attribute, even on a cname. So c.site.static_path should always be
    # the same as g.static_path.
    _defaults = dict(BaseSite._defaults,
        stylesheet_url="",
        stylesheet_url_http="",
        stylesheet_url_https="",
        header_size=None,
        allow_top=False, # overridden in "_new"
        reported=0,
        valid_votes=0,
        show_media=False,
        show_cname_sidebar=False,
        css_on_cname=True,
        domain=None,
        suggested_comment_sort=None,
        wikimode="disabled",
        wiki_edit_karma=100,
        wiki_edit_age=0,
        over_18=False,
        exclude_banned_modqueue=False,
        mod_actions=0,
        # do we allow self-posts, links only, or any?
        link_type='any', # one of ('link', 'self', 'any')
        sticky_fullname=None,
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
        submit_text="",
        allow_gilding=True,
        public_traffic=False,
        spam_links='high',
        spam_selfposts='high',
        spam_comments='low',
        archive_age=g.ARCHIVE_AGE,
        gilding_server_seconds=0,
        contest_mode_upvotes_only=False,
        collapse_deleted_comments=False,
        icon_img='',
        icon_size=None,
        banner_img='',
        banner_size=None,
        community_rules='',
        key_color='',
        hide_ads=False,
    )

    # special attributes that shouldn't set Thing data attributes because they
    # have special setters that set other data attributes
    _derived_attrs = (
        'related_subreddits',
    )

    _essentials = ('type', 'name', 'lang')
    _data_int_props = Thing._data_int_props + ('mod_actions', 'reported',
                                               'wiki_edit_karma', 'wiki_edit_age',
                                               'gilding_server_seconds')

    sr_limit = 50
    gold_limit = 100
    DEFAULT_LIMIT = object()

    ICON_EXACT_SIZE = (240, 240)
    BANNER_MIN_SIZE = (640, 360)
    BANNER_MAX_SIZE = (1280, 720)

    valid_types = {
        'archived',
        'employees_only',
        'gold_only',
        'gold_restricted',
        'private',
        'public',
        'restricted',
    }

    # this holds the subreddit types where content is not accessible
    # unless you are a contributor or mod
    private_types = {
        'employees_only',
        'gold_only',
        'private',
    }

    # in "rainbow" order
    KEY_COLORS = collections.OrderedDict([
        ('', N_('default')),
        ('#ea0027', N_('red')),
        ('#ff4500', N_('orangered')),
        ('#ff8717', N_('orange')),
        ('#ffd635', N_('yellow')),
        ('#fff03e', N_('highlight')),
        ('#c7e223', N_('lime')),
        ('#7cd344', N_('green')),
        ('#46a508', N_('dark green')),
        ('#008985', N_('dark teal')),
        ('#25b79f', N_('teal')),
        ('#24a0ed', N_('blue')),
        ('#0079d3', N_('alien blue')),
    ])

    def __setattr__(self, attr, val, make_dirty=True):
        if attr in self._derived_attrs:
            object.__setattr__(self, attr, val)
        else:
            Thing.__setattr__(self, attr, val, make_dirty=make_dirty)

    # note: for purposely unrenderable reddits (like promos) set author_id = -1
    @classmethod
    def _new(cls, name, title, author_id, ip, lang = g.lang, type = 'public',
             over_18 = False, **kw):
        if not cls.is_valid_name(name):
            raise ValueError("bad subreddit name")
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

    @classmethod
    def is_valid_name(cls, name, allow_language_srs=False, allow_time_srs=False,
                      allow_reddit_dot_com=False):
        if not name:
            return False

        if allow_reddit_dot_com and name.lower() == "reddit.com":
            return True

        valid = bool(subreddit_rx.match(name))

        if not valid and allow_language_srs:
            valid = bool(language_subreddit_rx.match(name))

        if not valid and allow_time_srs:
            valid = bool(time_subreddit_rx.match(name))

        return valid

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
            else:
                valid_name = cls.is_valid_name(lname, allow_language_srs=True,
                                               allow_time_srs=True,
                                               allow_reddit_dot_com=True)
                if valid_name:
                    to_fetch[lname] = name
                else:
                    g.log.debug("Subreddit._by_name() ignoring invalid srname: %s", lname)

        if to_fetch:
            srids_by_name = g.cache.get_multi(
                to_fetch.keys(), prefix='subreddit.byname', stale=True)

            missing_srnames = set(to_fetch.keys()) - set(srids_by_name.keys())
            if missing_srnames:
                for srnames in in_chunks(missing_srnames, size=10):
                    q = cls._query(
                        lower(cls.c.name) == srnames,
                        cls.c._spam == (True, False),
                        limit=len(srnames),
                        data=True,
                    )
                    fetched = {sr.name.lower(): sr._id for sr in q}
                    srids_by_name.update(fetched)
                    g.cache.set_multi(fetched, prefix='subreddit.byname')

            srs = {}
            srids = srids_by_name.values()
            if srids:
                srs = cls._byID(srids, data=True, return_dict=False, stale=stale)

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
    def allowed_types(self):
        if self.link_type == "any":
            return set(("link", "self"))
        return set((self.link_type,))

    @property
    def allows_referrers(self):
        return self.type in {'public', 'restricted',
                             'gold_restricted', 'archived'}

    def add_moderator(self, user, **kwargs):
        if not user.modmsgtime:
            user.modmsgtime = False
            user._commit()

        hook = hooks.get_hook("subreddit.add_moderator")
        hook.call(subreddit=self, user=user)

        return super(Subreddit, self).add_moderator(user, **kwargs)

    def remove_moderator(self, user, **kwargs):
        hook = hooks.get_hook("subreddit.remove_moderator")
        hook.call(subreddit=self, user=user)

        ret = super(Subreddit, self).remove_moderator(user, **kwargs)

        is_mod_somewhere = bool(Subreddit.reverse_moderator_ids(user))
        if not is_mod_somewhere:
            user.modmsgtime = None
            user._commit()

        return ret

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

    def fetch_stylesheet_source(self):
        try:
            return WikiPage.get(self, 'config/stylesheet')._get('content','')
        except tdb_cassandra.NotFound:
            return ""

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

    @property
    def hide_subscribers(self):
        return self.name.lower() in g.hide_subscribers_srs

    @property
    def hide_contributors(self):
        return self.type in {'employees_only', 'gold_only'}

    @property
    def _related_multipath(self):
        return '/r/%s/m/related' % self.name.lower()

    @property
    def related_subreddits(self):
        try:
            multi = LabeledMulti._byID(self._related_multipath)
        except tdb_cassandra.NotFound:
            multi = None
        return  [sr.name for sr in multi.srs] if multi else []

    @related_subreddits.setter
    def related_subreddits(self, related_subreddits):
        try:
            multi = LabeledMulti._byID(self._related_multipath)
        except tdb_cassandra.NotFound:
            if not related_subreddits:
                return
            multi = LabeledMulti.create(self._related_multipath, self)

        if related_subreddits:
            srs = Subreddit._by_name(related_subreddits)
            try:
                sr_props = {srs[sr_name]: {} for sr_name in related_subreddits}
            except KeyError as e:
                raise NotFound, 'Subreddit %s' % e.args[0]

            multi.clear_srs()
            multi.add_srs(sr_props)
            multi._commit()
        else:
            multi.delete()

    def get_accounts_active(self):
        fuzzed = False
        count = AccountsActiveBySR.get_count(self)
        key = 'get_accounts_active-' + self._id36

        # Fuzz counts having low values, for privacy reasons
        if count < 100 and not c.user_is_admin:
            fuzzed = True
            cached_count = g.cache.get(key)
            if not cached_count:
                count = fuzz_activity(count)
                g.cache.set(key, count, time=5*60)
            else:
                count = cached_count
        return count, fuzzed

    def spammy(self):
        return self._spam

    def is_contributor(self, user):
        if self.type == 'employees_only':
            return user.employee
        else:
            return super(Subreddit, self).is_contributor(user)

    def can_comment(self, user):
        if c.user_is_admin:
            return True

        override = hooks.get_hook("subreddit.can_comment").call_until_return(
                                                            sr=self, user=user)

        if override is not None:
            return override
        elif self.is_banned(user):
            return False
        elif self.type == 'gold_restricted' and user.gold:
            return True
        elif self.type in ('public','restricted'):
            return True
        elif self.is_moderator(user) or self.is_contributor(user):
            #private requires contributorship
            return True
        elif self.type == 'gold_only':
            return user.gold or user.gold_charter
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
        elif self.type == 'gold_only':
            return user.gold or user.gold_charter
        elif self.type == 'gold_restricted' and user.gold:
            return True
        elif self.type == 'restricted' and promotion:
            return True
        else:
            return False

    def can_submit_link(self, user):
        if c.user_is_admin or self.is_moderator_with_perms(user, "posts"):
            return True
        return "link" in self.allowed_types

    def can_submit_text(self, user):
        if c.user_is_admin or self.is_moderator_with_perms(user, "posts"):
            return True
        return "self" in self.allowed_types

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
        from r2.lib.template_helpers import make_url_protocol_relative

        if g.css_killswitch or (verify and not self.can_change_stylesheet(c.user)):
            return (None, None)

        if not content:
            return ([], "")

        # parse in regular old http mode
        images = ImagesByWikiPage.get_images(self, "config/stylesheet")
        protocol_relative_images = {
            name: make_url_protocol_relative(url)
            for name, url in images.iteritems()}
        parsed, errors = cssfilter.validate_css(
            content,
            protocol_relative_images,
        )

        return (errors, parsed)

    def change_css(self, content, parsed, prev=None, reason=None, author=None, force=False):
        from r2.models import ModAction
        from r2.lib.media import upload_stylesheet

        author = author if author else c.user._id36
        if content is None:
            content = ''
        try:
            wiki = WikiPage.get(self, 'config/stylesheet')
        except tdb_cassandra.NotFound:
            wiki = WikiPage.create(self, 'config/stylesheet')
        wr = wiki.revise(content, previous=prev, author=author, reason=reason, force=force)

        if parsed:
            self.stylesheet_url = upload_stylesheet(parsed)
            self.stylesheet_url_http = ""
            self.stylesheet_url_https = ""
        else:
            self.stylesheet_url = ""
            self.stylesheet_url_http = ""
            self.stylesheet_url_https = ""
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
        if self.is_special(user):
            return False

        hook = hooks.get_hook("account.is_ratelimit_exempt")
        ratelimit_exempt = hook.call_until_return(account=c.user)
        if ratelimit_exempt:
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
            if self.type == 'gold_only':
                return (user.gold or 
                    user.gold_charter or 
                    self.is_moderator(user) or 
                    self.is_moderator_invite(user))

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
            SRMember._fast_query(subreddits.values(), (c.user,), ('moderator',),
                                 data=True)

        return subreddits if return_dict else subreddits.values()

    def keep_for_rising(self, sr_id):
        """Return whether or not to keep a thing in rising for this SR."""
        return sr_id == self._id

    @classmethod
    def add_props(cls, user, wrapped):
        subscriber_srids = set()
        moderator_srids = set()
        contributor_srids = set()
        banned_srids = set()
        srmembers_to_fetch = []

        if not user or not c.user_is_loggedin or not user.has_subscribed:
            # NOTE: add_props is called with user = c.user, so
            # default_subreddits (which uses c.user rather than taking user as
            # an argument) will act as expected
            default_srids = Subreddit.default_subreddits()
            subscriber_srids.update(default_srids)
        else:
            srmembers_to_fetch.append('subscriber')

        if user and c.user_is_loggedin:
            srmembers_to_fetch.extend(['moderator', 'contributor', 'banned'])

        if srmembers_to_fetch:
            rels = SRMember._fast_query(wrapped, [user], srmembers_to_fetch)
            for (item, i_user, rel_name), rel in rels.iteritems():
                if not rel:
                    continue
                elif rel_name == 'subscriber':
                    subscriber_srids.add(item._id)
                elif rel_name == 'moderator':
                    moderator_srids.add(item._id)
                elif rel_name == 'contributor':
                    contributor_srids.add(item._id)
                elif rel_name == 'banned':
                    banned_srids.add(item._id)

        target = "_top" if c.cname else None
        for item in wrapped:
            item.subscriber = item._id in subscriber_srids
            item.moderator = item._id in moderator_srids
            item.contributor = item._id in contributor_srids
            item.banned = item._id in banned_srids

            if item.hide_subscribers and not c.user_is_admin:
                item._ups = 0

            item.score_hidden = not item.can_view(user)

            item.score = item._ups

            # override "voting" score behavior (it will override the use of
            # item.score in builder.py to be ups-downs)
            item.likes = item.subscriber or None
            base_score = item.score - (1 if item.likes else 0)
            item.voting_score = [(base_score + x - 1) for x in range(3)]
            item.score_fmt = Score.subscribers

            #will seem less horrible when add_props is in pages.py
            from r2.lib.pages import UserText
            if item.public_description or item.description:
                text = (item.public_description or
                        summarize_markdown(item.description))
                item.public_description_usertext = UserText(item,
                                                            text,
                                                            target=target)
            else:
                item.public_description_usertext = None


        Printable.add_props(user, wrapped)

    cache_ignore = {
        "description",
        "public_description",
        "subscribers",
    }.union(Printable.cache_ignore)

    @staticmethod
    def wrapped_cache_key(wrapped, style):
        s = Printable.wrapped_cache_key(wrapped, style)
        return s

    @classmethod
    def default_subreddits(cls, ids=True):
        """Return the subreddits a user with no subscriptions would see."""
        location = get_request_location()
        srids = LocalizedDefaultSubreddits.get_defaults(location)

        srs = Subreddit._byID(srids, data=True, return_dict=False, stale=True)
        srs = filter(lambda sr: sr.allow_top, srs)

        if ids:
            return [sr._id for sr in srs]
        else:
            return srs

    @classmethod
    @memoize('random_reddits', time = 1800)
    def random_reddits_cached(cls, user_name, sr_ids, limit):
        return random.sample(sr_ids, limit)

    @classmethod
    def random_reddits(cls, user_name, sr_ids, limit):
        """Select a random subset from sr_ids.

        Used for limiting the number of subscribed subreddits shown on a user's
        front page. Selection is cached for a while so the front page doesn't
        jump around.

        """

        if not limit:
            return sr_ids

        # if the user is subscribed to them, the automatic subreddits should
        # always be in the front page set and not count towards the limit
        if g.automatic_reddits:
            automatics = Subreddit._by_name(
                g.automatic_reddits, stale=True).values()
            automatic_ids = [sr._id for sr in automatics if sr._id in sr_ids]
            for sr_id in automatic_ids:
                sr_ids.remove(sr_id)
        else:
            automatic_ids = []

        if len(sr_ids) > limit:
            sr_ids = sorted(sr_ids)
            sr_ids = cls.random_reddits_cached(user_name, sr_ids, limit)

        return sr_ids + automatic_ids

    @classmethod
    def random_reddit(cls, over18=False, user=None):
        if over18:
            sr_ids = NamedGlobals.get("popular_over_18_sr_ids")
        else:
            sr_ids = NamedGlobals.get("popular_sr_ids")

        if user:
            excludes = set(cls.user_subreddits(user, limit=None))
            sr_ids = list(set(sr_ids) - excludes)

        if not sr_ids:
            return Subreddit._by_name(g.default_sr)

        sr_id = random.choice(sr_ids)
        sr = Subreddit._byID(sr_id, data=True)
        return sr

    @classmethod
    def update_popular_subreddits(cls, limit=5000):
        q = cls._query(cls.c.type == "public", sort=desc('_downs'), limit=limit,
                       data=True)
        srs = list(q)

        sr_ids = [sr._id for sr in srs if not sr.over_18]
        over_18_sr_ids = [sr._id for sr in srs if sr.over_18]

        # /r/promos is public but has special handling to make it unviewable
        promo_sr_id = cls.get_promote_srid()
        if promo_sr_id:
            try:
                sr_ids.remove(promo_sr_id)
            except ValueError:
                pass

        NamedGlobals.set("popular_sr_ids", sr_ids)
        NamedGlobals.set("popular_over_18_sr_ids", over_18_sr_ids)

    @classmethod
    def random_subscription(cls, user):
        srs = Subreddit.reverse_subscriber_ids(user)
        return (Subreddit._byID(random.choice(srs))
                if srs else Subreddit._by_name(g.default_sr))

    @classmethod
    def user_subreddits(cls, user, ids=True, limit=DEFAULT_LIMIT):
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
                                                      stale=True)
        else:
            return cls.default_subreddits(ids=ids)


    # Used to pull all of the SRs a given user moderates or is a contributor
    # to (which one is controlled by query_param)
    @classmethod
    def special_reddits(cls, user, query_param):
        lookup = getattr(cls, 'reverse_%s_ids' % query_param)
        return lookup(user)

    @classmethod
    def subscribe_defaults(cls, user):
        if not user.has_subscribed:
            for sr in cls.user_subreddits(user=None, ids=False, limit=None):
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

    def get_live_promos(self):
        from r2.lib import promote
        return promote.get_live_promotions([self.name])

    def schedule_unban(self, kind, victim, banner, duration):
        return SubredditTempBan.schedule(
            self,
            kind,
            victim,
            banner,
            datetime.timedelta(days=duration),
        )

    def unschedule_unban(self, victim, type):
        SubredditTempBan.unschedule(self.name, victim.name, type)

    def get_tempbans(self, type=None, names=None):
        return SubredditTempBan.search(self.name, type, names)

    def add_gilding_seconds(self):
        from r2.models.gold import get_current_value_of_month
        seconds = get_current_value_of_month()
        self._incr("gilding_server_seconds", int(seconds))

    @classmethod
    def get_promote_srid(cls):
        if g.promo_srid36:
            return int(g.promo_srid36, 36)
        else:
            return None


class FakeSubreddit(BaseSite):
    _defaults = dict(Subreddit._defaults,
        link_flair_position='right',
        flair_enabled=False,
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

    def get_gilded(self):
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

        # only include friends that have ever interacted with the site
        last_activity = last_modified_multi(friends, "overview")
        friends = [x for x in friends if x in last_activity]

        # sort friends by most recent interactions
        friends.sort(key = lambda x: last_activity[x], reverse = True)
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

    def get_gilded(self):
        from r2.lib.db.queries import get_gilded_users
        if not c.user_is_loggedin:
            raise UserRequiredException

        friends = self.get_important_friends(c.user._id)
        if not friends:
            return []

        return get_gilded_users(friends)


class AllSR(FakeSubreddit):
    name = 'all'
    title = 'all subreddits'
    path = '/r/all'

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

    def get_gilded(self):
        from r2.lib.db import queries
        return queries.get_all_gilded()


class AllMinus(AllSR):
    analytics_name = "all"
    name = _("%s (filtered)") % "all"

    def __init__(self, srs):
        AllSR.__init__(self)
        self.exclude_srs = srs
        self.exclude_sr_ids = [sr._id for sr in srs]

    def keep_for_rising(self, sr_id):
        return sr_id not in self.exclude_sr_ids

    @property
    def title(self):
        sr_names = ', '.join(sr.name for sr in self.exclude_srs)
        return 'all subreddits except ' + sr_names

    @property
    def path(self):
        return '/r/all-' + '-'.join(sr.name for sr in self.exclude_srs)

    def get_links(self, sort, time):
        from r2.models import Link
        from r2.lib.db.operators import not_
        q = AllSR.get_links(self, sort, time)
        if c.user.gold and self.exclude_sr_ids:
            q._filter(not_(Link.c.sr_id.in_(self.exclude_sr_ids)))
        return q


class Filtered(object):
    unfiltered_path = None

    @property
    def path(self):
        return '/me/f/%s' % self.filtername

    @property
    def title(self):
        return self.name

    @property
    def name(self):
        return _("%s (filtered)") % self.filtername

    @property
    def multi_path(self):
        return ('/user/%s/f/%s' % (c.user.name, self.filtername)).lower()

    def _get_filtered_subreddits(self):
        try:
            multi = LabeledMulti._byID(self.multi_path)
        except tdb_cassandra.NotFound:
            multi = None
        filtered_srs = multi.srs if multi else []
        return sorted(filtered_srs, key=lambda sr: sr.name)


class AllFiltered(Filtered, AllMinus):
    unfiltered_path = '/r/all'
    filtername = 'all'

    def __init__(self):
        filters = self._get_filtered_subreddits() if c.user.gold else []
        AllMinus.__init__(self, filters)


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
    @property
    def _base(self):
        try:
            return Subreddit._by_name(g.default_sr, stale=True)
        except NotFound:
            return None

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
    def stylesheet_url(self):
        return self._base.stylesheet_url if self._base else ""

    @property
    def stylesheet_url_http(self):
        return self._base.stylesheet_url_http if self._base else ""

    @property
    def stylesheet_url_https(self):
        return self._base.stylesheet_url_https if self._base else ""

    def get_all_comments(self):
        from r2.lib.db.queries import _get_sr_comments, merge_results
        sr_ids = Subreddit.user_subreddits(c.user)
        results = [_get_sr_comments(sr_id) for sr_id in sr_ids]
        return merge_results(*results)

    def get_gilded(self):
        from r2.lib.db.queries import get_gilded
        return get_gilded(Subreddit.user_subreddits(c.user))

    def get_live_promos(self):
        from r2.lib import promote
        srs = Subreddit.user_subreddits(c.user, ids=False)
        # '' is for promos targeted to the frontpage
        sr_names = [self.name] + [sr.name for sr in srs]
        return promote.get_live_promotions(sr_names)


class MultiReddit(FakeSubreddit):
    name = 'multi'
    header = ""
    _defaults = dict(
        FakeSubreddit._defaults,
        weighting_scheme="classic",
    )

    # See comment in normalized_hot before adding new values here.
    AGEWEIGHTS = {
        "classic": 0.0,
        "fresh": 0.15,
    }

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

    @property
    def allows_referrers(self):
        return all(sr.allows_referrers for sr in self.srs)

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

    def srs_with_perms(self, user, *perms):
        return [sr for sr in self.srs
                if sr.is_moderator_with_perms(user, *perms) and not sr._spam]

    @property
    def title(self):
        return _('posts from %s') % ', '.join(sr.name for sr in self.srs)

    @property
    def path(self):
        return self._path

    @property
    def over_18(self):
        return any(sr.over_18 for sr in self.srs)

    @property
    def ageweight(self):
        return self.AGEWEIGHTS.get(self.weighting_scheme, 0.0)

    def get_links(self, sort, time):
        return get_links_sr_ids(self.kept_sr_ids, sort, time)

    def get_all_comments(self):
        from r2.lib.db.queries import _get_sr_comments, merge_results
        results = [_get_sr_comments(sr_id) for sr_id in self.kept_sr_ids]
        return merge_results(*results)

    def get_gilded(self):
        from r2.lib.db.queries import get_gilded
        return get_gilded(self.kept_sr_ids)

    def get_live_promos(self):
        from r2.lib import promote
        srs = Subreddit._byID(self.kept_sr_ids, return_dict=False)
        sr_names = [sr.name for sr in srs]
        return promote.get_live_promotions(sr_names)


class TooManySubredditsError(Exception):
    pass


class LocalizedDefaultSubreddits(tdb_cassandra.View):
    """Mapping of location to subreddit ids"""
    _use_db = True
    _compare_with = tdb_cassandra.ASCII_TYPE
    _read_consistency_level = tdb_cassandra.CL.QUORUM
    _write_consistency_level = tdb_cassandra.CL.QUORUM
    _extra_schema_creation_args = {
        "key_validation_class": tdb_cassandra.ASCII_TYPE,
        "default_validation_class": tdb_cassandra.ASCII_TYPE,
    }
    GLOBAL = "GLOBAL"
    CACHE_PREFIX = "localized_defaults"

    @classmethod
    def _rowkey(cls, location):
        return str(location)

    @classmethod
    def lookup(cls, keys, update=False):
        def _lookup(keys):
            rows = cls._cf.multiget(keys)
            ret = {}
            for key in keys:
                columns = rows[key] if key in rows else {}
                id36s = columns.keys()
                ret[key] = id36s
            return ret

        id36s_by_location = sgm(
            g.cache, keys, miss_fn=_lookup, prefix=cls.CACHE_PREFIX,
            stale=True, _update=update,
        )
        ids_by_location = {location: [int(id36, 36) for id36 in id36s]
                           for location, id36s in id36s_by_location.iteritems()}
        return ids_by_location

    @classmethod
    def set_srs(cls, location, srs):
        rowkey = cls._rowkey(location)
        columns = {sr._id36: '' for sr in srs}

        # update cassandra
        try:
            existing = cls._cf.get(rowkey)
        except tdb_cassandra.NotFoundException:
            existing = {}

        cls._set_values(rowkey, columns)
        removed_srid36s = set(existing.keys()) - set(columns.keys())
        cls._remove(rowkey, removed_srid36s)

        # update cache
        id36s = columns.keys()
        g.cache.set_multi({rowkey: id36s}, prefix=cls.CACHE_PREFIX)

    @classmethod
    def set_global_srs(cls, srs):
        location = cls.GLOBAL
        cls.set_srs(location, srs)

    @classmethod
    def get_srids(cls, location):
        if not location:
            return []

        rowkey = cls._rowkey(location)
        ids_by_location = cls.lookup([rowkey])
        srids = ids_by_location[rowkey]
        return srids

    @classmethod
    def get_global_defaults(cls):
        return cls.get_srids(cls.GLOBAL)

    @classmethod
    def get_defaults(cls, location):
        location_key = cls._rowkey(location) if location else None
        global_key = cls._rowkey(cls.GLOBAL)
        keys = filter(None, [location_key, global_key])

        ids_by_location = cls.lookup(keys)

        if location_key and ids_by_location[location_key]:
            c.used_localized_defaults = True
            return ids_by_location[location_key]
        else:
            return ids_by_location[global_key]


class LabeledMulti(tdb_cassandra.Thing, MultiReddit):
    """Thing with special columns that hold Subreddit ids and properties."""
    _use_db = True
    _views = []
    _bool_props = ('is_symlink', )
    _defaults = dict(
        MultiReddit._defaults,
        visibility='private',
        is_symlink=False,
        description_md='',
        display_name='',
        copied_from=None,
        key_color="#cee3f8",  # A lovely shade of blue
        icon_id='',
        weighting_scheme="classic",
    )
    _extra_schema_creation_args = {
        "key_validation_class": tdb_cassandra.UTF8_TYPE,
        "column_name_class": tdb_cassandra.UTF8_TYPE,
        "default_validation_class": tdb_cassandra.UTF8_TYPE,
        "column_validation_classes": {
            "date": pycassa.system_manager.DATE_TYPE,
        },
    }
    _float_props = (
        "base_normalized_age_weight",
    )
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
    def _byID(cls, ids, return_dict=True, properties=None, load_subreddits=True,
              load_linked_multis=True):
        ret = super(cls, cls)._byID(ids, return_dict=False,
                                    properties=properties)
        if not ret:
            return

        ret = cls._load(ret, load_subreddits=load_subreddits,
                        load_linked_multis=load_linked_multis)
        if isinstance(ret, cls):
            return ret
        elif return_dict:
            return {thing._id: thing for thing in ret}
        else:
            return ret

    @classmethod
    def _load(cls, things, load_subreddits=True, load_linked_multis=True):
        things, single = tup(things, ret_is_single=True)

        # some objects are being loaded for the first time and need basic setup
        never_loaded = [t for t in things if not t._owner]
        if never_loaded:
            owner_fullnames = set(t.owner_fullname for t in never_loaded)
            owners = Thing._by_fullname(
                owner_fullnames, data=True, return_dict=True)
            for t in things:
                if t in never_loaded:
                    t._owner = owners[t.owner_fullname]
                    t._srs_loaded = False
                    t._linked_multi = None

        if load_linked_multis:
            needs_linked_multis = [t.copied_from for t in things
                                   if t.is_symlink and not t._linked_multi]
            if needs_linked_multis:
                multis = LabeledMulti._byID(needs_linked_multis, return_dict=True)
                for t in things:
                    if t.copied_from in needs_linked_multis:
                        t._linked_multi = multis[t.copied_from]

        # some objects may have been retrieved from cache and need srs
        if load_subreddits:
            needs_srs = [t for t in things if not t._srs_loaded]
            if needs_srs:
                sr_ids = set(
                    itertools.chain.from_iterable(t.sr_ids for t in needs_srs))
                srs = Subreddit._byID(
                    sr_ids, data=True, return_dict=True, stale=True)
                for t in things:
                    if t in needs_srs:
                        t._srs = [srs[sr_id] for sr_id in t.sr_ids]
                        t._srs_loaded = True

        return things[0] if single else things

    @property
    def linked_multi(self):
        return self._linked_multi

    @property
    def sr_ids(self):
        return self.sr_props.keys()

    @property
    def srs(self):
        if self.is_symlink:
            if (not self.copied_from or self.copied_from == self._id
                    or not self.linked_multi):
                raise RedditError("Upstream symlinked multi can't be retrieved.")
            if not self.linked_multi.can_view(self.owner):
                raise RedditError("Upstream symlinked multi is not visible.")

            return self.linked_multi.srs

        if not self._srs_loaded:
            g.log.error("%s: accessed subreddits without loading", self)
            self._srs = Subreddit._byID(
                self.sr_ids, data=True, return_dict=False)
        return self._srs

    @property
    def owner(self):
        return self._owner

    @property
    def sr_columns(self):
        # limit to max subreddit count, allowing a little fudge room for
        # cassandra inconsistency
        if self.is_symlink:
            return self.linked_multi.sr_columns

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
    def kind(self):
        return self._id.split('/')[3]

    @property
    def sr_props(self):
        return self.columns_to_sr_props(self.sr_columns)

    @property
    def path(self):
        if isinstance(self.owner, Account):
            return '/user/%(username)s/%(kind)s/%(multiname)s' % {
                'username': self.owner.name,
                'kind': self.kind,
                'multiname': self.name,
            }
        if isinstance(self.owner, Subreddit):
            return '/r/%(srname)s/%(kind)s/%(multiname)s' % {
                'srname': self.owner.name,
                'kind': self.kind,
                'multiname': self.name,
            }

    @property
    def user_path(self):
        if self.owner == c.user:
            return '/me/%s/%s' % (self.kind, self.name)
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
    def allows_referrers(self):
        if not self.is_public():
            return False
        return super(LabeledMulti, self).allows_referrers

    @property
    def title(self):
        if isinstance(self.owner, Account):
            return _('%s subreddits curated by /u/%s') % (self.name, self.owner.name)
        return _('%s subreddits') % self.name

    def is_public(self):
        return self.visibility == "public"

    def is_hidden(self):
        return self.visibility == "hidden"

    def can_view(self, user):
        if c.user_is_admin:
            return True

        if self.is_public():
            return True

        if isinstance(user, FakeAccount):
            return False

        # subreddit multireddit (mod can view)
        if isinstance(self.owner, Subreddit):
            return self.owner.is_moderator_with_perms(user, 'config')

        return user == self.owner

    def can_edit(self, user):
        if isinstance(user, FakeAccount):
            return False

        # subreddit multireddit (admin can edit)
        if isinstance(self.owner, Subreddit):
            return (c.user_is_admin or
                    self.owner.is_moderator_with_perms(user, 'config'))

        if c.user_is_admin and self.owner == Account.system_user():
            return True

        return user == self.owner

    @property
    def icon_url(self):
        from r2.lib.template_helpers import static
        if self.icon_id:
            path = "multi_icons/{}.png".format(self.icon_id.replace(" ", "_"))
            return static(path)
        else:
            return None

    def set_icon_by_name(self, name):
        """Set this multi's icon information by icon name

        Note: tdb_cassandra.Thing doesn't support property.setter properly;
        it appears to write through directly to self._t['icon_name'].

        """
        if not name:
            self.icon_id = ''
        elif name in g.multi_icons:
            self.icon_id = name
        else:
            raise ValueError("invalid multi icon name")

    @classmethod
    def by_owner(cls, owner, kinds=None, load_subreddits=True):
        try:
            multi_ids = LabeledMultiByOwner._byID(owner._fullname)._t.keys()
        except tdb_cassandra.NotFound:
            return []

        kinds = ('m',) if not kinds else kinds
        multis = cls._byID(
            multi_ids, return_dict=False, load_subreddits=load_subreddits)
        return [multi for multi in multis if multi.kind in kinds]

    @classmethod
    def create(cls, path, owner):
        obj = cls(_id=path, owner_fullname=owner._fullname)
        obj._commit()
        obj._owner = owner
        obj._srs_loaded = False
        return obj

    @classmethod
    def copy(cls, path, multi, owner, symlink=False):
        if symlink:
            # remove all the sr_ids from the properties
            props = {k: v for k, v in multi._t.iteritems()
                     if k not in multi.sr_columns.keys()}
            props["is_symlink"] = True
        else:
            props = multi._t

        obj = cls(_id=path, **props)
        obj._srs = multi._srs
        obj._srs_loaded = multi._srs_loaded
        obj.owner_fullname = owner._fullname
        obj.copied_from = multi.path.lower()
        obj._commit()
        obj._linked_multi = multi if symlink else None
        obj._owner = owner

        return obj

    @classmethod
    def slugify(cls, owner, display_name, type_="m"):
        """Generate user multi path from display name."""
        slug = unicode_title_to_ascii(display_name)
        if isinstance(owner, Subreddit):
            prefix = "/r/" + owner.name + "/" + type_ + "/"
        else:
            prefix = "/user/" + owner.name + "/" + type_ + "/"
        new_path = prefix + slug
        try:
            existing = LabeledMultiByOwner._byID(owner._fullname)._t.keys()
        except tdb_cassandra.NotFound:
            existing = []
        count = 0
        while new_path in existing:
            count += 1
            new_path = prefix + slug + str(count)
        return new_path

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

    def unlink(self):
        if not self.is_symlink:
            return

        self._srs = self.srs
        sr_props = dict.fromkeys(self.srs, {})
        sr_ids, sr_columns = self.sr_props_to_columns(sr_props)
        for attr, val in sr_columns.iteritems():
            self.__setattr__(attr, val)

        self.is_symlink = False

    def add_srs(self, sr_props):
        """Add/overwrite subreddit(s)."""
        if self.is_symlink:
            self.unlink()
        sr_ids, sr_columns = self.sr_props_to_columns(sr_props)

        if len(set(sr_columns) | set(self.sr_columns)) > self.MAX_SR_COUNT:
            raise TooManySubredditsError

        new_sr_ids = set(sr_ids) - set(self.sr_ids)
        new_srs = Subreddit._byID(
            new_sr_ids, data=True, return_dict=False, stale=True)
        self._srs.extend(new_srs)

        for attr, val in sr_columns.iteritems():
            self.__setattr__(attr, val)

    def del_srs(self, sr_ids):
        """Delete subreddit(s)."""
        if self.is_symlink:
            self.unlink()

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

    @property
    def allows_referrers(self):
        return False


class ModSR(ModContribSR):
    name  = "subreddits you moderate"
    title = "subreddits you moderate"
    query_param = "moderator"
    path = "/r/mod"

    def is_moderator(self, user):
        return FakeSRMember(ModeratorPermissionSet)


class ModMinus(ModSR):
    analytics_name = "mod"

    def __init__(self, exclude_srs):
        ModSR.__init__(self)
        self.exclude_srs = exclude_srs
        self.exclude_sr_ids = [sr._id for sr in exclude_srs]

    @property
    def sr_ids(self):
        sr_ids = super(ModMinus, self).sr_ids
        return [sr_id for sr_id in sr_ids if not sr_id in self.exclude_sr_ids]

    @property
    def name(self):
        exclude_text = ', '.join(sr.name for sr in self.exclude_srs)
        return 'subreddits you moderate except ' + exclude_text

    @property
    def title(self):
        return self.name

    @property
    def path(self):
        return '/r/mod-' + '-'.join(sr.name for sr in self.exclude_srs)


class ModFiltered(Filtered, ModMinus):
    unfiltered_path = '/r/mod'
    filtername = 'mod'

    def __init__(self):
        ModMinus.__init__(self, self._get_filtered_subreddits())


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
        domain = domain.lower()
        self.domain = domain
        self.name = domain 
        self.title = _("%(domain)s on %(reddit.com)s") % {
            "domain": domain, "reddit.com": g.domain}
        idn = domain.decode('idna')
        if idn != domain:
            self.idn = idn

    def get_links(self, sort, time):
        from r2.lib.db import queries
        return queries.get_domain_links(self.domain, sort, time)

class SearchResultSubreddit(Subreddit):
    _nodb = True

    @classmethod
    def add_props(cls, user, wrapped):
        from r2.controllers.reddit_base import UnloggedUser
        Subreddit.add_props(user, wrapped)
        for item in wrapped:
            url = UrlParser(item.path)
            url.update_query(ref="search_subreddits")
            item.search_path = url.unparse()
            can_view = item.can_view(user)
            if isinstance(user, UnloggedUser):
                can_comment = item.type == "public"
            else:
                can_comment = item.can_comment(user)
            if not can_view:
                item.display_type = "private"
            elif item.type == "archived":
                item.display_type = "archived"
            elif not can_comment:
                item.display_type = "restricted"
            else:
                item.display_type = "public"
        Printable.add_props(user, wrapped)

Frontpage = DefaultSR()
Sub = SubSR()
Friends = FriendsSR()
Mod = ModSR()
Contrib = ContribSR()
All = AllSR()
Random = RandomReddit()
RandomNSFW = RandomNSFWReddit()
RandomSubscription = RandomSubscriptionReddit()

# add to _specials so they can be retrieved with Subreddit._by_name, e.g.
# Subreddit._by_name("all")
Subreddit._specials.update({
    sr.name: sr for sr in (
        Friends,
        RandomNSFW,
        RandomSubscription,
        Random,
        Contrib,
        All,
        Frontpage,
    )
})

# some subreddits have unfortunate names
Subreddit._specials['mod'] = Mod


class SRMember(Relation(Subreddit, Account)):
    _defaults = dict(encoded_permissions=None)
    _permission_class = None
    _cache = g.srmembercache
    _fast_cache = g.srmembercache

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


class SubredditTempBan(object):
    def __init__(self, sr, kind, victim, banner, duration):
        self.sr = sr._id36
        self._srname = sr.name
        self.who = victim._id36
        self._whoname = victim.name
        self.type = kind
        self.banner = banner._id36
        self.duration = duration

    @classmethod
    def schedule(cls, sr, kind, victim, banner, duration):
        info = {
            'sr': sr._id36,
            'who': victim._id36,
            'type': kind,
            'banner': banner._id36,
        }
        result = TryLaterBySubject.schedule(
            cls.cancel_rowkey(sr.name, kind),
            cls.cancel_colkey(victim.name),
            json.dumps(info),
            duration,
            trylater_rowkey=cls.schedule_rowkey(),
        )
        return {victim.name: result.keys()[0]}

    @classmethod
    def cancel_colkey(cls, name):
        return name

    @classmethod
    def cancel_rowkey(cls, name, type):
        return "srunban:%s:%s" % (name, type)

    @classmethod
    def schedule_rowkey(cls):
        return "srunban"

    @classmethod
    def search(cls, srname, bantype, subjects):
        results = TryLaterBySubject.search(cls.cancel_rowkey(srname, bantype),
                                           subjects)

        def convert_uuid_to_datetime(uu):
            return datetime.datetime.fromtimestamp(convert_uuid_to_time(uu),
                                                   g.tz)
        return {
            name: convert_uuid_to_datetime(uu)
                for name, uu in results.iteritems()
        }

    @classmethod
    def unschedule(cls, srname, victim_name, bantype):
        TryLaterBySubject.unschedule(
            cls.cancel_rowkey(srname, bantype),
            cls.cancel_colkey(victim_name),
            cls.schedule_rowkey(),
        )


@trylater_hooks.on('trylater.srunban')
def on_subreddit_unban(data):
    from r2.models.modaction import ModAction
    for blob in data.itervalues():
        baninfo = json.loads(blob)
        container = Subreddit._byID36(baninfo['sr'], data=True)
        victim = Account._byID36(baninfo['who'], data=True)
        banner = Account._byID36(baninfo['banner'], data=True)
        kind = baninfo['type']
        remove_function = getattr(container, 'remove_' + kind)
        new = remove_function(victim)
        g.log.info("Unbanned %s from %s", victim.name, container.name)

        if new:
            action = dict(
                banned='unbanuser',
                wikibanned='wikiunbanned',
            ).get(kind, None)
            ModAction.create(container, banner, action, target=victim,
                             description="was temporary")
