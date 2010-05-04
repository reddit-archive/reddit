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

from pylons import c, g, request
from r2.lib.utils import ip_and_slash16, jury_cache_dict, voir_dire_priv
from r2.lib.memoize import memoize
from r2.lib.log import log_text

@memoize('trial_utils.all_defendants')
def all_defendants_cache():
    fnames = g.hardcache.backend.ids_by_category("trial")
    return fnames

def all_defendants(quench=False, _update=False):
    from r2.models import Thing
    all = all_defendants_cache(_update=_update)

    defs = Thing._by_fullname(all, data=True).values()

    if quench:
        # Used for the spotlight, to filter out trials with over 30 votes;
        # otherwise, hung juries would hog the spotlight for an hour as
        # their vote counts continued to skyrocket

        return filter (lambda d:
                       not g.cache.get("quench_jurors-" + d._fullname),
                       defs)
    else:
        return defs

def trial_key(thing):
    return "trial-" + thing._fullname

def on_trial(things):
    keys = dict((trial_key(thing), thing._fullname)
                for thing in things)
    vals = g.hardcache.get_multi(keys)
    return dict((keys[key], val)
                for (key, val)
                in vals.iteritems())

def end_trial(thing):
    g.hardcache.delete(trial_key(thing))
    all_defendants(_update=True)

def indict(defendant):
    tk = trial_key(defendant)

    rv = False
    if defendant._deleted:
        result = "already deleted"
    elif hasattr(defendant, "promoted") and defendant.promoted:
        result = "it's promoted"
    elif hasattr(defendant, "verdict") and defendant.verdict is not None:
        result = "it already has a verdict"
    elif g.hardcache.get(tk):
        result = "it's already on trial"
    else:
        # The regular hardcache reaper should never run on one of these,
        # since a mistrial should be declared if the trial is still open
        # after 24 hours. So the "3 days" expiration isn't really real.
        g.hardcache.set(tk, True, 3 * 86400)
        all_defendants(_update=True)
        result = "it's now indicted: %s" % tk
        rv = True

    log_text("indict_result", "%r: %s" % (defendant, result), level="info")

    return rv

# Check to see if a juror is eligible to serve on a jury for a given link.
def voir_dire(account, ip, slash16, defendants_voted_upon, defendant, sr):
    from r2.models import Link

    if defendant._deleted:
        g.log.debug("%s is deleted" % defendant)
        return False

    if defendant._id in defendants_voted_upon:
        g.log.debug("%s already jury-voted for %s" % (account.name, defendant))
        return False

    if not isinstance(defendant, Link):
        g.log.debug("%s can't serve on a jury for %s: it's not a link" %
                    account.name, defendant)
        return False

    if g.debug:
        return True

    if not voir_dire_priv(account, ip, slash16, defendant, sr):
        return False

    return True

def assign_trial(account, ip, slash16):
    from r2.models import Jury, Subreddit
    from r2.lib.db import queries

    defendants_voted_upon = []
    defendants_assigned_to = []
    for jury in Jury.by_account(account):
        defendants_assigned_to.append(jury._thing2_id)
        if jury._name != '0':
            defendants_voted_upon.append(jury._thing2_id)

    subscribed_sr_ids = Subreddit.user_subreddits(account, ids=True, limit=None)

    # Pull defendants, except ones which already have lots of juryvotes
    defs = all_defendants(quench=True)

    # Filter out defendants outside this user's subscribed SRs
    defs = filter (lambda d: d.sr_id in subscribed_sr_ids, defs)

    # Dictionary of sr_id => SR for all defendants' SRs
    srs = Subreddit._byID(set([ d.sr_id for d in defs ]))

    # Dictionary of sr_id => eligibility bool
    submit_srs = {}
    for sr_id, sr in srs.iteritems():
        submit_srs[sr_id] = sr.can_submit(account) and not sr._spam

    # Filter out defendants with ineligible SRs
    defs = filter (lambda d: submit_srs.get(d.sr_id), defs)

    likes = queries.get_likes(account, defs)

    # Filter out things that the user has upvoted or downvoted
    defs = filter (lambda d: likes.get((account, d)) is None, defs)

    # Prefer oldest trials
    defs.sort(key=lambda x: x._date)

    for defendant in defs:
        sr = srs[defendant.sr_id]

        if voir_dire(account, ip, slash16, defendants_voted_upon, defendant, sr):
            if defendant._id not in defendants_assigned_to:
                j = Jury._new(account, defendant)

            return defendant

    return None

def populate_spotlight():
    if not (c.user_is_loggedin and c.user.jury_betatester()):
        g.log.debug("not eligible")
        return None

    ip, slash16 = ip_and_slash16(request)

    jcd = jury_cache_dict(c.user, ip, slash16)

    if jcd is None:
        return None

    if g.cache.get_multi(jcd.keys()) and not g.debug:
        g.log.debug("recent juror")
        return None

    trial = assign_trial(c.user, ip, slash16)

    if trial is None:
        g.log.debug("nothing available")
        return None

    for k, v in jcd.iteritems():
        g.cache.set(k, True, v)

    return trial

def look_for_verdicts():
    from r2.models import Trial

    print "checking all trials for verdicts..."
    for defendant in all_defendants():
        print "Looking at %r" % defendant
        v = Trial(defendant).check_verdict()
        print "Verdict: %r" % v
