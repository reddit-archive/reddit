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
import sqlalchemy as sa

def get_engine(name, db_host='', db_user='', db_pass='',
               pool_size = 5, max_overflow = 5):
    host = db_host if db_host else '' 
    if db_user:
        if db_pass:
            host = "%s:%s@%s" % (db_user, db_pass, db_host)
        else:
            host = "%s@%s" % (db_user, db_host)
    return sa.create_engine('postgres://%s/%s' % (host, name),
                            strategy='threadlocal',
                            pool_size = int(pool_size),
                            max_overflow = int(max_overflow))

class db_manager:
    def __init__(self):
        self.type_db = None
        self.relation_type_db = None
        self.things = {}
        self.relations = {}
        self.engines = {}
        self.avoid_master_reads = {}

    def add_thing(self, name, thing_dbs, avoid_master = False, **kw):
        """thing_dbs is a list of database engines. the first in the
        list is assumed to be the master, the rest are slaves."""
        self.things[name] = thing_dbs
        self.avoid_master_reads[name] = avoid_master

    def add_relation(self, name, type1, type2, relation_dbs,
                     avoid_master = False, **kw):
        self.relations[name] = (type1, type2, relation_dbs)
        self.avoid_master_reads[name] = avoid_master
