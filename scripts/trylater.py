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
# All portions of the code written by reddit are Copyright (c) 2006-2015 reddit
# Inc. All Rights Reserved.
###############################################################################

from pylons import app_globals as g

from r2.lib import amqp
from r2.lib.hooks import all_hooks, get_hook
from r2.models.trylater import TryLater


def run_trylater():
    trylater_names = {
        hook_name[len("trylater."):]: hook_name
        for hook_name in all_hooks().iterkeys()
        if hook_name.startswith("trylater.")
    }

    for trylater_name, trylater_hook in trylater_names.iteritems():
        with TryLater.get_ready_items_and_cleanup(trylater_name) as items:
            g.log.info("Trying %s", trylater_name)
            get_hook(trylater_hook).call(data=items)

    amqp.worker.join()
    g.stats.flush()
