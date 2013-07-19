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

"""
Module for maintaining long or commonly used translatable strings,
removing the need to pollute the code with lots of extra _ and
ungettext calls.  Also provides a capacity for generating a list of
random strings which can be different in each language, though the
hooks to the UI are the same.
"""

from pylons import g, c
from pylons.i18n import _, ungettext, get_lang
import random
import babel.numbers

from r2.lib.permissions import ModeratorPermissionSet
from r2.lib.translation import set_lang

__all__ = ['StringHandler', 'strings', 'PluralManager', 'plurals',
           'Score', 'rand_strings']

# here's where all of the really long site strings (that need to be
# translated) live so as not to clutter up the rest of the code.  This
# dictionary is not used directly but rather is managed by the single
# StringHandler instance strings
string_dict = dict(

    banned_by = "removed by %s",
    banned    = "removed",
    reports   = "reports: %d",
    
    submitting = _("submitting..."),

    # this accomodates asian languages which don't use spaces
    number_label = _("%(num)d %(thing)s"),

    # this accomodates asian languages which don't use spaces
    points_label = _("%(num)d %(point)s"),

    # this accomodates asian languages which don't use spaces
    time_label = _("%(num)d %(time)s"),

    # this accomodates asian languages which don't use spaces
    float_label = _("%(num)5.3f %(thing)s"),

    # this is for Japanese which treats people counts differently
    person_label = _("<span class='number'>%(num)s</span>&#32;<span class='word'>%(persons)s</span>"),

    already_submitted = _("that link has already been submitted, but you can try to [submit it again](%s)."),

    multiple_submitted = _("that link has been submitted to multiple subreddits. you can try to [submit it again](%s)."),

    user_deleted = _("your account has been deleted, but we won't judge you for it."),

    cover_msg      = _("you'll need to login or register to do that"),
    cover_disclaim = _("(don't worry, it only takes a few seconds)"),

    oauth_login_msg = _(
        "Log in or register to connect your reddit account with %(app)s."),

    login_fallback_msg = _("try using our secure login form."),

    legal = _("I understand and agree that registration on or use of this site constitutes agreement to its %(user_agreement)s and %(privacy_policy)s."),

    friends = _('to view reddit with only submissions from your friends, use [reddit.com/r/friends](%s)'),

    sr_created = _('your subreddit has been created'),

    more_info_link = _("visit [%(link)s](%(link)s) for more information"),

    sr_messages = dict(
        empty =  _('you have not subscribed to any subreddits.'),
        subscriber =  _('below are the subreddits you have subscribed to'),
        contributor =  _('below are the subreddits that you are an approved submitter on.'),
        moderator = _('below are the subreddits that you have moderator access to.')
        ),

    sr_subscribe =  _('click the `subscribe` or `unsubscribe` buttons to choose which subreddits appear on your front page.'),

    searching_a_reddit = _('you\'re searching within the [%(reddit_name)s](%(reddit_link)s) subreddit. '+
                           'you can also search within [all subreddits](%(all_reddits_link)s)'),

    css_validator_messages = dict(
        broken_url = _('"%(brokenurl)s" is not a valid URL'),
        invalid_property = _('"%(cssprop)s" is not a valid CSS property'),
        invalid_val_for_prop = _('"%(cssvalue)s" is not a valid value for CSS property "%(cssprop)s"'),
        too_big = _('too big. keep it under %(max_size)dkb'),
        max_size = _('max size: %(max_size)dkB'),
        syntax_error = _('syntax error: "%(syntaxerror)s"'),
        no_imports = _('@imports are not allowed'),
        invalid_property_list = _('invalid CSS property list "%(proplist)s"'),
        unknown_rule_type = _('unknown CSS rule type "%(ruletype)s"')
    ),
    permalink_title = _("%(author)s comments on %(title)s"),
    link_info_title = _("%(title)s : %(site)s"),
    banned_subreddit_title = _("this subreddit has been banned"),
    banned_subreddit_message = _("most likely this was done automatically by our spam filtering program. the program is still learning, and may even have some bugs, so if you feel the ban was a mistake, please submit a link to our [request a subreddit listing](%(link)s) and be sure to include the **exact name of the subreddit**."),
    private_subreddit_title = _("this subreddit is private"),
    private_subreddit_message = _("the moderators of this subreddit have set it to private. you must be a moderator or approved submitter to view its contents."),
    comments_panel_text = _("""The following is a sample of what Reddit users had to say about this page. The full discussion is available [here](%(fd_link)s); you can also get there by clicking the link's title (in the middle of the toolbar, to the right of the comments button)."""),

    submit_link = _("""You are submitting a link. The key to a successful submission is interesting content and a descriptive title."""),
    submit_text = _("""You are submitting a text-based post. Speak your mind. A title is required, but expanding further in the text field is not. Beginning your title with "vote up if" is violation of intergalactic law."""),
    submit_link_label = _("Submit a new link"),
    submit_text_label = _("Submit a new text post"),
    compact_suggest = _("Looks like you're browsing on a small screen. Would you like to try [reddit's mobile interface](%(url)s)?"),
    verify_email = _("we're going to need to verify your email address for you to proceed."),
    verify_email_submit = _("you'll be able to submit more frequently once you verify your email address"),
    email_verified =  _("your email address has been verfied"),
    email_verify_failed = _("Verification failed.  Please try that again"),
    search_failed = _("Our search machines are under too much load to handle your request right now. :( Sorry for the inconvenience. Try again in a little bit -- but please don't mash reload; that only makes the problem worse."),
    invalid_search_query = _("I couldn't understand your query, so I simplified it and searched for \"%(clean_query)s\" instead."),
    completely_invalid_search_query = _("I couldn't understand your search query. Please try again."),
    search_help = _("You may also want to check the [search help page](%(search_help)s) for more information."),
    formatting_help_info = _('reddit uses a slightly-customized version of [Markdown](http://daringfireball.net/projects/markdown/syntax) for formatting. See below for some basics, or check [the commenting wiki page](/wiki/commenting) for more detailed help and solutions to common issues.'),
    generic_quota_msg = _("You've submitted too many links recently. Please try again in an hour."),
    verified_quota_msg = _("Looks like you're either a brand new user or your posts have not been doing well recently. You may have to wait a bit to post again. In the meantime feel free to [check out the reddiquette](%(reddiquette)s) or join the conversation in a different thread."),
    unverified_quota_msg = _("Looks like you're either a brand new user or your posts have not been doing well recently. You may have to wait a bit to post again. In the meantime feel free to [check out the reddiquette](%(reddiquette)s), join the conversation in a different thread, or [verify your email address](%(verify)s)."),
    read_only_msg = _("reddit is in \"emergency read-only mode\" right now. :( you won't be able to log in. we're sorry, and are working frantically to fix the problem."),
    heavy_load_msg = _("this page is temporarily in read-only mode due to heavy traffic."),
    gold_benefits_msg = _("Being a reddit gold member gives you access to a bunch of new site features and other benefits. Be sure to check out **[the reddit gold information page](/gold/about)** to see what's currently available, and subscribe to **/r/goldbenefits** to keep up with announcements of new benefits."),
    lounge_msg = _("please grab a drink and join us in [the lounge](%(link)s)."),
    postcard_msg = _("You sent us a postcard! (Or something similar.) When we run out of room on our refrigerator, we might one day auction off the stuff that people sent in. Is it okay if we include your thing?"),
    over_comment_limit = _("Sorry, the maximum number of comments is %(max)d. (However, if you subscribe to reddit gold, it goes up to %(goldmax)d.)"),
    over_comment_limit_gold = _("Sorry, the maximum number of comments is %d."),
    youve_got_gold = _("%(sender)s just sent you %(amount)s of reddit gold! Wasn't that nice?"),
    giftgold_note = _("Here's a note that was included:\n\n----\n\n"),
    youve_got_comment_gold = _("A redditor liked [your comment](%(url)s) so much, they gave you a month of reddit gold. Shiny!"),
    gold_summary_autorenew = _("You're about to set up an ongoing, autorenewing subscription to reddit gold for yourself (%(user)s)."),
    gold_summary_onetime = _("You're about to make a one-time purchase of %(amount)s of reddit gold for yourself (%(user)s)."),
    gold_summary_creddits = _("You're about to purchase %(amount)s of reddit gold creddits. They work like gift certificates: each creddit you have will allow you to give one month of reddit gold to someone else."),
    gold_summary_signed_gift = _("You're about to give %(amount)s of reddit gold to %(recipient)s, who will be told that it came from you."),
    gold_summary_anonymous_gift = _("You're about to give %(amount)s of reddit gold to %(recipient)s. It will be an anonymous gift."),
    gold_summary_comment_gift = _("Want to say thanks to *%(recipient)s* for this comment? Give them a month of [reddit gold](/gold/about)."),
    gold_summary_comment_page = _("Give *%(recipient)s* a month of [reddit gold](/gold/about) for this comment:"),
    gold_partners_description = _('reddit gold members get access to exclusive stuff'),
    unvotable_message = _("sorry, this has been archived and can no longer be voted on"),
    account_activity_blurb = _("This page shows a history of recent activity on your account. If you notice unusual activity, you should change your password immediately. Location information is guessed from your computer's IP address and may be wildly wrong, especially for visits from mobile devices. Note: due to a bug, private-use addresses (starting with 10.) sometimes show up erroneously in this list after regular use of the site."),
    your_current_ip_is = _("You are currently accessing reddit from this IP address: %(address)s."),
    account_activity_apps_blurb = _("""
These apps are authorized to access your account. Logging out of all sessions
will revoke access from all apps. You may also revoke access from individual
apps below.
"""),

    traffic_promoted_link_explanation = _("Below you will see your promotion's impression and click traffic per hour of promotion.  Please note that these traffic totals will lag behind by two to three hours, and that daily totals will be preliminary until 24 hours after the link has finished its run."),
    traffic_processing_slow = _("Traffic processing is currently running slow. The latest data available is from %(date)s. This page will be updated as new data becomes available."),
    traffic_processing_normal = _("Traffic processing occurs on an hourly basis. The latest data available is from %(date)s. This page will be updated as new data becomes available."),
    traffic_help_email = _("Questions? Email self serve support: %(email)s"),

    traffic_subreddit_explanation = _("""
Below are the traffic statistics for your subreddit. Each graph represents one of the following over the interval specified.

* **pageviews** are all hits to %(subreddit)s, including both listing pages and comment pages.
* **uniques** are the total number of unique visitors (determined by a combination of their IP address and User Agent string) that generate the above pageviews. This is independent of whether or not they are logged in.
* **subscriptions** is the number of new subscriptions that have been generated in a given day. This number is less accurate than the first two metrics, as, though we can track new subscriptions, we have no way to track unsubscriptions.

Note: there are a couple of places outside of your subreddit where someone can click "subscribe", so it is possible (though unlikely) that the subscription count can exceed the unique count on a given day.
"""),

    go = _("go"),
    view_subreddit_traffic = _("view subreddit traffic"),

    an_error_occurred = _("an error occurred (status: %(status)s)"),
    an_error_occurred_friendly = _("an error occurred. please try again later! (status: %(status)s)"),
    rate_limit = _("please wait a few seconds and try again."),
    subscribed_multi = _("multireddit of your subscriptions"),
    mod_multi = _("multireddit of subreddits you moderate"),

    r_all_description = _("/r/all displays content from all of reddit, including subreddits you aren't subscribed to."),
    r_all_minus_description = _("Displaying content from /r/all of reddit, except the following subreddits:"),
    all_minus_gold_only = _('Filtering /r/all is a feature only available to [reddit gold](/gold/about) subscribers. Displaying unfiltered results from /r/all.'),

    missing_credit_name = _("missing name"),
    bad_credit_number = _("invalid credit card number"),
    bad_credit_expiry = _("invalid expiration date"),
    bad_credit_cvc = _("invalid cvc"),
    missing_credit_address = _("missing address"),
    missing_credit_city = _("missing city"),
    missing_credit_state = _("missing state or province"),
    missing_credit_country = _("missing country"),
    missing_credit_zip = _("missing zip code"),

    permissions = dict(
        info=dict(
            moderator=ModeratorPermissionSet.info,
            moderator_invite=ModeratorPermissionSet.info,
        ),
        all_msg=_("full permissions"),
        none_msg=_("no permissions"),
    ),
    categorize = _('categorize'),
    are_you_sure = _('are you sure?'),
    yes = _('yes'),
    no = _('no'),
    create_multi = _('create a new multi'),
    awesomeness_goes_here = _('awesomeness goes here'),
    add_multi_sr = _('add a subreddit to your multi.'),
    open_multi = _('open this multi'),
    summarize_and_n_more = _('&hellip; and %(count)s more &rArr;'),
    summarize_less = _('&lArr; less'),
)

class StringHandler(object):
    """Class for managing long translatable strings.  Allows accessing
    of strings via both getitem and getattr.  In both cases, the
    string is passed through the gettext _ function before being
    returned."""
    def __init__(self, **sdict):
        self.string_dict = sdict

    def get(self, attr, default=None):
        try:
            return self[attr]
        except KeyError:
            return default

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
            return StringHandler(**rval)
        else:
            raise AttributeError
    
    def __iter__(self):
        return iter(self.string_dict)

    def keys(self):
        return self.string_dict.keys()

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
        to_func = False
        if attr.startswith("N_"):
            attr = attr[2:]
            to_func = True

        attr = attr.replace("_", " ")
        if to_func:
            rval = self.string_dict[attr]
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
                         P_("creddit",     "creddits"),

                         # people
                         P_("reader",  "readers"),
                         P_("subscriber",  "subscribers"),
                         P_("approved submitter", "approved submitters"),
                         P_("moderator",   "moderators"),
                         P_("user here now",   "users here now"),

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
        return str(max(x, 0))

    @staticmethod
    def points(x):
        return  strings.points_label % dict(num=x, point=plurals.N_points(x))

    @staticmethod
    def safepoints(x):
        return  strings.points_label % dict(num=max(x,0),
                                            point=plurals.N_points(x))

    @staticmethod
    def _people(x, label, prepend=''):
        num = prepend + babel.numbers.format_number(x, c.locale)
        return strings.person_label % \
            dict(num=num, persons=label(x))

    @staticmethod
    def subscribers(x):
        return Score._people(x, plurals.N_subscribers)

    @staticmethod
    def readers(x):
        return Score._people(x, plurals.N_readers)

    @staticmethod
    def somethings(x, word):
        p = plurals.string_dict[word]
        f = lambda x: ungettext(p[0], p[1], x)
        return strings.number_label % dict(num=x, thing=f(x))

    @staticmethod
    def users_here_now(x, prepend=''):
        return Score._people(x, plurals.N_users_here_now, prepend=prepend)

    @staticmethod
    def none(x):
        return ""


def fallback_trans(x):
    """For translating placeholder strings the user should never see
    in raw form, such as 'funny 500 message'.  If the string does not
    translate in the current language, falls back on the g.lang
    translation that we've hopefully already provided"""
    t = _(x)
    if t == x:
        l = get_lang()
        set_lang(g.lang, graceful_fail = True)
        t = _(x)
        if l and l[0] != g.lang:
            set_lang(l[0])
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


def generate_strings():
    """Print out automatically generated strings for translation."""

    # used by error pages and in the sidebar for why to create a subreddit
    for name, rand_string in rand_strings:
        for string in rand_string:
            print "# TRANSLATORS: Do not translate literally. Come up with a funny/relevant phrase (see the English version for ideas)"
            print "print _('" + string + "')"

    # these are used in r2.lib.pages.trafficpages
    INTERVALS = ("hour", "day", "month")
    TYPES = ("uniques", "pageviews", "traffic", "impressions", "clicks")
    for interval in INTERVALS:
        for type in TYPES:
            print "print _('%s by %s')" % (type, interval)
