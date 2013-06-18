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

import datetime
from os import urandom
from base64 import urlsafe_b64encode

from pycassa.system_manager import ASCII_TYPE, DATE_TYPE, UTF8_TYPE

from pylons import g
from pylons.i18n import _

from r2.lib.db import tdb_cassandra
from r2.lib.db.thing import NotFound
from r2.models.account import Account

def generate_token(size):
    return urlsafe_b64encode(urandom(size)).rstrip("=")


class Token(tdb_cassandra.Thing):
    """A unique randomly-generated token used for authentication."""

    _extra_schema_creation_args = dict(
        key_validation_class=ASCII_TYPE,
        default_validation_class=UTF8_TYPE,
        column_validation_classes=dict(
            date=DATE_TYPE,
            used=ASCII_TYPE
        )
    )

    @classmethod
    def _new(cls, **kwargs):
        if "_id" not in kwargs:
            kwargs["_id"] = cls._generate_unique_token()

        token = cls(**kwargs)
        token._commit()
        return token

    @classmethod
    def _generate_unique_token(cls):
        for i in range(3):
            token = generate_token(cls.token_size)
            try:
                cls._byID(token)
            except tdb_cassandra.NotFound:
                return token
            else:
                continue
        raise ValueError

    @classmethod
    def get_token(cls, _id):
        if _id is None:
            return None
        try:
            return cls._byID(_id)
        except tdb_cassandra.NotFound:
            return None


class ConsumableToken(Token):
    _defaults = dict(used=False)
    _bool_props = ("used",)
    _warn_on_partial_ttl = False

    @classmethod
    def get_token(cls, _id):
        token = super(ConsumableToken, cls).get_token(_id)
        if token and not token.used:
            return token
        else:
            return None

    def consume(self):
        self.used = True
        self._commit()


class OAuth2Scope:
    scope_info = {
        "edit": {
            "id": "edit",
            "name": _("Edit Posts"),
            "description": _("Edit and delete my comments and submissions."),
        },
        "identity": {
            "id": "identity",
            "name": _("My Identity"),
            "description": _("Access my reddit username and signup date."),
        },
        "modflair": {
            "id": "modflair",
            "name": _("Moderate Flair"),
            "description": _(
                "Manage and assign flair in subreddits I moderate."),
        },
        "modposts": {
            "id": "modposts",
            "name": _("Moderate Posts"),
            "description": _(
                "Approve, remove, mark nsfw, and distinguish content"
                " in subreddits I moderate."),
        },
        "modconfig": {
            "id": "modconfig",
            "name": _("Moderate Subreddit Configuration"),
            "description": _(
                "Manage the configuration, sidebar, and CSS"
                " of subreddits I moderate."),
        },
        "modlog": {
            "id": "modlog",
            "name": _("Moderation Log"),
            "description": _(
                "Access the moderation log in subreddits I moderate."),
        },
        "modtraffic": {
            "id": "modtraffic",
            "name": _("Subreddit Traffic"),
            "description": _("Access traffic stats in subreddits I moderate."),
        },
        "mysubreddits": {
            "id": "mysubreddits",
            "name": _("My Subreddits"),
            "description": _(
                "Access the list of subreddits I moderate, contribute to,"
                " and subscribe to."),
        },
        "privatemessages": {
            "id": "privatemessages",
            "name": _("Private Messages"),
            "description": _(
                "Access my inbox and send private messages to other users."),
        },
        "read": {
            "id": "read",
            "name": _("Read Content"),
            "description": _("Access posts and comments through my account."),
        },
        "submit": {
            "id": "submit",
            "name": _("Submit Content"),
            "description": _("Submit links and comments from my account."),
        },
        "subscribe": {
            "id": "subscribe",
            "name": _("Edit My Subscriptions"),
            "description": _("Manage my subreddit subscriptions."),
        },
        "vote": {
            "id": "vote",
            "name": _("Vote"),
            "description":
                _("Submit and change my votes on comments and submissions."),
        },
    }

    def __init__(self, scope_str=None):
        if scope_str:
            self._parse_scope_str(scope_str)
        else:
            self.subreddit_only = False
            self.subreddits = set()
            self.scopes = set()

    def _parse_scope_str(self, scope_str):
        srs, sep, scopes = scope_str.rpartition(':')
        if sep:
            self.subreddit_only = True
            self.subreddits = set(srs.split('+'))
        else:
            self.subreddit_only = False
            self.subreddits = set()
        self.scopes = set(scopes.split(','))

    def __str__(self):
        if self.subreddit_only:
            sr_part = '+'.join(sorted(self.subreddits)) + ':'
        else:
            sr_part = ''
        return sr_part + ','.join(sorted(self.scopes))

    def is_valid(self):
        return all(scope in self.scope_info for scope in self.scopes)

    def details(self):
        return [(scope, self.scope_info[scope]) for scope in self.scopes]


class OAuth2Client(Token):
    """A client registered for OAuth2 access"""
    max_developers = 20
    token_size = 10
    client_secret_size = 20
    _defaults = dict(name="",
                     description="",
                     about_url="",
                     icon_url="",
                     secret="",
                     redirect_uri="",
                    )
    _use_db = True
    _connection_pool = "main"

    _developer_colname_prefix = 'has_developer_'

    @classmethod
    def _new(cls, **kwargs):
        if "secret" not in kwargs:
            kwargs["secret"] = generate_token(cls.client_secret_size)
        return super(OAuth2Client, cls)._new(**kwargs)

    @property
    def _developer_ids(self):
        for k, v in self._t.iteritems():
            if k.startswith(self._developer_colname_prefix) and v:
                try:
                    yield int(k[len(self._developer_colname_prefix):], 36)
                except ValueError:
                    pass

    @property
    def _developers(self):
        """Returns a list of users who are developers of this client."""

        devs = Account._byID(list(self._developer_ids))
        return [dev for dev in devs.itervalues()
                if not (dev._deleted or dev._spam)]

    def _developer_colname(self, account):
        """Developer access is granted by way of adding a column with the
        account's ID36 to the client object.  This function returns the
        column name for a given Account.
        """

        return ''.join((self._developer_colname_prefix, account._id36))

    def has_developer(self, account):
        """Returns a boolean indicating whether or not the supplied Account is a developer of this application."""

        if account._deleted or account._spam:
            return False
        else:
            return getattr(self, self._developer_colname(account), False)

    def add_developer(self, account, force=False):
        """Grants developer access to the supplied Account."""

        dev_ids = set(self._developer_ids)
        if account._id not in dev_ids:
            if not force and len(dev_ids) >= self.max_developers:
                raise OverflowError('max developers reached')
            setattr(self, self._developer_colname(account), True)
            self._commit()

        # Also update index
        OAuth2ClientsByDeveloper._set_values(account._id36, {self._id: ''})

    def remove_developer(self, account):
        """Revokes the supplied Account's developer access."""

        if hasattr(self, self._developer_colname(account)):
            del self[self._developer_colname(account)]
            if not len(self._developers):
                # No developers remain, delete the client
                self.deleted = True
            self._commit()

        # Also update index
        try:
            cba = OAuth2ClientsByDeveloper._byID(account._id36)
            del cba[self._id]
        except (tdb_cassandra.NotFound, KeyError):
            pass
        else:
            cba._commit()

    @classmethod
    def _by_developer(cls, account):
        """Returns a (possibly empty) list of clients for which Account is a developer."""

        if account._deleted or account._spam:
            return []

        try:
            cba = OAuth2ClientsByDeveloper._byID(account._id36)
        except tdb_cassandra.NotFound:
            return []

        clients = cls._byID(cba._values().keys())
        return [client for client in clients.itervalues()
                if not getattr(client, 'deleted', False)
                    and client.has_developer(account)]

    @classmethod
    def _by_user(cls, account):
        """Returns a (possibly empty) list of client-scope-expiration triples for which Account has outstanding access tokens."""

        refresh_tokens = {
            token._id: token for token in OAuth2RefreshToken._by_user(account)
            if token.check_valid()}
        access_tokens = [token for token in OAuth2AccessToken._by_user(account)
                         if token.check_valid()]

        tokens = refresh_tokens.values()
        tokens.extend(token for token in access_tokens
                      if token.refresh_token not in refresh_tokens)

        clients = cls._byID([token.client_id for token in tokens])
        return [(clients[token.client_id], OAuth2Scope(token.scope),
                 token.date + datetime.timedelta(seconds=token._ttl)
                     if token._ttl else None)
                for token in tokens]

    def revoke(self, account):
        """Revoke all of the outstanding OAuth2AccessTokens associated with this client and user Account."""

        for token in OAuth2RefreshToken._by_user(account):
            if token.client_id == self._id:
                token.revoke()
        for token in OAuth2AccessToken._by_user(account):
            if token.client_id == self._id:
                token.revoke()

class OAuth2ClientsByDeveloper(tdb_cassandra.View):
    """Index providing access to the list of OAuth2Clients of which an Account is a developer."""

    _use_db = True
    _type_prefix = 'OAuth2ClientsByDeveloper'
    _view_of = OAuth2Client
    _connection_pool = 'main'


class OAuth2AuthorizationCode(ConsumableToken):
    """An OAuth2 authorization code for completing authorization flow"""
    token_size = 20
    _ttl = datetime.timedelta(minutes=10)
    _defaults = dict(ConsumableToken._defaults.items() + [
                         ("client_id", ""),
                         ("redirect_uri", ""),
                         ("scope", ""),
                         ("refreshable", False)])
    _bool_props = ConsumableToken._bool_props + ("refreshable",)
    _warn_on_partial_ttl = False
    _use_db = True
    _connection_pool = "main"

    @classmethod
    def _new(cls, client_id, redirect_uri, user_id, scope, refreshable):
        return super(OAuth2AuthorizationCode, cls)._new(
                client_id=client_id,
                redirect_uri=redirect_uri,
                user_id=user_id,
                scope=str(scope),
                refreshable=refreshable)

    @classmethod
    def use_token(cls, _id, client_id, redirect_uri):
        token = cls.get_token(_id)
        if token and (token.client_id == client_id and
                      token.redirect_uri == redirect_uri):
            token.consume()
            return token
        else:
            return None


class OAuth2AccessToken(Token):
    """An OAuth2 access token for accessing protected resources"""
    token_size = 20
    _ttl = datetime.timedelta(minutes=60)
    _defaults = dict(scope="",
                     token_type="bearer",
                     refresh_token=None,
                    )
    _use_db = True
    _connection_pool = "main"

    @classmethod
    def _new(cls, client_id, user_id, scope, refresh_token=None):
        return super(OAuth2AccessToken, cls)._new(
                     client_id=client_id,
                     user_id=user_id,
                     scope=str(scope),
                     refresh_token=refresh_token)

    @classmethod
    def _by_user_view(cls):
        return OAuth2AccessTokensByUser

    def _on_create(self):
        """Updates the by-user view upon creation."""

        self._by_user_view()._set_values(str(self.user_id), {self._id: ''})
        return super(OAuth2AccessToken, self)._on_create()

    def check_valid(self):
        """Returns boolean indicating whether or not this access token is still valid."""

        # Has the token been revoked?
        if getattr(self, 'revoked', False):
            return False

        # Is the OAuth2Client still valid?
        try:
            client = OAuth2Client._byID(self.client_id)
            if getattr(client, 'deleted', False):
                raise NotFound
        except NotFound:
            return False

        # Is the user account still valid?
        try:
            account = Account._byID36(self.user_id)
            if account._deleted:
                raise NotFound
        except NotFound:
            return False

        return True

    def revoke(self):
        """Revokes (invalidates) this access token."""

        self.revoked = True
        self._commit()

        try:
            tba = self._by_user_view()._byID(self.user_id)
            del tba[self._id]
        except (tdb_cassandra.NotFound, KeyError):
            # Not fatal, since self.check_valid() will still be False.
            pass
        else:
            tba._commit()

    @classmethod
    def revoke_all_by_user(cls, account):
        """Revokes all access tokens for a given user Account."""
        tokens = cls._by_user(account)
        for token in tokens:
            token.revoke()

    @classmethod
    def _by_user(cls, account):
        """Returns a (possibly empty) list of valid access tokens for a given user Account."""

        try:
            tba = cls._by_user_view()._byID(account._id36)
        except tdb_cassandra.NotFound:
            return []

        tokens = cls._byID(tba._values().keys())
        return [token for token in tokens.itervalues() if token.check_valid()]

class OAuth2AccessTokensByUser(tdb_cassandra.View):
    """Index listing the outstanding access tokens for an account."""

    _use_db = True
    _ttl = OAuth2AccessToken._ttl
    _type_prefix = 'OAuth2AccessTokensByUser'
    _view_of = OAuth2AccessToken
    _connection_pool = 'main'


class OAuth2RefreshToken(OAuth2AccessToken):
    """A refresh token for obtaining new access tokens for the same grant."""

    _type_prefix = None
    _ttl = None

    @classmethod
    def _by_user_view(cls):
        return OAuth2RefreshTokensByUser

class OAuth2RefreshTokensByUser(tdb_cassandra.View):
    """Index listing the outstanding refresh tokens for an account."""

    _use_db = True
    _ttl = OAuth2RefreshToken._ttl
    _type_prefix = 'OAuth2RefreshTokensByUser'
    _view_of = OAuth2RefreshToken
    _connection_pool = 'main'


class EmailVerificationToken(ConsumableToken):
    _use_db = True
    _connection_pool = "main"
    _ttl = datetime.timedelta(hours=12)
    token_size = 20

    @classmethod
    def _new(cls, user):
        return super(EmailVerificationToken, cls)._new(user_id=user._fullname,
                                                       email=user.email)

    def valid_for_user(self, user):
        return self.email == user.email


class PasswordResetToken(ConsumableToken):
    _use_db = True
    _connection_pool = "main"
    _ttl = datetime.timedelta(hours=12)
    token_size = 20

    @classmethod
    def _new(cls, user):
        return super(PasswordResetToken, cls)._new(user_id=user._fullname,
                                                   email_address=user.email,
                                                   password=user.password)

    def valid_for_user(self, user):
        return (self.email_address == user.email and
                self.password == user.password)


class AwardClaimToken(ConsumableToken):
    token_size = 20
    _ttl = datetime.timedelta(days=30)
    _defaults = dict(ConsumableToken._defaults.items() + [
                         ("awardfullname", ""),
                         ("description", ""),
                         ("url", ""),
                         ("uid", "")])
    _use_db = True
    _connection_pool = "main"

    @classmethod
    def _new(cls, uid, award, description, url):
        '''Create an AwardClaimToken with the given parameters

        `uid` - A string that uniquely identifies the kind of
                Trophy the user would be claiming.*
        `award_codename` - The codename of the Award the user will claim
        `description` - The description the Trophy will receive
        `url` - The URL the Trophy will receive

        *Note that this differs from Award codenames, because it may be
        desirable to allow users to have multiple copies of the same Award,
        but restrict another aspect of the Trophy. For example, users
        are allowed to have multiple Translator awards, but should only get
        one for each language, so the `unique_award_id`s for those would be
        of the form "i18n_%(language)s"

        '''
        return super(AwardClaimToken, cls)._new(
            awardfullname=award._fullname,
            description=description or "",
            url=url or "",
            uid=uid,
        )

    def post_url(self):
        # Relative URL; should be used on an on-site form
        return "/awards/claim/%s" % self._id

    def confirm_url(self):
        # Full URL; for emailing, PM'ing, etc.
        return "http://%s/awards/confirm/%s" % (g.domain, self._id)
