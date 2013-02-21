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

from pylons.i18n import _

class PermissionSet(dict):
    ALL = 'all'

    info = None

    def __init__(self, *args, **kwargs):
        super(PermissionSet, self).__init__(*args, **kwargs)

    @classmethod
    def loads(cls, encoded, validate=False):
        if not encoded:
            return cls()
        result = cls(((term[1:], term[0] == '+')
                     for term in encoded.split(',')))
        if result.get(cls.ALL) == False:
            del result[cls.ALL]
        if validate and not result.is_valid():
            raise ValueError
        return result

    def dumps(self):
        if self.is_superuser():
            return '+all'
        return ','.join('-+'[bool(v)] + k for k, v in sorted(self.iteritems()))

    def is_superuser(self):
        return bool(super(PermissionSet, self).get(self.ALL))

    def is_valid(self):
        if not self.info:
            return False
        for k in self:
            if k != self.ALL and k not in self.info:
                return False
        return True

    def get(self, key, default=None):
        if self.info and self.is_superuser():
            return True if key in self.info else default
        return super(PermissionSet, self).get(key, default)

    def __getitem__(self, key):
        if self.info and self.is_superuser():
            return key in self.info
        return super(PermissionSet, self).get(key, False)


class ModeratorPermissionSet(PermissionSet):
    info = dict(
        access=dict(
            title=_('access'),
            description=_('manage the lists of contributors and banned users'),
        ),
        config=dict(
            title=_('config'),
            description=_('edit settings, sidebar, css, and images'),
        ),
        flair=dict(
            title=_('flair'),
            description=_('manage user flair, link flair, and flair templates'),
        ),
        mail=dict(
            title=_('mail'),
            description=_('read and reply to moderator mail'),
        ),
        posts=dict(
            title=_('posts'),
            description=_(
                'use the approve, remove, spam, distinguish, and nsfw buttons'),
        ),
        wiki=dict(
            title=_('wiki'),
            description=_('manage the wiki and access to the wiki'),
        ),
    )

    @classmethod
    def loads(cls, encoded, **kwargs):
        if encoded is None:
            return cls(all=True)
        return super(ModeratorPermissionSet, cls).loads(encoded, **kwargs)
