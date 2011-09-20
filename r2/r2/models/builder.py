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
from account import *
from link import *
from vote import *
from report import *
from listing import Listing
from pylons import g
from pylons.i18n import _

import subreddit

from r2.lib.comment_tree import moderator_messages, sr_conversation, conversation
from r2.lib.comment_tree import user_messages, subreddit_messages

from r2.lib.wrapped import Wrapped
from r2.lib import utils
from r2.lib.db import operators
from r2.lib.filters import _force_unicode
from copy import deepcopy

import time
from admintools import compute_votes, admintools, ip_span

EXTRA_FACTOR = 1.5
MAX_RECURSION = 10

class Builder(object):
    def __init__(self, wrap = Wrapped, keep_fn = None, stale = True):
        self.stale = stale
        self.wrap = wrap
        self.keep_fn = keep_fn

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
        email_attrses = {}
        friend_rels = None
        if aids:
            authors = Account._byID(aids, data=True, stale=self.stale) if aids else {}
            cup_infos = Account.cup_info_multi(aids)
            if c.user_is_admin:
                email_attrses = admintools.email_attrs(aids, return_dict=True)
            if user and user.gold:
                friend_rels = user.friend_rels()

        subreddits = Subreddit.load_subreddits(items, stale=self.stale)

        if not user:
            can_ban_set = set()
        else:
            can_ban_set = set(id for (id,sr) in subreddits.iteritems()
                              if sr.can_ban(user))

        #get likes/dislikes
        likes = queries.get_likes(user, items)
        uid = user._id if user else None

        types = {}
        wrapped = []
        count = 0

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

            if False and w.author and c.user_is_admin:
                for attr in email_attrses[w.author._id]:
                    add_attr(w.attribs, attr[2], label=attr[1])

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

            w.rowstyle = getattr(w, 'rowstyle', "")
            w.rowstyle += ' ' + ('even' if (count % 2) else 'odd')

            count += 1

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
            w.reveal_trial_info = False
            w.use_big_modbuttons = False

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
                    w.use_big_modbuttons = True
                    if getattr(w, "author", None) and w.author._spam:
                        w.show_spam = "author"

                elif getattr(item, 'reported', 0) > 0:
                    w.show_reports = True
                    w.use_big_modbuttons = True


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

class QueryBuilder(Builder):
    def __init__(self, query, wrap = Wrapped, keep_fn = None,
                 skip = False, **kw):
        Builder.__init__(self, wrap, keep_fn)
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

        #for prewrap
        orig_items = {}

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

            #pre-wrap
            if self.prewrap_fn:
                new_items2 = []
                for i in new_items:
                    new = self.prewrap_fn(i)
                    orig_items[new._id] = i
                    new_items2.append(new)
                new_items = new_items2

            #wrap
            if self.wrap:
                new_items = self.wrap_items(new_items)

            #skip and count
            while new_items and (not self.num or num_have < self.num):
                i = new_items.pop(0)

                if not (self.must_skip(i) or self.skip and not self.keep_item(i)):
                    items.append(i)
                    num_have += 1
                    if self.wrap:
                        count = count - 1 if self.reverse else count + 1
                        i.num = count
                last_item = i
        
            #unprewrap the last item
            if self.prewrap_fn and last_item:
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
        new_items = Thing._by_fullname(new_names, data = True, return_dict=False, stale=self.stale)
        return done, new_items

class SearchBuilder(IDBuilder):
    def init_query(self):
        self.skip = True

        self.start_time = time.time()

        search = self.query.run()
        names = list(search.docs)
        self.total_num = search.hits

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
        else:
            return True

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
        return moderator_messages(self.user)


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

