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

from account import *
from link import *
from vote import *
from report import *
from listing import Listing
from pylons import g
from pylons.i18n import _

import subreddit
import datetime

from r2.lib.comment_tree import moderator_messages, sr_conversation, conversation
from r2.lib.comment_tree import user_messages, subreddit_messages

from r2.lib.wrapped import Wrapped
from r2.lib import utils
from r2.lib.db import operators, tdb_cassandra
from r2.lib.filters import _force_unicode
from copy import deepcopy
from r2.lib.utils import Storage

from r2.models import wiki

from collections import defaultdict
import time
from admintools import compute_votes, admintools, ip_span, is_banned_domain

EXTRA_FACTOR = 1.5
MAX_RECURSION = 10

class Builder(object):
    def __init__(self, wrap=Wrapped, keep_fn=None, stale=True, spam_listing=False):
        self.stale = stale
        self.wrap = wrap
        self.keep_fn = keep_fn
        self.spam_listing = spam_listing

    def keep_item(self, item):
        if self.keep_fn:
            return self.keep_fn(item)
        else:
            return item.keep_item(item)

    def wrap_items(self, items):
        from r2.lib.db import queries
        from r2.lib.template_helpers import add_attr
        user = c.user if c.user_is_loggedin else None

        #get authors
        #TODO pull the author stuff into add_props for links and
        #comments and messages?

        aids = set(l.author_id for l in items if hasattr(l, 'author_id')
                   and l.author_id is not None)

        authors = {}
        cup_infos = {}
        friend_rels = None
        if aids:
            authors = Account._byID(aids, data=True, stale=self.stale) if aids else {}
            cup_infos = Account.cup_info_multi(aids)
            if user and user.gold:
                friend_rels = user.friend_rels()

        subreddits = Subreddit.load_subreddits(items, stale=self.stale)

        can_ban_set = set()
        can_flair_set = set()
        can_own_flair_set = set()
        if user:
            for sr_id, sr in subreddits.iteritems():
                if sr.can_ban(user):
                    can_ban_set.add(sr_id)
                if sr.is_moderator_with_perms(user, 'flair'):
                    can_flair_set.add(sr_id)
                if sr.link_flair_self_assign_enabled:
                    can_own_flair_set.add(sr_id)

        #get likes/dislikes
        try:
            likes = queries.get_likes(user, items)
        except tdb_cassandra.TRANSIENT_EXCEPTIONS as e:
            g.log.warning("Cassandra vote lookup failed: %r", e)
            likes = {}
        uid = user._id if user else None

        types = {}
        wrapped = []

        modlink = {}
        modlabel = {}
        for s in subreddits.values():
            modlink[s._id] = '/r/%s/about/moderators' % s.name
            modlabel[s._id] = (_('moderator of /r/%(reddit)s, speaking officially') %
                        dict(reddit = s.name) )


        for item in items:
            w = self.wrap(item)
            wrapped.append(w)
            # add for caching (plus it should be bad form to use _
            # variables in templates)
            w.fullname = item._fullname
            types.setdefault(w.render_class, []).append(w)

            #TODO pull the author stuff into add_props for links and
            #comments and messages?
            w.author = None
            w.friend = False

            # List of tuples (see add_attr() for details)
            w.attribs = []

            w.distinguished = None
            if hasattr(item, "distinguished"):
                if item.distinguished == 'yes':
                    w.distinguished = 'moderator'
                elif item.distinguished in ('admin', 'special'):
                    w.distinguished = item.distinguished

            try:
                w.author = authors.get(item.author_id)
                if user and item.author_id in user.friends:
                    # deprecated old way:
                    w.friend = True

                    # new way:
                    label = None
                    if friend_rels:
                        rel = friend_rels[item.author_id]
                        note = getattr(rel, "note", None)
                        if note:
                            label = u"%s (%s)" % (_("friend"), 
                                                  _force_unicode(note))
                    add_attr(w.attribs, 'F', label)

            except AttributeError:
                pass

            if (w.distinguished == 'admin' and w.author):
                add_attr(w.attribs, 'A')

            if w.distinguished == 'moderator':
                add_attr(w.attribs, 'M', label=modlabel[item.sr_id],
                         link=modlink[item.sr_id])
            
            if w.distinguished == 'special':
                args = w.author.special_distinguish()
                args.pop('name')
                if not args.get('kind'):
                    args['kind'] = 'special'
                add_attr(w.attribs, **args)

            if w.author and w.author._id in cup_infos and not c.profilepage:
                cup_info = cup_infos[w.author._id]
                label = _(cup_info["label_template"]) % \
                        {'user':w.author.name}
                add_attr(w.attribs, 'trophy:' + cup_info["img_url"],
                         label=label,
                         link = "/user/%s" % w.author.name)

            if hasattr(item, "sr_id") and item.sr_id is not None:
                w.subreddit = subreddits[item.sr_id]

            w.likes = likes.get((user, item))

            # update vote tallies
            compute_votes(w, item)

            w.score = w.upvotes - w.downvotes

            if w.likes:
                base_score = w.score - 1
            elif w.likes is None:
                base_score = w.score
            else:
                base_score = w.score + 1

            # store the set of available scores based on the vote
            # for ease of i18n when there is a label
            w.voting_score = [(base_score + x - 1) for x in range(3)]

            w.deleted = item._deleted

            w.link_notes = []

            if c.user_is_admin:
                if item._deleted:
                    w.link_notes.append("deleted link")
                if getattr(item, "verdict", None):
                    if not item.verdict.endswith("-approved"):
                        w.link_notes.append(w.verdict)
                if hasattr(item, 'url') and is_banned_domain(item.url):
                    w.link_notes.append("banned domain")

            if c.user_is_admin and getattr(item, 'ip', None):
                w.ip_span = ip_span(item.ip)
            else:
                w.ip_span = ""

            # if the user can ban things on a given subreddit, or an
            # admin, then allow them to see that the item is spam, and
            # add the other spam-related display attributes
            w.show_reports = False
            w.show_spam    = False
            w.can_ban      = False
            w.can_flair    = False
            w.use_big_modbuttons = self.spam_listing

            if (c.user_is_admin
                or (user
                    and hasattr(item,'sr_id')
                    and item.sr_id in can_ban_set)):
                if getattr(item, "promoted", None) is None:
                    w.can_ban = True

                ban_info = getattr(item, 'ban_info', {})
                w.unbanner = ban_info.get('unbanner')

                if item._spam:
                    w.show_spam = True
                    w.moderator_banned = ban_info.get('moderator_banned', False)
                    w.autobanned = ban_info.get('auto', False)
                    w.banner = ban_info.get('banner')
                    if ban_info.get('note', None) and w.banner:
                        w.banner += ' (%s)' % ban_info['note']
                    w.use_big_modbuttons = True
                    if getattr(w, "author", None) and w.author._spam:
                        w.show_spam = "author"

                    if c.user == w.author and c.user._spam:
                        w.show_spam = False
                        w._spam = False
                        w.use_big_modbuttons = False

                elif (getattr(item, 'reported', 0) > 0
                      and (not getattr(item, 'ignore_reports', False) or c.user_is_admin)):
                    w.show_reports = True
                    w.use_big_modbuttons = True

            if (c.user_is_admin
                or (user and hasattr(item, 'sr_id')
                    and (item.sr_id in can_flair_set
                         or (w.author and w.author._id == user._id
                             and item.sr_id in can_own_flair_set)))):
                w.can_flair = True

            w.approval_checkmark = None
            if w.can_ban:
                verdict = getattr(w, "verdict", None)
                if verdict in ('admin-approved', 'mod-approved'):
                    approver = None
                    baninfo = getattr(w, "ban_info", None)
                    if baninfo:
                        approver = baninfo.get("unbanner", None)
                        approval_time = baninfo.get("unbanned_at", None)

                    approver = approver or _("a moderator")

                    if approval_time:
                        text = _("approved by %(who)s %(when)s ago") % {
                                    "who": approver,
                                    "when": timesince(approval_time)}
                    else:
                        text = _("approved by %s") % approver
                    w.approval_checkmark = text

        # recache the user object: it may be None if user is not logged in,
        # whereas now we are happy to have the UnloggedUser object
        user = c.user
        for cls in types.keys():
            cls.add_props(user, types[cls])

        return wrapped

    def get_items(self):
        raise NotImplementedError

    def item_iter(self, *a):
        """Iterates over the items returned by get_items"""
        raise NotImplementedError

    def must_skip(self, item):
        """whether or not to skip any item regardless of whether the builder
        was contructed with skip=true"""
        user = c.user if c.user_is_loggedin else None
        if hasattr(item, "promoted") and item.promoted is not None:
            return False
        if hasattr(item, 'subreddit') and not item.subreddit.can_view(user):
            return True
        if hasattr(item, 'can_view_slow') and not item.can_view_slow():
            return True

class QueryBuilder(Builder):
    def __init__(self, query, wrap=Wrapped, keep_fn=None, skip=False,
                 spam_listing=False, **kw):
        Builder.__init__(self, wrap=wrap, keep_fn=keep_fn, spam_listing=spam_listing)
        self.query = query
        self.skip = skip
        self.num = kw.get('num')
        self.start_count = kw.get('count', 0) or 0
        self.after = kw.get('after')
        self.reverse = kw.get('reverse')

        self.prewrap_fn = None
        if hasattr(query, 'prewrap_fn'):
            self.prewrap_fn = query.prewrap_fn
        #self.prewrap_fn = kw.get('prewrap_fn')

    def __repr__(self):
        return "<%s(%r)>" % (self.__class__.__name__, self.query)

    def item_iter(self, a):
        """Iterates over the items returned by get_items"""
        for i in a[0]:
            yield i

    def init_query(self):
        q = self.query

        if self.reverse:
            q._reverse()

        q._data = True
        self.orig_rules = deepcopy(q._rules)
        if self.after:
            q._after(self.after)

    def fetch_more(self, last_item, num_have):
        done = False
        q = self.query
        if self.num:
            num_need = self.num - num_have
            if num_need <= 0:
                #will cause the loop below to break
                return True, None
            else:
                #q = self.query
                #check last_item if we have a num because we may need to iterate
                if last_item:
                    q._rules = deepcopy(self.orig_rules)
                    q._after(last_item)
                    last_item = None
                q._limit = max(int(num_need * EXTRA_FACTOR), 1)
        else:
            done = True
        new_items = list(q)

        return done, new_items

    def get_items(self):
        self.init_query()

        num_have = 0
        done = False
        items = []
        count = self.start_count
        first_item = None
        last_item = None
        have_next = True

        #logloop
        self.loopcount = 0
        
        while not done:
            done, new_items = self.fetch_more(last_item, num_have)

            #log loop
            self.loopcount += 1
            if self.loopcount == 20:
                g.log.debug('BREAKING: %s' % self)
                done = True

            #no results, we're done
            if not new_items:
                break;

            #if fewer results than we wanted, we're done
            elif self.num and len(new_items) < self.num - num_have:
                done = True
                have_next = False

            if not first_item and self.start_count > 0:
                first_item = new_items[0]

            if self.prewrap_fn:
                orig_items = {}
                new_items2 = []
                for i in new_items:
                    new = self.prewrap_fn(i)
                    orig_items[new._id] = i
                    new_items2.append(new)
                new_items = new_items2
            else:
                orig_items = dict((i._id, i) for i in new_items)

            if self.wrap:
                new_items = self.wrap_items(new_items)

            #skip and count
            while new_items and (not self.num or num_have < self.num):
                i = new_items.pop(0)

                if not (self.must_skip(i) or self.skip and not self.keep_item(i)):
                    items.append(i)
                    num_have += 1
                    count = count - 1 if self.reverse else count + 1
                    if self.wrap:
                        i.num = count
                last_item = i
        
            # get original version of last item
            if last_item and (self.prewrap_fn or self.wrap):
                last_item = orig_items[last_item._id]

        if self.reverse:
            items.reverse()
            last_item, first_item = first_item, have_next and last_item
            before_count = count
            after_count = self.start_count - 1
        else:
            last_item = have_next and last_item
            before_count = self.start_count + 1
            after_count = count

        #listing is expecting (things, prev, next, bcount, acount)
        return (items,
                first_item,
                last_item,
                before_count,
                after_count)

class IDBuilder(QueryBuilder):
    def thing_lookup(self, names):
        return Thing._by_fullname(names, data=True, return_dict=False,
                                  stale=self.stale)

    def init_query(self):
        names = list(tup(self.query))

        after = self.after._fullname if self.after else None

        self.names = self._get_after(names,
                                     after,
                                     self.reverse)

    @staticmethod
    def _get_after(l, after, reverse):
        names = list(l)

        if reverse:
            names.reverse()

        if after:
            try:
                i = names.index(after)
            except ValueError:
                names = ()
            else:
                names = names[i + 1:]

        return names

    def fetch_more(self, last_item, num_have):
        done = False
        names = self.names
        if self.num:
            num_need = self.num - num_have
            if num_need <= 0:
                return True, None
            else:
                if last_item:
                    last_item = None
                slice_size = max(int(num_need * EXTRA_FACTOR), 1)
        else:
            slice_size = len(names)
            done = True

        self.names, new_names = names[slice_size:], names[:slice_size]
        new_items = self.thing_lookup(new_names)
        return done, new_items


class CampaignBuilder(IDBuilder):
    """Build on a list of PromoTuples."""

    def __init__(self, query, wrap=Wrapped, keep_fn=None, prewrap_fn=None,
                 skip=False, num=None):
        Builder.__init__(self, wrap=wrap, keep_fn=keep_fn)
        self.query = query
        self.skip = skip
        self.num = num
        self.start_count = 0
        self.after = None
        self.reverse = False
        self.prewrap_fn = prewrap_fn

    def thing_lookup(self, tuples):
        links = Link._by_fullname([t.link for t in tuples], data=True,
                                  return_dict=True, stale=self.stale)

        return [Storage({'thing': links[t.link],
                         '_id': links[t.link]._id,
                         'weight': t.weight,
                         'campaign': t.campaign}) for t in tuples]

    def wrap_items(self, items):
        links = [i.thing for i in items]
        wrapped = IDBuilder.wrap_items(self, links)
        by_link = defaultdict(list)
        for w in wrapped:
            by_link[w._fullname].append(w)

        ret = []
        for i in items:
            w = by_link[i.thing._fullname].pop()
            w.campaign = i.campaign
            w.weight = i.weight
            ret.append(w)

        return ret


class SimpleBuilder(IDBuilder):
    def thing_lookup(self, names):
        return names

    def init_query(self):
        items = list(tup(self.query))

        if self.reverse:
            items.reverse()

        if self.after:
            for i, item in enumerate(items):
                if item._id == self.after:
                    self.names = items[i + 1:]
                    break
            else:
                self.names = ()
        else:
            self.names = items

    def get_items(self):
        items, prev, next, bcount, acount = IDBuilder.get_items(self)
        if prev:
            prev = prev._id
        if next:
            next = next._id
        return (items, prev, next, bcount, acount)


class SearchBuilder(IDBuilder):
    def __init__(self, query, wrap=Wrapped, keep_fn=None, skip=False,
                 skip_deleted_authors=True, **kw):
        IDBuilder.__init__(self, query, wrap, keep_fn, skip, **kw)
        self.skip_deleted_authors = skip_deleted_authors
    def init_query(self):
        self.skip = True

        self.start_time = time.time()

        self.results = self.query.run()
        names = list(self.results.docs)
        self.total_num = self.results.hits

        after = self.after._fullname if self.after else None

        self.names = self._get_after(names,
                                     after,
                                     self.reverse)

    def keep_item(self,item):
        # doesn't use the default keep_item because we want to keep
        # things that were voted on, even if they've chosen to hide
        # them in normal listings
        # TODO: Consider a flag to disable this (and see listingcontroller.py)
        if item._spam or item._deleted:
            return False
        # If checking (wrapped) links, filter out banned subreddits
        elif hasattr(item, 'subreddit') and item.subreddit.spammy():
            return False
        elif (self.skip_deleted_authors and
              getattr(item, "author", None) and item.author._deleted):
            return False
        else:
            return True

class WikiRevisionBuilder(QueryBuilder):
    show_extended = True
    
    def __init__(self, *k, **kw):
        self.user = kw.pop('user', None)
        self.sr = kw.pop('sr', None)
        QueryBuilder.__init__(self, *k, **kw)
    
    def wrap_items(self, items):
        types = {}
        wrapped = []
        for item in items:
            w = self.wrap(item)
            w.show_extended = self.show_extended
            types.setdefault(w.render_class, []).append(w)
            wrapped.append(w)
        
        user = c.user
        for cls in types.keys():
            cls.add_props(user, types[cls])

        return wrapped
    
    def keep_item(self, item):
        from r2.lib.validator.wiki import may_view
        return ((not item.is_hidden) and
                may_view(self.sr, self.user, item.wikipage))

class WikiRecentRevisionBuilder(WikiRevisionBuilder):
    show_extended = False
    
    def must_skip(self, item):
        return (datetime.datetime.now(g.tz) - item.date).days >= wiki.WIKI_RECENT_DAYS
        

def empty_listing(*things):
    parent_name = None
    for t in things:
        try:
            parent_name = t.parent_name
            break
        except AttributeError:
            continue
    l = Listing(None, None, parent_name = parent_name)
    l.things = list(things)
    return Wrapped(l)

def make_wrapper(parent_wrapper = Wrapped, **params):
    def wrapper_fn(thing):
        w = parent_wrapper(thing)
        for k, v in params.iteritems():
            setattr(w, k, v)
        return w
    return wrapper_fn

from _builder import _CommentBuilder, _MessageBuilder

class CommentBuilder(_CommentBuilder):
    def item_iter(self, a):
        for i in a:
            yield i
            if hasattr(i, 'child'):
                for j in self.item_iter(i.child.things):
                    yield j

class MessageBuilder(_MessageBuilder):
    def item_iter(self, a):
        for i in a[0]:
            yield i
            if hasattr(i, 'child'):
                for j in i.child.things:
                    yield j

class ModeratorMessageBuilder(MessageBuilder):
    def __init__(self, user, **kw):
        self.user = user
        MessageBuilder.__init__(self, **kw)

    def get_tree(self):
        if self.parent:
            return conversation(self.user, self.parent)
        sr_ids = Subreddit.reverse_moderator_ids(self.user)
        return moderator_messages(sr_ids)

class MultiredditMessageBuilder(MessageBuilder):
    def __init__(self, user, **kw):
        self.user = user
        MessageBuilder.__init__(self, **kw)

    def get_tree(self):
        if self.parent:
            return conversation(self.user, self.parent)
        return moderator_messages(c.site.sr_ids)

class TopCommentBuilder(CommentBuilder):
    """A comment builder to fetch only the top-level, non-spam,
       non-deleted comments"""
    def __init__(self, link, sort, wrap = Wrapped):
        CommentBuilder.__init__(self, link, sort,
                                load_more = False,
                                continue_this_thread = False,
                                max_depth = 1, wrap = wrap)

    def get_items(self, num = 10):
        final = CommentBuilder.get_items(self, num = num)
        return [ cm for cm in final if not cm.deleted ]

class SrMessageBuilder(MessageBuilder):
    def __init__(self, sr, **kw):
        self.sr = sr
        MessageBuilder.__init__(self, **kw)

    def get_tree(self):
        if self.parent:
            return sr_conversation(self.sr, self.parent)
        return subreddit_messages(self.sr)

class UserMessageBuilder(MessageBuilder):
    def __init__(self, user, **kw):
        self.user = user
        MessageBuilder.__init__(self, **kw)

    def get_tree(self):
        if self.parent:
            return conversation(self.user, self.parent)
        return user_messages(self.user)

