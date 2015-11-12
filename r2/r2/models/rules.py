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

import json
from datetime import datetime
from pylons import app_globals as g
from pylons.i18n import _

from r2.lib.db import tdb_cassandra

OLD_SITEWIDE_RULES = [
    _("spam"),
    _("vote manipulation"),
    _("personal information"),
    _("sexualizing minors"),
    _("breaking reddit"),
]

SITEWIDE_RULES = [
    _("Spam"),
    _("Personal and confidential information"),
    _("Threatening, harassing, or inciting violence"),
]
MAX_RULES_PER_SUBREDDIT = 15

class SubredditRules(tdb_cassandra.View):
    _use_db = True
    _extra_schema_creation_args = {
        "key_validation_class": tdb_cassandra.UTF8_TYPE,
        "column_name_class": tdb_cassandra.UTF8_TYPE,
        "default_validation_class": tdb_cassandra.UTF8_TYPE,
    }
    _compare_with = tdb_cassandra.UTF8_TYPE
    _read_consistency_level = tdb_cassandra.CL.ONE
    _write_consistency_level = tdb_cassandra.CL.ONE
    _connection_pool = "main"

    @classmethod
    def get_rule_blob(self, short_name, description, priority, when=None):
        if not when:
            when = str(datetime.now(g.tz))

        jsonpacked = json.dumps({
            "description": description,
            "priority": priority,
            "when": when,
        })
        blob = {short_name: jsonpacked}
        return blob

    @classmethod
    def create(self, subreddit, short_name, description, when=None):
        """Create a rule and append to the end of the priority list."""
        try:
            priority = len(list(self._cf.get(subreddit._id36)))
        except tdb_cassandra.NotFoundException:
            priority = 0

        if priority >= MAX_RULES_PER_SUBREDDIT:
            return

        blob = self.get_rule_blob(short_name, description, priority, when)
        self._set_values(subreddit._id36, blob)

    @classmethod
    def remove_rule(self, subreddit, short_name):
        """Remove a rule and update priorities of remaining rules."""
        self._remove(subreddit._id36, [short_name])

        rules = self.get_rules(subreddit)
        blobs = {}
        for index, rule in enumerate(rules):
            if rule["priority"] != index:
                blobs.update(self.get_rule_blob(
                    short_name=rule["short_name"],
                    description=rule["description"],
                    priority=index,
                    when=rule["when"],
                ))
        self._set_values(subreddit._id36, blobs)

    @classmethod
    def update(self, subreddit, old_short_name, short_name, description):
        """Update the short_name or description of a rule."""
        rules = self._cf.get(subreddit._id36)
        if old_short_name != short_name:
            old_rule = rules.get(old_short_name, None)
            self._remove(subreddit._id36, [old_short_name])
        else:
            old_rule = rules.get(short_name, None)
        if not old_rule:
            return False

        old_rule = json.loads(old_rule)
        blob = self.get_rule_blob(
            short_name,
            description,
            old_rule["priority"],
            old_rule["when"],
        )
        self._set_values(subreddit._id36, blob)

    @classmethod
    def reorder(self, subreddit, short_name, priority):
        """Update the priority spot of a rule

        Move an existing rule to the desired spot in the rules
        list and then update the priority of the rules.
        """
        rule_to_reorder = self.get_rule(subreddit, short_name)
        if not rule_to_reorder:
            return False

        self._remove(subreddit._id36, [short_name])
        rules = self.get_rules(subreddit)

        priority = min(priority, len(rules))
        current_priority_index = 0
        blobs = {}
        blobs.update(self.get_rule_blob(
                    rule_to_reorder["short_name"],
                    rule_to_reorder["description"],
                    priority,
                    rule_to_reorder["when"],
        ))

        for rule in rules:
            # Placeholder for rule_to_reorder's new priority
            if priority == current_priority_index:
                current_priority_index += 1

            if rule["priority"] != current_priority_index:
                blobs.update(self.get_rule_blob(
                    rule["short_name"],
                    rule["description"],
                    current_priority_index,
                    rule["when"],
                ))
            current_priority_index += 1
        self._set_values(subreddit._id36, blobs)

    @classmethod
    def get_rule(self, subreddit, short_name):
        """Return rule associated with short_name or None."""
        try:
            rules = self._cf.get(subreddit._id36)
        except tdb_cassandra.NotFoundException:
            return None
        rule = rules.get(short_name, None)
        if not rule:
            return None
        rule = json.loads(rule)
        rule["short_name"] = short_name
        return rule

    @classmethod
    def get_rules(self, subreddit):
        """Return list of rules sorted by priority."""
        try:
            query = self._cf.get(subreddit._id36)
        except tdb_cassandra.NotFoundException:
            return []

        result = []
        for uuid, json_blob in query.iteritems():
            payload = json.loads(json_blob)
            payload["short_name"] = uuid
            result.append(payload)

        return sorted(result, key=lambda t: t["priority"])
