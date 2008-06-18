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
from r2.lib.utils import Storage
from pylons.i18n import _
from copy import copy

error_list = dict((
        ('NO_URL', _('url required')),
        ('BAD_URL', _('you should check that url')),
        ('NO_TITLE', _('title required')),
        ('TITLE_TOO_LONG', _('you can be more succinct than that')),
        ('COMMENT_TOO_LONG', _('you can be more succinct than that')),
        ('BAD_CAPTCHA', _('your letters stink')),
        ('BAD_USERNAME', _('invalid user name')),
        ('USERNAME_TAKEN', _('that username is already taken')),
        ('NO_THING_ID', _('id not specified')),
        ('NOT_AUTHOR', _("you can't do that")),
        ('BAD_COMMENT', _('please enter a comment')),
        ('BAD_PASSWORD', _('invalid password')),
        ('WRONG_PASSWORD', _('invalid password')),
        ('BAD_PASSWORD_MATCH', _('passwords do not match')),
        ('NO_NAME', _('please enter a name')),
        ('NO_EMAIL', _('please enter an email address')),
        ('NO_EMAIL_FOR_USER', _('no email address for that user')),
        ('NO_MESSAGE', _('please enter a message')),
        ('NO_TO_ADDRESS', _('send it to whom?')),
        ('NO_MSG_BODY', _('please enter a message')),
        ('NO_SUBJECT', _('please enter a subject')),
        ('USER_DOESNT_EXIST', _("that user doesn't exist")),
        ('NO_USER', _('please enter a username')),
        ('INVALID_PREF', "that preference isn't valid"),
        ('BAD_NUMBER', _("that number isn't in the right range")),
        ('ALREADY_SUB', _("that link has already been submitted")),
        ('SUBREDDIT_EXISTS', _('that subreddit already exists')),
        ('BAD_SR_NAME', _('that name isn\'t going to work')),
        ('RATELIMIT', _('you are trying to submit too fast. try again in %(time)s.')),
        ('EXPIRED', _('your session has expired')),
        ('DRACONIAN', _('you must accept the terms first')),
        ('BANNED_IP', "IP banned"),
        ('BANNED_DOMAIN', "Domain banned"),
        ('INVALID_SUBREDDIT_TYPE', _('that option is not valid')),
        ('DESC_TOO_LONG', _('description is too long')),
        ('CHEATER', 'what do you think you\'re doing there?'),
    ))
errors = Storage([(e, e) for e in error_list.keys()])

class Error(object):
    #__slots__ = ('name', 'message')
    def __init__(self, name, i18n_message, msg_params):
        self.name = name
        self.i18n_message = i18n_message
        self.msg_params = msg_params
        
    @property
    def message(self):
        return _(self.i18n_message) % self.msg_params

    def __iter__(self):
         #yield ('num', self.num)
        yield ('name', self.name)
        yield ('message', _(self.message))

    def __repr__(self):
        return '<Error: %s>' % self.name

class ErrorSet(object):
    def __init__(self):
        self.errors = {}

    def __contains__(self, error_name):
        return self.errors.has_key(error_name)

    def __getitem__(self, name):
        return self.errors[name]
        
    def add(self, error_name, msg_params = {}):
        msg = error_list[error_name]
        self.errors[error_name] = Error(error_name, msg, msg_params)

    def remove(self, error_name):
        if self.errors.has_key(error_name):
            del self.errors[error_name]
