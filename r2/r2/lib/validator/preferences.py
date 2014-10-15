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
# All portions of the code written by reddit are Copyright (c) 2006-2014 reddit
# Inc. All Rights Reserved.
###############################################################################
from pylons import g
from r2.lib.validator.validator import (
    VBoolean,
    VInt,
    VLang,
    VOneOf,
)

# Validators that map directly to Account._preference_attrs
# The key MUST be the same string as the value in _preference_attrs
# Non-preference validators should be added to to the controller
# method directly (see PostController.POST_options)
PREFS_VALIDATORS = dict(
    pref_frame=VBoolean('frame'),
    pref_clickgadget=VBoolean('clickgadget'),
    pref_organic=VBoolean('organic'),
    pref_newwindow=VBoolean('newwindow'),
    pref_public_votes=VBoolean('public_votes'),
    pref_hide_from_robots=VBoolean('hide_from_robots'),
    pref_hide_ups=VBoolean('hide_ups'),
    pref_hide_downs=VBoolean('hide_downs'),
    pref_over_18=VBoolean('over_18'),
    pref_research=VBoolean('research'),
    pref_numsites=VInt('numsites', 1, 100),
    pref_lang=VLang('lang'),
    pref_media=VOneOf('media', ('on', 'off', 'subreddit')),
    pref_compress=VBoolean('compress'),
    pref_domain_details=VBoolean('domain_details'),
    pref_min_link_score=VInt('min_link_score', -100, 100),
    pref_min_comment_score=VInt('min_comment_score', -100, 100),
    pref_num_comments=VInt('num_comments', 1, g.max_comments,
                           default=g.num_comments),
    pref_highlight_controversial=VBoolean('highlight_controversial'),
    pref_show_stylesheets=VBoolean('show_stylesheets'),
    pref_show_flair=VBoolean('show_flair'),
    pref_show_link_flair=VBoolean('show_link_flair'),
    pref_no_profanity=VBoolean('no_profanity'),
    pref_label_nsfw=VBoolean('label_nsfw'),
    pref_show_promote=VBoolean('show_promote'),
    pref_mark_messages_read=VBoolean("mark_messages_read"),
    pref_threaded_messages=VBoolean("threaded_messages"),
    pref_collapse_read_messages=VBoolean("collapse_read_messages"),
    pref_private_feeds=VBoolean("private_feeds"),
    pref_store_visits=VBoolean('store_visits'),
    pref_show_adbox=VBoolean("show_adbox"),
    pref_show_sponsors=VBoolean("show_sponsors"),
    pref_show_sponsorships=VBoolean("show_sponsorships"),
    pref_show_trending=VBoolean("show_trending"),
    pref_highlight_new_comments=VBoolean("highlight_new_comments"),
    pref_monitor_mentions=VBoolean("monitor_mentions"),
    pref_hide_locationbar=VBoolean("hide_locationbar"),
    pref_use_global_defaults=VBoolean("use_global_defaults"),
    pref_creddit_autorenew=VBoolean("creddit_autorenew"),
)


def set_prefs(user, prefs):
    for k, v in prefs.iteritems():
        setattr(user, k, v)


def filter_prefs(prefs, user):
    for pref_key in prefs.keys():
        if pref_key not in user._preference_attrs:
            del prefs[pref_key]

    #temporary. eventually we'll change pref_clickgadget to an
    #integer preference
    prefs['pref_clickgadget'] = 5 if prefs['pref_clickgadget'] else 0
    if user.pref_show_promote is None:
        prefs['pref_show_promote'] = None
    elif not prefs.get('pref_show_promote'):
        prefs['pref_show_promote'] = False

    if not prefs.get("pref_over_18") or not user.pref_over_18:
        prefs['pref_no_profanity'] = True

    if prefs.get("pref_no_profanity") or user.pref_no_profanity:
        prefs['pref_label_nsfw'] = True

    # default all the gold options to on if they don't have gold
    if not user.gold:
        for pref in ('pref_show_adbox',
                     'pref_show_sponsors',
                     'pref_show_sponsorships',
                     'pref_highlight_new_comments',
                     'pref_monitor_mentions',
                     'pref_creddit_autorenew',
                    ):
            prefs[pref] = True
