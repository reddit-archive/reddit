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
"""
Module for maintaining long or commonly used translatable strings,
removing the need to pollute the code with lots of extra _ and
ungettext calls.  Also provides a capacity for generating a list of
random strings which can be different in each language, though the
hooks to the UI are the same.
"""

import helpers as h
from pylons.i18n import _, ungettext
import random

__all__ = ['StringHandler', 'strings', 'PluralManager', 'plurals',
           'Score', 'rand_strings']

# here's where all of the really long site strings (that need to be
# translated) live so as not to clutter up the rest of the code.  This
# dictionary is not used directly but rather is managed by the single
# StringHandler instance strings
string_dict = dict(

    banned_by = "banned by %s",
    banned    = "banned",
    reports   = "reports: %d",
    
    # this accomodates asian languages which don't use spaces
    number_label = _("%d %s"),

    # this accomodates asian languages which don't use spaces
    float_label = _("%5.3f %s"),

    # this is for Japanese which treats people counds differently
    person_label = _("%(num)d %(persons)s"),

    firsttext = _("reddit is a source for what's new and popular online. vote on links that you like or dislike and help decide what's popular, or submit your own!"),

    already_submitted = _("that link has already been submitted, but you can try to [submit it again](%s)."),

    multiple_submitted = _("that link has been submitted to multiple reddits. you can try to [submit it again](%s)."),

    user_deleted = _("your account has been deleted, but we won't judge you for it."),

    cover_msg      = _("you'll need to login or register to do that"),
    cover_disclaim = _("(don't worry, it only takes a few seconds)"),

    legal = _("I understand and agree that registration on or use of this site constitutes agreement to its %(user_agreement)s and %(privacy_policy)s."),
    
    friends = _('to view reddit with only submissions from your friends, use [reddit.com/r/friends](%s)'),

    msg_add_friend = dict(
        friend = None,
        moderator = _("you have been added as a moderator to [%(title)s](%(url)s)."),
        contributor = _("you have been added as a contributor to [%(title)s](%(url)s)."),
        banned = _("you have been banned from posting to [%(title)s](%(url)s).")
        ),

    subj_add_friend = dict(
        friend = None,
        moderator = _("you are a moderator"),
        contributor = _("you are a contributor"),
        banned = _("you've been banned")
        ),
    
    sr_messages = dict(
        empty =  _('you have not subscribed to any reddits.'),
        subscriber =  _('below are the reddits you have subscribed to'),
        contributor =  _('below are the reddits that you have contributor access to.'),
        moderator = _('below are the reddits that you have moderator access to.')
        ),
    
    sr_subscribe =  _('click the checkbox next to a reddit to subscribe')
)

class StringHandler(object):
    """Class for managing long translatable strings.  Allows accessing
    of strings via both getitem and getattr.  In both cases, the
    string is passed through the gettext _ function before being
    returned."""
    def __init__(self, **sdict):
        self.string_dict = sdict

    def __getitem__(self, attr):
        try:
            return self.__getattr__(attr)
        except AttributeError:
            raise KeyError
    
    def __getattr__(self, attr):
        rval = self.string_dict[attr]
        if isinstance(rval, (str, unicode)):
            return _(rval)
        elif isinstance(rval, dict):
            return dict((k, _(v)) for k, v in rval.iteritems())
        else:
            raise AttributeError

strings = StringHandler(**string_dict)


def P_(x, y):
    """Convenience method for handling pluralizations.  This identity
    function has been added to the list of keyword functions for babel
    in setup.cfg so that the arguments are translated without having
    to resort to ungettext and _ trickery."""
    return (x, y)

class PluralManager(object):
    """String handler for dealing with pluralizable forms.  plurals
    are passed in in pairs (sing, pl) and can be accessed via
    self.sing and self.pl.

    Additionally, calling self.N_sing(n) (or self.N_pl(n)) (where
    'sing' and 'pl' are placeholders for a (sing, pl) pairing) is
    equivalent to ungettext(sing, pl, n)
    """
    def __init__(self, plurals):
        self.string_dict = {}
        for s, p in plurals:
            self.string_dict[s] = self.string_dict[p] = (s, p)

    def __getattr__(self, attr):
        if attr.startswith("N_"):
            a = attr[2:]
            rval = self.string_dict[a]
            return lambda x: ungettext(rval[0], rval[1], x)
        else:
            rval = self.string_dict[attr]
            n = 1 if attr == rval[0] else 5
            return ungettext(rval[0], rval[1], n)

plurals = PluralManager([P_("comment",     "comments"),
                         P_("point",       "points"),
                         
                         # things
                         P_("link",        "links"),
                         P_("comment",     "comments"),
                         P_("message",     "messages"),
                         P_("subreddit",   "subreddits"),
                         
                         # people
                         P_("subscriber",  "subscribers"),
                         P_("contributor", "contributors"),
                         P_("moderator",   "moderators"),
                         
                         # time words
                         P_("milliseconds","milliseconds"),
                         P_("second",      "seconds"),
                         P_("minute",      "minutes"),
                         P_("hour",        "hours"),
                         P_("day",         "days"),
                         P_("month",       "months"),
                         P_("year",        "years"),
])


class Score(object):
    """Convienience class for populating '10 points' in a traslatible
    fasion, used primarily by the score() method in printable.html"""
    @staticmethod
    def number_only(x):
        return max(x, 0)

    @staticmethod
    def points(x):
        return  strings.number_label % (x, plurals.N_points(x))

    @staticmethod
    def subscribers(x):
        return  strings.person_label % \
            dict(num = x, persons = plurals.N_subscribers(x))

    @staticmethod
    def none(x):
        return ""


def fallback_trans(x):
    """For translating placeholder strings the user should never see
    in raw form, such as 'funny 500 message'.  If the string does not
    translate in the current language, falls back on the 'en'
    translation that we've hopefully already provided"""
    t = _(x)
    if t == x:
        l = h.get_lang()
        h.set_lang('en', graceful_fail = True)
        t = _(x)
        if l and l[0] != 'en':
            h.set_lang(l[0])
    return t

class RandomString(object):
    """class for generating a translatable random string that is one
    of n choices.  The 'description' field passed to the constructor
    is only used to generate labels for the translation interface.

    Unlike other translations, this class is accessed directly by the
    translator classes and side-step babel.extract_messages.
    Untranslated, the strings return are of the form 'description n+1'
    for the nth string.  The user-facing versions of these strings are
    therefore completely determined by their translations."""
    def __init__(self, description, num):
        self.desc = description
        self.num = num
    
    def get(self, quantity = 0):
        """Generates a list of 'quantity' random strings.  If quantity
        < self.num, the entries are guaranteed to be unique."""
        l = []
        possible = []
        for x in range(max(quantity, 1)):
            if not possible:
                possible = range(self.num)
            irand = random.choice(possible)
            possible.remove(irand)
            l.append(fallback_trans(self._trans_string(irand)))

        return l if len(l) > 1 else l[0]

    def _trans_string(self, n):
        """Provides the form of the string that is actually translated by gettext."""
        return "%s %d" % (self.desc, n+1)

    def __iter__(self):
        for i in xrange(self.num):
            yield self._trans_string(i)
                   

class RandomStringManager(object):
    """class for keeping randomized translatable strings organized.
    New strings are added via add, and accessible by either getattr or
    getitem using the short name passed to add."""
    def __init__(self):
        self.strings = {}

    def __getitem__(self, attr):
        return self.strings[attr].get()

    def __getattr__(self, attr):
        try:
            return self[attr]
        except KeyError:
            raise AttributeError

    def get(self, attr, quantity = 0):
        """Convenience method for getting a list of 'quantity' strings
        from the RandomString named 'attr'"""
        return self.strings[attr].get(quantity)

    def add(self, name, description, num):
        """create a new random string accessible by 'name' in the code
        and explained in the translation interface with 'description'."""
        self.strings[name] = RandomString(description, num)

    def __iter__(self):
        """iterator primarily used by r2.lib.translations to fetch the
        list of random strings and to iterate over their names to
        insert them into the resulting .po file for a given language"""
        return self.strings.iteritems()

rand_strings = RandomStringManager()

rand_strings.add('sadmessages',   "Funny 500 page message", 10)
rand_strings.add('create_reddit', "Reason to create a reddit", 20)
