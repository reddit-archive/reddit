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
# All portions of the code written by CondeNet are Copyright (c) 2006-2008
# CondeNet, Inc. All Rights Reserved.
################################################################################
import os, re, sys, socket, time, random, time
from itertools import chain

from wrapped import Wrapped
from datetime import datetime, timedelta
from pylons import g
from r2.lib.utils import tup
from r2.lib.cache import Memcache

class AppServiceMonitor(Wrapped):
    cache_key       = "machine_datalogger_data_"
    cache_key_small = "machine_datalogger_db_summary_"
    cache_lifetime  = "memcached_lifetime"

    """
    Master controller class for service monitoring.
    This class has three purposes:

      * Fetches Hostlogger instances from the cache for generating
        reports (by calling render() as it is a subclass of wrapped).

      * keeping track of which machines are DB machines, allowing db
        load to be checked and improving load balancing.

      * monitoring the local host's load and storing it in the cache.

    """

    def __init__(self, hosts = None):
        """
        hosts is a list of machine hostnames to be tracked.
        """
        self._hosts = hosts or g.monitored_servers 

        db_info = {}
        for db in g.databases:
            dbase, ip = list(g.to_iter(getattr(g, db + "_db")))[:2]
            name = socket.gethostbyaddr(ip)[0]
    
            for host in g.monitored_servers:
                if (name == host or
                    ("." in host and name.endswith("." + host)) or
                    name.startswith(host + ".")):
                    db_info[db] = (dbase, ip, host)

        self._db_info = db_info
        self.hostlogs = []
        Wrapped.__init__(self)

    @classmethod
    def set_cache_lifetime(cls, data):
        g.rendercache.set(cls.cache_lifetime, data)

    @classmethod
    def get_cache_lifetime(cls, average = None):
        d =  g.rendercache.get(cls.cache_lifetime, DataLogger())
        return d(average)

    @classmethod
    def from_cache(cls, host):
        key = cls.cache_key + str(host)
        return g.rendercache.get(key)

    def set_cache(self, h):
        cache = g.rendercache
        # cache the whole object
        res = {}
        res[self.cache_key + str(h.host)] = h
        if h.database:
            data = (h.load(), h.load(60),
                    h.database.connections(), h.database.connections(60), 
                    h.database.max_connections)
            # cache summary for easy db lookups
            for dbn in chain(h.ini_db_names, h.db_ips):
                res[self.cache_key_small + dbn] = data
        cache.set_multi(res)

    @classmethod
    def get_db_load(cls, *names):
        return g.rendercache.get_multi(names, prefix = cls.cache_key_small)

    def database_load(self, db_name):
        if self._db_info.has_key(db_name):
            return self.server_load(self._db_info[db_name][-1])

    def server_load(self, mach_name):
        h = self.from_cache(host) 
        return h.load.most_recent()
        
    def __iter__(self):
        if not self.hostlogs:
            self.hostlogs = [self.from_cache(host) for host in self._hosts]
            self.hostlogs = filter(None, self.hostlogs)
        return iter(self.hostlogs)

    def render(self, *a, **kw):
        self.hostlogs = list(self)
        return Wrapped.render(self, *a, **kw)

    def monitor(self, srvname, loop = True, loop_time = 2, *a, **kw):

        host = g.reddit_host
        h = HostLogger(host, self)
        while True:
            h.monitor(srvname, *a, **kw)
            
            self.set_cache(h)
            if loop:
                time.sleep(loop_time)
            else:
                break
            

    def is_db_machine(self, host):
        """
        Given a host name, checks the list of known DB machines to
        determine if the host is one of them.
        """
        return dict((k, (d2, ip))
                    for k, (d2,ip,name) in self._db_info.iteritems()
                    if host == name)


class DataLogger(object):
    """
    simple stat tracker class.  Elements are added to a list of length
    maxlen along with their timestamp.  __call__ generates the average
    of the interval provided or returns the last element if no
    interval is provided
    """
    
    def __init__(self, maxlen = 300):
        self._list = []
        self.maxlen = maxlen

    def add(self, value):
        self._list.append((value, datetime.now()))
        if len(self._list) > self.maxlen:
            self._list = self._list[-self.maxlen:]
                          

    def __call__(self, average = None):
        time = datetime.now()
        if average > 0 and self._list:
            lst = filter(lambda x: time - x[1] <= timedelta(0, average),
                         self._list)
            return sum(x[0] for x in lst)/max(len(lst), 1)
        elif self._list:
            return self._list[-1][0]
        else:
            return -1

    def __len__(self):
        return len(self._list)

    def most_recent(self):
        if self._list:
            return self._list[-1]
        else:
            return [0, None]

        
class Service(object):
    def __init__(self, name, pid, age):
        self.name = name
        self.pid = pid
        self.age = age

        self.mem  = DataLogger()
        self.cpu  = DataLogger()

    def last_update(self):
        return max(x.most_recent()[1] for x in [self.mem, self.cpu])


class Database(object):

    def __init__(self):
        self.vacuuming = []
        self.connections = DataLogger()
        self.max_connections = -1
        self.ip_conn = {}
        self.db_conn = {}
        self.query_count = DataLogger()
    

    def track(self, conn = 0, ip_conn = {}, db_conn = {}, vacuums = {},
              query_count = None, max_connections = None):

        #log the number of connections
        self.connections.add(conn)
        if self.max_connections:
            self.max_connections = max_connections

        # log usage by ip
        for ip, num in ip_conn.iteritems():
            self.ip_conn.setdefault(ip, DataLogger())
            self.ip_conn[ip].add(num)

        # log usage by db
        for db, num in db_conn.iteritems():
            self.db_conn.setdefault(db, DataLogger())
            self.db_conn[db].add(num)

        # log vacuuming
        self.vacuuming = [k for k, v in vacuums.iteritems() if v]

        # has a query count
        if query_count is not None:
            self.query_count.add(query_count)
        
class HostLogger(object):

    def __init__(self, host, master):
        self.host = host
        self.load = DataLogger()
        self.services = {}
        db_info = master.is_db_machine(host)

        self.ini_db_names = db_info.keys()
        self.db_names = set(name for name, ip in db_info.itervalues())
        self.db_ips   = set(ip   for name, ip in db_info.itervalues())
            
        self.database = Database() if self.db_names else None

    def service_pids(self):
        return self.services.keys()

    def track(self, pid, cpu = 0, mem = 0, **kw):
        pid = int(pid)
        if self.services.has_key(pid):
            s = self.services[pid]
            s.cpu.add(cpu)
            s.mem.add(mem)

    def add_service(self, name, pid, age):
        pid = int(pid)
        if not self.services.has_key(pid):
            self.services[pid] = Service(name, pid, int(age / 60))
        else:
            self.services[pid].age = int(age / 60)
        
    def clean_dead(self, age = 10):
        time = datetime.now()
        for pid, s in list(self.services.iteritems()):
            t = s.last_update()
            if not t or t < time - timedelta(0, age) or pid < 0:
                del self.services[pid]


    def monitor(self, srvname, 
                srv_params = {}, top_params = {}, db_params = {}):
        # (re)populate the service listing
        for name, status, pid, t in supervise_list(**srv_params):
            if not srvname or any(s in name for s in srvname):
                self.add_service(name, pid, t)
        
        # check process usage
        proc_info = process_info(proc_ids = self.service_pids(),
                                 **top_params)
        for pid, info in proc_info.iteritems():
            self.track(pid, **info)
        
        #check db usage:
        if self.database:
            self.database.track(**check_database(self.db_names,
                                                 **db_params))
        
        handle = os.popen('/usr/bin/uptime')
        foo = handle.read()
        foo = foo.split("load average")[1].split(':')[1].strip(' ')
        self.load.add(float(foo.split(' ')[1].strip(',')))
        handle.close()
        
        self.clean_dead()


    def __iter__(self):
        s = self.services
        pids = s.keys()
        pids.sort(lambda x, y: 1 if s[x].name > s[y].name else -1)
        for pid in pids:
            yield s[pid]
        


re_text = re.compile('\S+')
def process_info(proc_ids = [], name = '', exe = "/bin/ps"):
    pidi = 0
    cpuid = 1
    memid = 2
    ageid = 5

    if not os.path.exists(exe):
        raise ValueError, "bad executable specified for top"

    cmd = ([exe, "-a", '-O', 'pcpu,pmem'] +
           ["-p %d" % x for x in proc_ids if x > 0])
    handle = os.popen(' '.join(cmd))

    proc_ids = set(map(int, proc_ids))
    res = {}
    for line in handle:
        line = re_text.findall(line)
        try:
            pid = int(line[pidi])
            n = ' '.join(line[ageid+1:])
            if (n.startswith(name) and
                (not proc_ids or int(pid) in proc_ids)):
                res[pid] =  dict(cpu = float(line[cpuid]),
                                 mem = float(line[memid]),
                                 age = float(line[ageid].split(':')[0]),
                                 name = n)
        except (ValueError, IndexError):
            pass
    handle.close()
    return res


def supervise_list(exe = "/usr/local/bin/svstat", path = '/service/'):
    handle = os.popen("%s %s*" % (exe, path))
    defunct = 0
    for line in handle:
        line = line.split(' ')
        name = line[0]
        try:
            status, blah, pid, time = line[1:5]
            name = name[len(path):].strip(':')
            if status == 'up':
                pid = int(pid.strip(')'))
                time = int(time)
            else:
                raise ValueError, "down process"
        except ValueError:
            defunct += 1
            pid = -defunct
            time = 0
        yield (name, "down", pid, time)
    handle.close()

def check_database(db_names, proc = "postgres", check_vacuum = True, user='ri'):
    def simple_query(query, _db = None):
        if not _db: _db = list(db_names)[0]
        cmd = (r"(echo '\\t'; echo '%(query)s' ) " +
               "| psql -U %(user)s %(db)s")
        cmd = cmd % dict(query = query, user = user, db = _db)
        handle = os.popen(cmd)
        res = list(handle)
        handle.close()
        return res
        
    by_ip = {}
    by_db = {}
    total = 0
    for line in simple_query("select datname, client_addr "
                             "from pg_catalog.pg_stat_activity ;"):
        line = line.strip(' \n').split("|")
        if len(line) == 2:
            db, ip = map(lambda x: x.strip(' '), line)
            ip = ip or '[local]'
            by_ip[ip] = by_ip.get(ip, 0) + 1
            by_db[db] = by_db.get(db, 0) + 1
            total += 1

    vacuums = {}
    if check_vacuum:
        for db in by_db:
            for line in simple_query('select * from active;', db):
                cmd = line.split('|')[-1].strip(' ').lower()
                if cmd.startswith('vacuum '):
                    vacuums[db] = True
                    break

    res = dict(conn = total, ip_conn = by_ip, db_conn = by_db,
               vacuums = vacuums, max_connections = 0)
    
    for line in simple_query('show max_connections;'):
        try:
            res['max_connections'] = int(line.strip('\n '))
            break
        except ValueError:
            continue
            

    if 'query_queue' in by_db:
        for line in simple_query('select count(*) from reddit_query_queue;',
                              'query_queue'):
            try:
                res['query_count'] = int(line.strip('\n '))
                break
            except ValueError:
                continue

    return res    

def monitor_cache_lifetime(minutes, retest = 10, ntest = -1,
                           cache_key = "cache_life_", verbose = False):

    # list of list of active memcache test keys
    keys = []
    period = 60  # 1 minute cycle time
    data = DataLogger()
    
    
    # we'll create an independent connection to memcached for this test
    mc = Memcache(g.memcaches)

    counter = 0
    while ntest:

        if counter == 0 or (retest and counter % retest == 0):
            randstr = random.random()
            newkeys = [("%s_%s_%d" % (cache_key, randstr, x), x+1)
                       for x in xrange(minutes)]

            # set N keys, and tell them not to live for longer than this test
            mc.set_multi(dict(newkeys),
                         #time = minutes * period)
                         time = (minutes+1) * period)

            # add the list in reverse order since we'll be poping.
            newkeys.reverse()
            keys.append(newkeys)

        # wait for the next key to (potentially) expire
        counter += 1
        time.sleep(period)

        for k in keys:
            key, age = k.pop()
            if mc.get(key) is None or k == []:
                if verbose:
                    print "cache expiration: %d seconds" % (period * age)
                data.add(period * age)
                AppServiceMonitor.set_cache_lifetime(data)
                # wipe out the list for removal by the subsequent filter
                while k: k.pop()

        # clear out any empty key lists
        if [] in keys:
            keys = filter(None, keys)
            ntest -= 1
                
        
        
