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

from pylons import c, g, request
from r2.lib.utils import jury_cache_dict, voir_dire_priv, tup
from r2.lib.memoize import memoize
from r2.lib.log import log_text
import random as rand

# Hardcache lifetime for a trial.
# The regular hardcache reaper should never run on one of these,
# since a mistrial should be declared if the trial is still open
# after 24 hours. So the "3 days" expiration isn't really real.
TRIAL_TIME = 3 * 86400

def trial_key(thing):
    return "trial-" + thing._fullname

def trial_info(things):
    things = tup(things)
    keys = dict((trial_key(thing), thing._fullname)
                for thing in things)
# TODO: disabling trial lookup for now, since there aren't any
#    vals = g.hardcache.get_multi(keys)
    vals = {}
    return dict((keys[key], val)
                for (key, val)
                in vals.iteritems())

def end_trial(thing, verdict=None):
    from r2.models import Trial
    if trial_info(thing):
        g.hardcache.delete(trial_key(thing))
        Trial.all_defendants(_update=True)

    if verdict is not None:
        thing.verdict = verdict
        thing._commit()

def indict(defendant):
    from r2.models import Trial
    tk = trial_key(defendant)

    rv = False
    if defendant._deleted:
        result = "already deleted"
    elif getattr(defendant, "promoted", None) is not None:
        result = "it's promoted"
    elif hasattr(defendant, "verdict") and defendant.verdict is not None:
        result = "it already has a verdict"
    elif g.hardcache.get(tk):
        result = "it's already on trial"
    else:
        # The spams/koshers dict is just a infrequently-updated cache; the
        # official source of the data is the Jury relation.
        g.hardcache.set(tk, dict(spams=0, koshers=0), TRIAL_TIME)
        Trial.all_defendants(_update=True)
        result = "it's now indicted: %s" % tk
        rv = True

    log_text("indict_result", "%s: %s" % (defendant._id36, result), level="info")

    return rv

# These are spam/kosher votes, not up/down votes
def update_voting(defendant, koshers, spams):
    tk = trial_key(defendant)
    d = g.hardcache.get(tk)
    if d is None:
        log_text("update_voting() fail",
                 "%s not on trial" % defendant._id36,
                 level="error")
    else:
        d["koshers"] = koshers
        d["spams"] = spams
        g.hardcache.set(tk, d, TRIAL_TIME)

# Check to see if a juror is eligible to serve on a jury for a given link.
def voir_dire(account, ip, slash16, defendants_assigned_to, defendant, sr):
    from r2.models import Link

    if defendant._deleted:
        g.log.debug("%s is deleted" % defendant)
        return False

    if defendant._id in defendants_assigned_to:
        g.log.debug("%s is already assigned to %s" % (account.name, defendant))
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

def assign_trial(account, juries_already_on, ip, slash16):
    from r2.models import Jury, Subreddit, Trial
    from r2.lib.db import queries

    defendants_assigned_to = []
    for jury in juries_already_on:
        defendants_assigned_to.append(jury._thing2_id)

    subscribed_sr_ids = Subreddit.user_subreddits(account, ids=True, limit=None)

    # Pull defendants, except ones which already have lots of juryvotes
    defs = Trial.all_defendants(quench=True)

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

    if not g.debug:
        # Filter out things that the user has upvoted or downvoted
        defs = filter (lambda d: likes.get((account, d)) is None, defs)

    # Prefer oldest trials
    defs.sort(key=lambda x: x._date)

    for defendant in defs:
        sr = srs[defendant.sr_id]

        if voir_dire(account, ip, slash16, defendants_assigned_to, defendant, sr):
            j = Jury._new(account, defendant)
            return defendant

    return None

def populate_spotlight():
    raise Exception("this function is broken (re: ip_and_slash16) and pending demolition")

    from r2.models import Jury
    from r2.lib.db.thing import NotFound

    if not (c.user_is_loggedin and c.user.jury_betatester()):
        g.log.debug("not eligible")
        return None

    try:
        juries_already_on = Jury.by_account(c.user)
    except NotFound:
        # This can happen if Jury.delete_old() just so happens to be cleaning
        # up this user's old Jury rels while they're visiting the front page.
        # In this unlucky case, just skip the 20% nagging below.
        juries_already_on = []

    # If they're already on a jury, and haven't yet voted, re-show
    # it every five or so times.
    if rand.random() < 0.2:
        unvoted = filter(lambda j: j._name == '0', juries_already_on)
        defs = [u._thing2 for u in unvoted]
        active_trials = trial_info(defs)
        for d in defs:
            if active_trials.get(d._fullname, False):
                return d

    if not g.cache.add("global-jury-key", True, 5):
        g.log.debug("not yet time to add another juror")
        return None

    ip, slash16 = ip_and_slash16(request)

    jcd = jury_cache_dict(c.user, ip, slash16)

    if jcd is None:
        g.cache.delete("global-jury-key")
        return None

    if g.cache.get_multi(jcd.keys()) and not g.debug:
        g.log.debug("recent juror")
        g.cache.delete("global-jury-key")
        return None

    trial = assign_trial(c.user, juries_already_on, ip, slash16)

    if trial is None:
        g.log.debug("nothing available")
        g.cache.delete("global-jury-key")
        return None

    for k, v in jcd.iteritems():
        g.cache.set(k, True, v)

    log_text("juryassignment",
             "%s was just assigned to the jury for %s" % (c.user.name, trial._id36),
             level="info")

    return trial

def look_for_verdicts():
    from r2.models import Trial, Jury

    print "checking all trials for verdicts..."
    for defendant in Trial.all_defendants():
        print "Looking at reddit.com/comments/%s/x" % defendant._id36
        v = Trial(defendant).check_verdict()
        print "Verdict: %r" % v

    Jury.delete_old(verbose=True, limit=1000)
