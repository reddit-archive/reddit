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
# All portions of the code written by reddit are Copyright (c) 2006-2012 reddit
# Inc. All Rights Reserved.
###############################################################################

from os import urandom
from base64 import urlsafe_b64encode

from pycassa.system_manager import ASCII_TYPE, DATE_TYPE, UTF8_TYPE

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
        """Returns a (possibly empty) list of client-scope pairs for which Account has outstanding access tokens."""

        client_ids = set()
        client_id_to_scope = {}
        for token in OAuth2AccessToken._by_user(account):
            if token.check_valid():
                client_id_to_scope.setdefault(token.client_id, set()).update(
                    token.scope_list)

        clients = cls._byID(client_id_to_scope.keys())
        return [(client, list(client_id_to_scope.get(client_id, [])))
                for client_id, client in clients.iteritems()]

    def revoke(self, account):
        """Revoke all of the outstanding OAuth2AccessTokens associated with this client and user Account."""

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
    _ttl = 10 * 60
    _defaults = dict(ConsumableToken._defaults.items() + [
                         ("client_id", ""),
                         ("redirect_uri", ""),
                         ("scope", ""),
                     ]
                )
    _int_props = ("user_id",)
    _warn_on_partial_ttl = False
    _use_db = True
    _connection_pool = "main"

    @classmethod
    def _new(cls, client_id, redirect_uri, user_id, scope_list):
        scope = ','.join(scope_list)
        return super(OAuth2AuthorizationCode, cls)._new(
                client_id=client_id,
                redirect_uri=redirect_uri,
                user_id=user_id,
                scope=scope)

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
    _ttl = 10 * 60
    _defaults = dict(scope="",
                     token_type="bearer",
                    )
    _use_db = True
    _connection_pool = "main"

    @classmethod
    def _new(cls, client_id, user_id, scope):
        return super(OAuth2AccessToken, cls)._new(
                     client_id=client_id,
                     user_id=user_id,
                     scope=scope)

    def _on_create(self):
        """Updates the OAuth2AccessTokensByUser index upon creation."""

        OAuth2AccessTokensByUser._set_values(str(self.user_id), {self._id: ''})
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
            if account._deleted or account._spam:
                raise NotFound
        except NotFound:
            return False

        return True

    def revoke(self):
        """Revokes (invalidates) this access token."""

        self.revoked = True
        self._commit()

        try:
            tba = OAuth2AccessTokensByUser._byID(self.user_id)
            del tba[self._id]
        except (tdb_cassandra.NotFound, KeyError):
            # Not fatal, since self.check_valid() will still be False.
            pass
        else:
            tba._commit()

    @classmethod
    def _by_user(cls, account):
        """Returns a (possibly empty) list of valid access tokens for a given user Account."""

        try:
            tba = OAuth2AccessTokensByUser._byID(account._id36)
        except tdb_cassandra.NotFound:
            return []

        tokens = cls._byID(tba._values().keys())
        return [token for token in tokens.itervalues() if token.check_valid()]

    @property
    def scope_list(self):
        return self.scope.split(',')

class OAuth2AccessTokensByUser(tdb_cassandra.View):
    """Index listing the outstanding access tokens for an account."""

    _use_db = True
    _ttl = OAuth2AccessToken._ttl
    _type_prefix = 'OAuth2AccessTokensByUser'
    _view_of = OAuth2AccessToken
    _connection_pool = 'main'

class EmailVerificationToken(ConsumableToken):
    _use_db = True
    _connection_pool = "main"
    _ttl = 60 * 60 * 12
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
    _ttl = 60 * 60 * 12
    token_size = 20

    @classmethod
    def _new(cls, user):
        return super(PasswordResetToken, cls)._new(user_id=user._fullname,
                                                   email_address=user.email,
                                                   password=user.password)

    def valid_for_user(self, user):
        return (self.email_address == user.email and
                self.password == user.password)
