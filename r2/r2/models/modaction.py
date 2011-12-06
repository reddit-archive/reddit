from r2.lib.db import tdb_cassandra
from r2.lib.utils import tup
from r2.models import Account, Subreddit, Link, Printable
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

    _use_db = True
    _connection_pool = 'main'
    _str_props = ('sr_id36', 'mod_id36', 'target_fullname', 'action', 'details', 
                  'description')
    _defaults = {}

    actions = ('banuser', 'unbanuser', 'removelink', 'approvelink', 
               'removecomment', 'approvecomment', 'addmoderator',
               'removemoderator', 'addcontributor', 'removecontributor',
               'editsettings', 'editflair')

    _menu = {'banuser': _('ban user'),
             'unbanuser': _('unban user'),
             'removelink': _('remove post'),
             'approvelink': _('approve post'),
             'removecomment': _('remove comment'),
             'approvecomment': _('approve comment'),
             'addmoderator': _('add moderator'),
             'removemoderator': _('remove moderator'),
             'addcontributor': _('add contributor'),
             'removecontributor': _('remove contributor'),
             'editsettings': _('edit settings'),
             'editflair': _('edit user flair')}

    _text = {'banuser': _('banned'),
             'unbanuser': _('unbanned'),
             'removelink': _('removed post'),
             'approvelink': _('approved post'),
             'removecomment': _('removed comment'),
             'approvecomment': _('approved comment'),                    
             'addmoderator': _('added moderator'),
             'removemoderator': _('removed moderator'),
             'addcontributor': _('added approved contributor'),
             'removecontributor': _('removed approved contributor'),
             'editsettings': _('edited settings'),
             'editflair': _('edited user flair')}

    _details_text = {# removemoderator
                     'remove_self': _('removed self'),
                     # editsettings
                     'title': _('title'),
                     'description': _('description'),
                     'lang': _('language'),
                     'type': _('type'),
                     'link_type': _('link type'),
                     'over_18': _('toggle viewers must be over 18'),
                     'allow_top': _('toggle allow in default set'),
                     'show_media': _('toggle show thumbnail images of content'),
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
                     'flair_position': _('toggle flair position'),
                     'flair_self_enabled': _('toggle user assigned flair enabled'),
                     'flair_template': _('add/edit flair templates'),
                     'flair_delete_template': _('delete flair template'),
                     'flair_clear_template': _('clear flair templates')}

    # This stuff won't change
    cache_ignore = set(['subreddit']).union(Printable.cache_ignore)

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
    def get_actions(cls, sr, mod=None, action=None, after=None, reverse=False, count=1000):
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

        if not mod and not action:
            rowkey = sr._id36
            q = ModActionBySR.query(rowkey, after=after, reverse=reverse, count=count)
        elif mod and not action:
            rowkey = '%s_%s' % (sr._id36, mod._id36)
            q = ModActionBySRMod.query(rowkey, after=after, reverse=reverse, count=count)
        elif not mod and action:
            rowkey = '%s_%s' % (sr._id36, action)
            q = ModActionBySRAction.query(rowkey, after=after, reverse=reverse, count=count)
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

    @classmethod
    def add_props(cls, user, wrapped):

        from r2.lib.menus import NavButton
        from r2.lib.db.thing import Thing
        from r2.lib.pages import WrappedUser, SimpleLinkDisplay

        request_path = request.path

        target_fullnames = [item.target_fullname for item in wrapped if hasattr(item, 'target_fullname')]
        targets = Thing._by_fullname(target_fullnames)

        for item in wrapped:
            # Can I move these buttons somewhere else? Does it make sense to do so?
            css_class = 'modactions %s' % item.action
            item.button = NavButton('', item.action, opt='type', css_class=css_class)
            item.button.build(base_path=request_path)

            mod_name = item.author.name
            item.mod = NavButton(mod_name, mod_name, opt='mod')
            item.mod.build(base_path=request_path)
            item.text = ModAction._text.get(item.action, '')
            item.details = item.get_extra_text()

            # Can extend default_thing_wrapper to also lookup the targets
            if hasattr(item, 'target_fullname') and not item.target_fullname == None:
                target = targets[item.target_fullname]
                if isinstance(target, Account):
                    item.target = WrappedUser(target)
                elif isinstance(target, Comment) or isinstance(target, Link):
                    item.target = SimpleLinkDisplay(target)
        
        Printable.add_props(user, wrapped)

class ModActionBySR(tdb_cassandra.View):
    _use_db = True
    _connection_pool = 'main'
    _compare_with = TIME_UUID_TYPE
    _view_of = ModAction
    _ttl = 60*60*24*30*3  # 3 month ttl

    @classmethod
    def _rowkey(cls, ma):
        return ma.sr_id36

class ModActionBySRMod(tdb_cassandra.View):
    _use_db = True
    _connection_pool = 'main'
    _compare_with = TIME_UUID_TYPE
    _view_of = ModAction
    _ttl = 60*60*24*30*3  # 3 month ttl

    @classmethod
    def _rowkey(cls, ma):
        return '%s_%s' % (ma.sr_id36, ma.mod_id36)

class ModActionBySRAction(tdb_cassandra.View):
    _use_db = True
    _connection_pool = 'main'
    _compare_with = TIME_UUID_TYPE
    _view_of = ModAction
    _ttl = 60*60*24*30*3  # 3 month ttl

    @classmethod
    def _rowkey(cls, ma):
        return '%s_%s' % (ma.sr_id36, ma.action)
