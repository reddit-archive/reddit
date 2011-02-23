
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
import logging, traceback
import time, random

logger = logging.getLogger('dm_manager')
logger.addHandler(logging.StreamHandler())

def get_engine(name, db_host='', db_user='', db_pass='', db_port='5432',
               pool_size = 5, max_overflow = 5):
    db_port = int(db_port)

    host = db_host if db_host else '' 
    if db_user:
        if db_pass:
            host = "%s:%s@%s:%s" % (db_user, db_pass, db_host, db_port)
        else:
            host = "%s@%s:%s" % (db_user, db_host,db_port)
    return sa.create_engine('postgres://%s/%s' % (host, name),
                            strategy='threadlocal',
                            pool_size = int(pool_size),
                            max_overflow = int(max_overflow))

class db_manager:
    def __init__(self):
        self.type_db = None
        self.relation_type_db = None
        self._things = {}
        self._relations = {}
        self._engines = {}
        self.avoid_master_reads = {}
        self.dead = {}

    def add_thing(self, name, thing_dbs, avoid_master = False, **kw):
        """thing_dbs is a list of database engines. the first in the
        list is assumed to be the master, the rest are slaves."""
        self._things[name] = thing_dbs
        self.avoid_master_reads[name] = avoid_master

    def add_relation(self, name, type1, type2, relation_dbs,
                     avoid_master = False, **kw):
        self._relations[name] = (type1, type2, relation_dbs)
        self.avoid_master_reads[name] = avoid_master

    def setup_db(self, db_name, g_override=None, **params):
        engine = get_engine(**params)
        self._engines[db_name] = engine
        self.test_engine(engine, g_override)

    def things_iter(self):
        for name, engines in self._things.iteritems():
            yield name, [e for e in engines if e not in self.dead]

    def rels_iter(self):
        for name, (type1_name, type2_name, engines) in self._relations.iteritems():
            engines = [e for e in engines if e not in self.dead]
            yield name, (type1_name, type2_name, engines) 

    def mark_dead(self, engine, g_override=None):
        from r2.lib import services
        logger.error("db_manager: marking connection dead: %r" % engine)
        self.dead[engine] = time.time()
        if g_override is None:
            services.AppServiceMonitor.mark_db_down(engine.url.host)
        else:
            services.mark_db_down(g_override.servicecache, engine.url.host)

    def test_engine(self, engine, g_override=None):
        try:
            list(engine.execute("select 1"))
            if engine in self.dead:
                logger.error("db_manager: marking connection alive: %r" % engine)
                del self.dead[engine]
            return True
        except Exception, e:
            logger.error(traceback.format_exc())
            logger.error("connection failure: %r" % engine)
            self.mark_dead(engine, g_override)
            return False

    def get_engine(self, name):
        return self._engines[name]

    def get_engines(self, names):
        return [self._engines[name] for name in names if name in self._engines]

    def get_read_table(self, tables):
        from r2.lib.services import AppServiceMonitor
        # short-cut for only one element
        if len(tables) == 1:
            return tables[0]

        if self.dead:
            tables = set(tables)
            dead = set(t for t in tables if t[0].bind in self.dead)
            for t in list(dead):
                # TODO: tune the reconnect code.  We have about 1-2
                # requests per second per app, so this should
                # reconnect every 50-100 seconds.
                if (random.randint(1,100) == 42 and 
                    self.test_engine(t[0].bind)):
                    dead.remove(t)
            tables = tables - dead

        #'t' is a list of engines itself. since we assume those engines
        #are on the same machine, just take the first one. len(ips) may be
        #< len(tables) if some tables are on the same host.
        ips = dict((t[0].bind.url.host, t) for t in tables)
        ip_loads = AppServiceMonitor.get_db_load(ips.keys())

        total_load = 0
        missing_loads = []
        no_connections = []
        have_loads = []

        for ip in ips:
            if ip not in ip_loads:
                missing_loads.append(ip)
            else:
                load, avg_load, conns, avg_conns, max_conns = ip_loads[ip]

                # remove high load machines from the pool.
                if load < 100:
                    max_load = max(load, avg_load)
                    total_load += max_load
                    have_loads.append((ip, max_load))
                else:
                    no_connections.append(ip)

        if total_load:
            avg_load = total_load / max(len(have_loads), 1)
            ip_weights = [(ip, 1 - load / total_load) for ip, load in have_loads]
        #if total_load is 0, which happens when have_loads is empty
        else:
            avg_load = 1.0
            ip_weights = [(ip, 1.0 / len(have_loads)) for ip, load in have_loads]

        if missing_loads or no_connections:
            #add in the missing load numbers with an average weight
            ip_weights.extend((ip, avg_load) for ip in missing_loads)

            #add in the over-connected machines with a 1% weight
            ip_weights.extend((ip, .01) for ip in no_connections)

        #rebalance the weights
        total_weight = sum(w[1] for w in ip_weights) or 1
        ip_weights = [(ip, weight / total_weight)
                      for ip, weight in ip_weights]

        r = random.random()
        for ip, load in ip_weights:
            if r < load:
                # print "db ip: %s" % str(ips[ip][0].metadata.bind.url.host)
                return ips[ip]
            r = r - load

        #should never happen
        print 'yer stupid'
        return  random.choice(list(tables))

