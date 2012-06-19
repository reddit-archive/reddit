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

from r2.models import Thing, Link, Subreddit, AllSR, admintools
from r2.lib.utils import Storage, tup
from r2.lib.memoize import memoize
from datetime import datetime
from pylons import g

class Trial(Storage):
    def __init__(self, defendant):
        from r2.lib.utils.trial_utils import trial_info

        if not defendant._loaded:
            defendant._load()
        if not trial_info(defendant):
            raise ValueError ("Defendant %s is not on trial" % defendant._id)
        self.defendant = defendant

    def convict(self, details = ''):
#        if self.defendant._spam:
#            TODO: PM submitter, maybe?
#        else:
#            TODO: PM submitter, maybe?
        admintools.spam(self.defendant, auto=False, moderator_banned=True,
                        banner="deputy moderation" + details)

    def acquit(self, details = ''):
        admintools.unspam(self.defendant, unbanner="deputy moderation" + details)

#        if self.defendant._spam:
#           TODO: PM submitter
#           TODO: reset submission time:
#           self.defendant._date = datetime.now(g.tz)

    def mistrial(self):
        #TODO: PM mods
        if self.defendant._spam:
            pass #TODO: PM submitter

    def verdict(self):
        from r2.models import Jury
        from r2.lib.utils.trial_utils import update_voting

        koshers = 0
        spams = 0
        nones = 0

        now = datetime.now(g.tz)
        defendant_age = now - self.defendant._date
        if defendant_age.days > 0:
            return ("jury timeout", None, None)

        latest_juryvote = None
        for j in Jury.by_defendant(self.defendant):
            if j._name == "0":
                nones += 1
                continue

            # For non-zero votes, update latest_juryvote
            if latest_juryvote is None:
                latest_juryvote = j._date
            else:
                latest_juryvote = max(latest_juryvote, j._date)

            if j._name == "1":
                koshers += 1
            elif j._name == "-1":
                spams += 1
            else:
                raise ValueError("weird jury vote: [%s]" % j._name)

        # The following trace is temporary; it'll be removed once this
        # is done via cron job as opposed to manually
        print "%d koshers, %d spams, %d haven't voted yet" % (koshers, spams, nones)

        update_voting(self.defendant, koshers, spams)

        total_votes = koshers + spams

        if total_votes < 7:
            g.log.debug("not enough votes yet")
            return (None, koshers, spams)

        # Stop showing this in the spotlight box once it has 20 votes
        if total_votes >= 20:
            g.cache.set("quench_jurors-" + self.defendant._fullname, True)
            quenching = True
        else:
            quenching = False

        # If a trial is less than an hour old, and votes are still trickling
        # in (i.e., there was one in the past five minutes), we're going to
        # require a nearly unanimous opinion to end the trial without
        # waiting for more votes.
        if defendant_age.seconds < 3600 and (now - latest_juryvote).seconds < 300:
            trickling = True
        else:
            trickling = False

        kosher_pct = float(koshers) / float(total_votes)

        if kosher_pct < 0.13:
            return ("guilty", koshers, spams)
        elif kosher_pct > 0.86:
            return ("innocent", koshers, spams)
        elif trickling:
            g.log.debug("votes still trickling in")
            return (None, koshers, spams)
        elif kosher_pct < 0.34:
            return ("guilty", koshers, spams)
        elif kosher_pct > 0.66:
            return ("innocent", koshers, spams)
        elif not quenching:
            g.log.debug("not yet quenching")
            return (None, koshers, spams)
        # At this point, we're not showing the link to any new jurors, and
        # the existing jurors haven't changed or submitted votes for several
        # minutes, so we're not really expecting to get many more votes.
        # Thus, lower our standards for consensus.
        elif kosher_pct < 0.3999:
            return ("guilty", koshers, spams)
        elif kosher_pct > 0.6001:
            return ("innocent", koshers, spams)
        elif total_votes >= 100:
            # This should never really happen; quenching should kick in
            # after 20 votes, so new jurors won't be assigned to the
            # trial. Just in case something goes wrong, close any trials
            # with more than 100 votes.
            return ("hung jury", koshers, spams)
        else:
            g.log.debug("hung jury, so far")
            return (None, koshers, spams) # no decision yet; wait for more voters

    def check_verdict(self):
        from r2.lib.utils.trial_utils import end_trial

        verdict, koshers, spams = self.verdict()
        if verdict is None:
            return # no verdict yet

        if verdict in ("jury timeout", "hung jury"):
            self.mistrial()
        else:
            details=", %d-%d" % (spams, koshers)

            if verdict == "guilty":
                self.convict(details)
            elif verdict == "innocent":
                self.acquit(details)
            else:
                raise ValueError("Invalid verdict [%s]" % verdict)

        end_trial(self.defendant, verdict)

        return verdict

    @classmethod
    @memoize('trial.all_defendants')
    def all_defendants_cache(cls):
        fnames = g.hardcache.backend.ids_by_category("trial")
        return fnames

    @classmethod
    def all_defendants(cls, quench=False, _update=False):
        all = cls.all_defendants_cache(_update=_update)

        defs = Thing._by_fullname(all, data=True).values()

        if quench:
            # Used for the spotlight, to filter out trials with over 20 votes;
            # otherwise, hung juries would hog the spotlight for an hour as
            # their vote counts continued to skyrocket

            return filter (lambda d:
                           not g.cache.get("quench_jurors-" + d._fullname),
                           defs)
        else:
            return defs

    # sr can be plural
    @classmethod
    def defendants_by_sr(cls, sr):
        all = cls.all_defendants()

        if isinstance(sr, AllSR):
            return all

        sr = tup(sr)
        sr_ids = [ s._id for s in sr ]

        return filter (lambda x: x.sr_id in sr_ids, all)
