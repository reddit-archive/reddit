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

from r2.models import Link
from r2.lib.utils import Storage
from datetime import datetime
from pylons import g

class Trial(Storage):
    def __init__(self, defendant):
        from r2.lib.utils.trial_utils import on_trial

        if not defendant._loaded:
            defendant._load()
        if not on_trial(defendant):
            raise ValueError ("Defendant %s is not on trial" % defendant._id)
        self.defendant = defendant

    def convict(self):
#        train_spam_filter(self.defendant, "spam")
        if self.defendant._spam:
            pass #TODO: PM submitter
        else:
            pass #TODO: ban it

    def acquit(self):
#        train_spam_filter(self.defendant, "ham")
        if self.defendant._spam:
            pass
#            self.defendant._date = datetime.now(g.tz)
#            self.defendant._spam = False
            #TODO: PM submitter

    def mistrial(self):
        #TODO: PM mods
        if self.defendant._spam:
            pass #TODO: PM submitter

    def verdict(self):
        from r2.models import Jury

        ups = 0
        downs = 0
        nones = 0

        now = datetime.now(g.tz)
        defendant_age = now - self.defendant._date
        if defendant_age.days > 0:
            return "timeout"

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
                ups += 1
            elif j._name == "-1":
                downs += 1
            else:
                raise ValueError("weird jury vote: [%s]" % j._name)

        # The following trace is temporary; it'll be removed once this
        # is done via cron job as opposed to manually
        print "%d ups, %d downs, %d haven't voted yet" % (ups, downs, nones)

        total_votes = ups + downs

        if total_votes < 7:
            g.log.debug("not enough votes yet")
            return None

        # Stop showing this in the spotlight box once it has 30 votes
        if total_votes >= 30:
            g.cache.set("quench_jurors-" + self.defendant._fullname, True)

        # If a trial is less than an hour old, and votes are still trickling in
        # (i.e., there was one in the past five minutes), it's not yet time to
        # declare a verdict.
        if defendant_age.seconds < 3600 and (now - latest_juryvote).seconds < 300:
            g.log.debug("votes still trickling in")
            return None

        up_pct = float(ups) / float(total_votes)

        if up_pct < 0.34:
            return "guilty"
        elif up_pct > 0.66:
            return "innocent"
        elif total_votes >= 30:
            return "hung jury"
        else:
            g.log.debug("hung jury, so far")
            return None # no decision yet; wait for more voters

    def check_verdict(self):
        from r2.lib.utils.trial_utils import end_trial

        verdict = self.verdict()
        if verdict is None:
            return # no verdict yet

        if verdict == "guilty":
            self.convict()
        elif verdict == "innocent":
            self.acquit()
        elif verdict in ("timeout", "hung jury"):
            self.mistrial()
        else:
            raise ValueError("Invalid verdict [%s]" % verdict)

        self.defendant.verdict = verdict
        self.defendant._commit()

        end_trial(self.defendant)

        return verdict
