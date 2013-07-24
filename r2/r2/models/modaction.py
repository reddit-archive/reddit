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

from datetime import timedelta
import itertools

from r2.lib.db import tdb_cassandra
from r2.lib.utils import tup
from r2.models import Account, Subreddit, Link, Comment, Printable
from r2.models.subreddit import DefaultSR
from pycassa.system_manager import TIME_UUID_TYPE
from uuid import UUID
from pylons.i18n import _
from pylons import request

class ModAction(tdb_cassandra.UuidThing, Printable):
    """
    Columns:
    sr_id - Subreddit id36
    mod_id - Account id36 of moderator
    action - specific name of action, must be in ModAction.actions
    target_fullname - optional fullname of the target of the action
    details - subcategory available for some actions, must show up in 
    description - optional user
    """

    _read_consistency_level = tdb_cassandra.CL.ONE
    _use_db = True
    _connection_pool = 'main'
    _str_props = ('sr_id36', 'mod_id36', 'target_fullname', 'action', 'details', 
                  'description')
    _defaults = {}

    actions = ('banuser', 'unbanuser', 'removelink', 'approvelink', 
               'removecomment', 'approvecomment', 'addmoderator',
               'invitemoderator', 'uninvitemoderator', 'acceptmoderatorinvite',
               'removemoderator', 'addcontributor', 'removecontributor',
               'editsettings', 'editflair', 'distinguish', 'marknsfw', 
               'wikibanned', 'wikicontributor', 'wikiunbanned',
               'removewikicontributor', 'wikirevise', 'wikipermlevel',
               'ignorereports', 'unignorereports', 'setpermissions')

    _menu = {'banuser': _('ban user'),
             'unbanuser': _('unban user'),
             'removelink': _('remove post'),
             'approvelink': _('approve post'),
             'removecomment': _('remove comment'),
             'approvecomment': _('approve comment'),
             'addmoderator': _('add moderator'),
             'removemoderator': _('remove moderator'),
             'invitemoderator': _('invite moderator'),
             'uninvitemoderator': _('uninvite moderator'),
             'acceptmoderatorinvite': _('accept moderator invite'),
             'addcontributor': _('add contributor'),
             'removecontributor': _('remove contributor'),
             'editsettings': _('edit settings'),
             'editflair': _('edit flair'),
             'distinguish': _('distinguish'),
             'marknsfw': _('mark nsfw'),
             'wikibanned': _('ban from wiki'),
             'wikiunbanned': _('unban from wiki'),
             'wikicontributor': _('add wiki contributor'),
             'removewikicontributor': _('remove wiki contributor'),
             'wikirevise': _('wiki revise page'),
             'wikipermlevel': _('wiki page permissions'),
             'ignorereports': _('ignore reports'),
             'unignorereports': _('unignore reports'),
             'setpermissions': _('permissions')}

    _text = {'banuser': _('banned'),
             'wikibanned': _('wiki banned'),
             'wikiunbanned': _('unbanned from wiki'),
             'wikicontributor': _('added wiki contributor'),
             'removewikicontributor': _('removed wiki contributor'),
             'unbanuser': _('unbanned'),
             'removelink': _('removed'),
             'approvelink': _('approved'),
             'removecomment': _('removed'),
             'approvecomment': _('approved'),
             'addmoderator': _('added moderator'),
             'removemoderator': _('removed moderator'),
             'invitemoderator': _('invited moderator'),
             'uninvitemoderator': _('uninvited moderator'),
             'acceptmoderatorinvite': _('accepted moderator invitation'),
             'addcontributor': _('added approved contributor'),
             'removecontributor': _('removed approved contributor'),
             'editsettings': _('edited settings'),
             'editflair': _('edited flair'),
             'wikirevise': _('edited wiki page'),
             'wikipermlevel': _('changed wiki page permission level'),
             'distinguish': _('distinguished'),
             'marknsfw': _('marked nsfw'),
             'ignorereports': _('ignored reports'),
             'unignorereports': _('unignored reports'),
             'setpermissions': _('changed permissions on')}

    _details_text = {# approve comment/link
                     'unspam': _('unspam'),
                     'confirm_ham': _('approved'),
                     # remove comment/link
                     'confirm_spam': _('confirmed spam'),
                     'remove': _('removed not spam'),
                     'spam': _('removed spam'),
                     # removemoderator
                     'remove_self': _('removed self'),
                     # editsettings
                     'title': _('title'),
                     'public_description': _('description'),
                     'description': _('sidebar'),
                     'lang': _('language'),
                     'type': _('type'),
                     'link_type': _('link type'),
                     'submit_link_label': _('submit link button label'),
                     'submit_text_label': _('submit text post button label'),
                     'comment_score_hide_mins': _('comment score hide period'),
                     'over_18': _('toggle viewers must be over 18'),
                     'allow_top': _('toggle allow in default set'),
                     'show_media': _('toggle show thumbnail images of content'),
                     'public_traffic': _('toggle public traffic stats page'),
                     'exclude_banned_modqueue': _('toggle exclude banned users\' posts from modqueue'),
                     'domain': _('domain'),
                     'show_cname_sidebar': _('toggle show sidebar from cname'),
                     'css_on_cname': _('toggle custom CSS from cname'),
                     'header_title': _('header title'),
                     'stylesheet': _('stylesheet'),
                     'del_header': _('delete header image'),
                     'del_image': _('delete image'),
                     'upload_image_header': _('upload header image'),
                     'upload_image': _('upload image'),
                     # editflair
                     'flair_edit': _('add/edit flair'),
                     'flair_delete': _('delete flair'),
                     'flair_csv': _('edit by csv'),
                     'flair_enabled': _('toggle flair enabled'),
                     'flair_position': _('toggle user flair position'),
                     'link_flair_position': _('toggle link flair position'),
                     'flair_self_enabled': _('toggle user assigned flair enabled'),
                     'link_flair_self_enabled': _('toggle submitter assigned link flair enabled'),
                     'flair_template': _('add/edit flair templates'),
                     'flair_delete_template': _('delete flair template'),
                     'flair_clear_template': _('clear flair templates'),
                     # distinguish/nsfw
                     'remove': _('remove'),
                     'ignore_reports': _('ignore reports'),
                     # permissions
                     'permission_moderator': _('set permissions on moderator'),
                     'permission_moderator_invite': _('set permissions on moderator invitation')}

    # This stuff won't change
    cache_ignore = set(['subreddit', 'target']).union(Printable.cache_ignore)

    # Thing properties for Printable
    @property
    def author_id(self):
        return int(self.mod_id36, 36)

    @property
    def sr_id(self):
        return int(self.sr_id36, 36)

    @property
    def _ups(self):
        return 0

    @property
    def _downs(self):
        return 0

    @property
    def _deleted(self):
        return False

    @property
    def _spam(self):
        return False

    @property
    def reported(self):
        return False

    @classmethod
    def create(cls, sr, mod, action, details=None, target=None, description=None):
        # Split this off into separate function to check for valid actions?
        if not action in cls.actions:
            raise ValueError("Invalid ModAction: %s" % action)
        
        # Front page should insert modactions into the base sr
        sr = sr._base if isinstance(sr, DefaultSR) else sr
        
        kw = dict(sr_id36=sr._id36, mod_id36=mod._id36, action=action)

        if target:
            kw['target_fullname'] = target._fullname
        if details:
            kw['details'] = details
        if description:
            kw['description'] = description

        ma = cls(**kw)
        ma._commit()
        return ma

    def _on_create(self):
        """
        Update all Views.
        """

        views = (ModActionBySR, ModActionBySRMod, ModActionBySRAction)

        for v in views:
            v.add_object(self)

    @classmethod
    def get_actions(cls, srs, mod=None, action=None, after=None, reverse=False, count=1000):
        """
        Get a ColumnQuery that yields ModAction objects according to
        specified criteria.
        """
        if after and isinstance(after, basestring):
            after = cls._byID(UUID(after))
        elif after and isinstance(after, UUID):
            after = cls._byID(after)

        if not isinstance(after, cls):
            after = None

        srs = tup(srs)

        if not mod and not action:
            rowkeys = [sr._id36 for sr in srs]
            q = ModActionBySR.query(rowkeys, after=after, reverse=reverse, count=count)
        elif mod and not action:
            mods = tup(mod)
            rowkeys = itertools.product([sr._id36 for sr in srs],
                [mod._id36 for mod in mods])
            rowkeys = ['%s_%s' % (sr, mod) for sr, mod in rowkeys]
            q = ModActionBySRMod.query(rowkeys, after=after, reverse=reverse, count=count)
        elif not mod and action:
            rowkeys = ['%s_%s' % (sr._id36, action) for sr in srs]
            q = ModActionBySRAction.query(rowkeys, after=after, reverse=reverse, count=count)
        else:
            raise NotImplementedError("Can't query by both mod and action")

        return q

    def get_extra_text(self):
        text = ''
        if hasattr(self, 'details') and not self.details == None:
            text += self._details_text.get(self.details, self.details)
        if hasattr(self, 'description') and not self.description == None:
            text += ' %s' % self.description
        return text

    @staticmethod
    def get_rgb(i, fade=0.8):
        r = int(256 - (hash(str(i)) % 256)*(1-fade))
        g = int(256 - (hash(str(i) + ' ') % 256)*(1-fade))
        b = int(256 - (hash(str(i) + '  ') % 256)*(1-fade))
        return (r, g, b)

    @classmethod
    def add_props(cls, user, wrapped):

        from r2.lib.menus import NavButton
        from r2.lib.db.thing import Thing
        from r2.lib.pages import WrappedUser
        from r2.lib.filters import _force_unicode

        TITLE_MAX_WIDTH = 50

        request_path = request.path

        target_fullnames = [item.target_fullname for item in wrapped if hasattr(item, 'target_fullname')]
        targets = Thing._by_fullname(target_fullnames, data=True)
        authors = Account._byID([t.author_id for t in targets.values() if hasattr(t, 'author_id')], data=True)
        links = Link._byID([t.link_id for t in targets.values() if hasattr(t, 'link_id')], data=True)

        sr_ids = set([t.sr_id for t in targets.itervalues() if hasattr(t, 'sr_id')] +
                     [w.sr_id for w in wrapped])
        subreddits = Subreddit._byID(sr_ids, data=True)

        # Assemble target links
        target_links = {}
        target_accounts = {}
        for fullname, target in targets.iteritems():
            if isinstance(target, Link):
                author = authors[target.author_id]
                title = _force_unicode(target.title)
                if len(title) > TITLE_MAX_WIDTH:
                    short_title = title[:TITLE_MAX_WIDTH] + '...'
                else:
                    short_title = title
                text = '%(link)s "%(title)s" %(by)s %(author)s' % {
                        'link': _('link'),
                        'title': short_title, 
                        'by': _('by'),
                        'author': author.name}
                path = target.make_permalink(subreddits[target.sr_id])
                target_links[fullname] = (text, path, title)
            elif isinstance(target, Comment):
                author = authors[target.author_id]
                link = links[target.link_id]
                title = _force_unicode(link.title)
                if len(title) > TITLE_MAX_WIDTH:
                    short_title = title[:TITLE_MAX_WIDTH] + '...'
                else:
                    short_title = title
                text = '%(comment)s %(by)s %(author)s %(on)s "%(title)s"' % {
                        'comment': _('comment'),
                        'by': _('by'),
                        'author': author.name,
                        'on': _('on'),
                        'title': short_title}
                path = target.make_permalink(link, subreddits[link.sr_id])
                target_links[fullname] = (text, path, title)
            elif isinstance(target, Account):
                target_accounts[fullname] = WrappedUser(target)

        for item in wrapped:
            # Can I move these buttons somewhere else? Not great to have request stuff in here
            css_class = 'modactions %s' % item.action
            item.button = NavButton('', item.action, opt='type', css_class=css_class)
            item.button.build(base_path=request_path)

            mod_name = item.author.name
            item.mod = NavButton(mod_name, mod_name, opt='mod')
            item.mod.build(base_path=request_path)
            item.text = ModAction._text.get(item.action, '')
            item.details = item.get_extra_text()

            if hasattr(item, 'target_fullname') and item.target_fullname:
                target = targets[item.target_fullname]
                if isinstance(target, Account):
                    item.target_wrapped_user = target_accounts[item.target_fullname]
                elif isinstance(target, Link) or isinstance(target, Comment):
                    item.target_text, item.target_path, item.target_title = target_links[item.target_fullname]

            item.bgcolor = ModAction.get_rgb(item.sr_id)
            item.sr_name = subreddits[item.sr_id].name
            item.sr_path = subreddits[item.sr_id].path

        Printable.add_props(user, wrapped)

class ModActionBySR(tdb_cassandra.View):
    _use_db = True
    _connection_pool = 'main'
    _compare_with = TIME_UUID_TYPE
    _view_of = ModAction
    _ttl = timedelta(days=90)
    _read_consistency_level = tdb_cassandra.CL.ONE

    @classmethod
    def _rowkey(cls, ma):
        return ma.sr_id36

class ModActionBySRMod(tdb_cassandra.View):
    _use_db = True
    _connection_pool = 'main'
    _compare_with = TIME_UUID_TYPE
    _view_of = ModAction
    _ttl = timedelta(days=90)
    _read_consistency_level = tdb_cassandra.CL.ONE

    @classmethod
    def _rowkey(cls, ma):
        return '%s_%s' % (ma.sr_id36, ma.mod_id36)

class ModActionBySRAction(tdb_cassandra.View):
    _use_db = True
    _connection_pool = 'main'
    _compare_with = TIME_UUID_TYPE
    _view_of = ModAction
    _ttl = timedelta(days=90)
    _read_consistency_level = tdb_cassandra.CL.ONE

    @classmethod
    def _rowkey(cls, ma):
        return '%s_%s' % (ma.sr_id36, ma.action)
