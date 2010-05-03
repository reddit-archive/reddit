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
from __future__ import with_statement
import os, re, sys, socket, time, random, time, signal
from itertools import chain

from wrapped import Templated
from datetime import datetime, timedelta
from pylons import g
from r2.lib.utils import tup
from r2.lib.cache import Memcache

import subprocess, math

class ShellProcess(object):
    def __init__(self, cmd, timeout = 5, sleepcycle = 0.5):
        self.proc = subprocess.Popen(cmd, shell = True,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)

        ntries = int(math.ceil(timeout / sleepcycle))
        for n in xrange(ntries):
            if self.proc.poll() is not None:
                break
            time.sleep(sleepcycle)
        else:
            print "Process timeout: '%s'" % cmd
            os.kill(self.proc.pid, signal.SIGTERM)

        self.output, self.error = self.proc.communicate()

        self.rcode = self.proc.poll()
        self.timeout = (self.rcode == -signal.SIGTERM)

    def __iter__(self):
        return iter(self.output.split('\n'))

    def read(self):
        return self.output


class AppServiceMonitor(Templated):
    cache_key       = "service_datalogger_data_"
    cache_key_small = "service_datalogger_db_summary_"

    """
    Master controller class for service monitoring.
    This class has three purposes:

      * Fetches Hostlogger instances from the cache for generating
        reports (by calling render() as it is a subclass of wrapped).

      * keeping track of which machines are DB machines, allowing db
        load to be checked and improving load balancing.

      * monitoring the local host's load and storing it in the cache.

    """

    def __init__(self, hosts = None, queue_length_max = {}):
        """
        hosts is a list of machine hostnames to be tracked.
        """
        self._hosts = hosts or g.monitored_servers 

        db_info = {}
        for db in g.databases:
            dbase, ip = list(g.to_iter(getattr(g, db + "_db")))[:2]
            try:
                name = socket.gethostbyaddr(ip)[0]

                for host in g.monitored_servers:
                    if (name == host or
                        ("." in host and name.endswith("." + host)) or
                        name.startswith(host + ".")):
                        db_info[db] = (dbase, ip, host)
            except socket.gaierror:
                print "error resolving host: %s" % ip

        self._db_info = db_info
        q_host = g.amqp_host.split(':')[0]
        if q_host:
            # list of machines that have amqp queues
            self._queue_hosts = set([q_host, socket.gethostbyaddr(q_host)[0]])
        # dictionary of max lengths for each queue 
        self._queue_length_max = queue_length_max

        self.hostlogs = []
        Templated.__init__(self)

    @classmethod
    def set_cache_lifetime(cls, data, key = "memcaches"):
        g.rendercache.set(key + "_lifetime", data)

    @classmethod
    def get_cache_lifetime(cls, average = None, key = "memcaches"):
        d =  g.rendercache.get(key + "_lifetime", DataLogger())
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
    def get_db_load(cls, names):
        return g.rendercache.get_multi(names, prefix = cls.cache_key_small)

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
        return Templated.render(self, *a, **kw)

    def monitor(self, srvname, loop = True, loop_time = 5, *a, **kw):

        host = g.reddit_host
        h = HostLogger(host, self)
        while True:
            h.monitor(srvname, *a, **kw)

            self.set_cache(h)
            if loop:
                time.sleep(loop_time)
            else:
                break

    def is_queue(self, host):
        name = socket.gethostbyaddr(host)[0]
        return name in self._queue_hosts or host in self._queue_hosts

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

    def __init__(self, maxlen = 30):
        self._list = []
        self.maxlen = maxlen

    def add(self, value):
        self._list.append((value, datetime.utcnow()))
        if len(self._list) > self.maxlen:
            self._list = self._list[-self.maxlen:]

    def __call__(self, average = None):
        time = datetime.utcnow()
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

class AMQueueP(object):

    default_max_queue = 1000

    def __init__(self, max_lengths = {}):
        self.queues = {}
        self.max_lengths = max_lengths

    def track(self, cmd = "rabbitmqctl"):
        for line in ShellProcess("%s list_queues" % cmd):
            try:
                name, length = line.split('\t')
                length = int(length.strip(' \n'))
                self.queues.setdefault(name, DataLogger()).add(length)
            except ValueError:
                continue

    def max_length(self, name):
        return self.max_lengths.get(name, self.default_max_queue)

    def __iter__(self):
        for x in sorted(self.queues.keys()):
            yield (x, self.queues[x])

class Database(object):

    def __init__(self):
        self.vacuuming = []
        self.connections = DataLogger()
        self.max_connections = -1
        self.ip_conn = {}
        self.db_conn = {}
        self.query_count = DataLogger()
        self.failures = set([])
        self.disk_usage = 0

    def last_update(self):
        update = self.connections.most_recent()[1]
        return datetime.utcnow() - update if update else None

    def track(self, conn = 0, ip_conn = {}, db_conn = {}, vacuums = {},
              query_count = None, max_connections = -1,
              failures = [], disk_usage = 0):

        if max_connections and max_connections > 0:
            self.max_connections = max_connections

        # if connection failures, assume we are out of connections
        self.connections.add(self.max_connections if failures else conn)
        
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

        # list of failed connections
        self.failures = set(failures)
        if disk_usage:
            self.disk_usage = disk_usage
        
class HostLogger(object):

    def __init__(self, host, master):
        self.host = host
        self.load = DataLogger()
        self.services = {}
        db_info = master.is_db_machine(host)
        is_queue = master.is_queue(host)

        self.ini_db_names = db_info.keys()
        self.db_names = set(name for name, ip in db_info.itervalues())
        self.db_ips   = set(ip   for name, ip in db_info.itervalues())

        self.database = Database() if self.db_names else None
        self.queue    = AMQueueP(master._queue_length_max) if is_queue else None

        self.ncpu = 0
        try:
            with open('/proc/cpuinfo', 'r') as handle:
                for line in handle:
                    if line.startswith("processor"):
                        self.ncpu += 1
        except IOError:
            # guess we don't know
            self.ncpu = 1

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
        time = datetime.utcnow()
        for pid, s in list(self.services.iteritems()):
            t = s.last_update()
            if not t or t < time - timedelta(0, age) or pid < 0:
                del self.services[pid]


    def monitor(self, srvname, 
                srv_params = {}, top_params = {}, db_params = {},
                queue_params = {}):
        # (re)populate the service listing
        if srvname:
            for name, status, pid, t in supervise_list(**srv_params):
                if any(s in name for s in srvname):
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

        if self.queue:
            self.queue.track(**queue_params)

        foo = ShellProcess('/usr/bin/env uptime').read()
        foo = foo.split("load average")[1].split(':')[1].strip(' ')
        self.load.add(float(foo.split(' ')[0].strip(',')))
        
        self.clean_dead()


    def __iter__(self):
        s = self.services
        pids = s.keys()
        pids.sort(lambda x, y: 1 if s[x].name > s[y].name else -1)
        for pid in pids:
            yield s[pid]
        


re_text = re.compile('\S+')
def process_info(proc_ids = [], name = '', exe = "/usr/bin/env ps"):
    pidi = 0
    cpuid = 1
    memid = 2
    ageid = 5

    cmd = ([exe, "-a", '-O', 'pcpu,pmem'] +
           ["-p %d" % x for x in proc_ids if x > 0])

    proc_ids = set(map(int, proc_ids))
    res = {}
    for line in ShellProcess(' '.join(cmd)):
        line = re_text.findall(line)
        try:
            pid = int(line[pidi])
            n = ' '.join(line[ageid+1:])
            if (n.startswith(name) and
                (not proc_ids or int(pid) in proc_ids)):
                age = line[ageid].split(':')[0]
                # patch for > 24 hour old processes
                if '-' in age:
                    days, hours = age.split('-')
                    age = float(days) * 24 + float(hours)
                else:
                    age = float(age)
                res[pid] =  dict(cpu = float(line[cpuid]),
                                 mem = float(line[memid]),
                                 age = age, name = n)
        except (ValueError, IndexError):
            pass
    return res


def supervise_list(exe = "/usr/local/bin/svstat", path = '/service/'):
    """
    Generates a list of processes that are currently running under supervise.
    """
    defunct = 0
    for line in ShellProcess("%s %s*" % (exe, path)):
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
            status = 'down'
        yield (name, status, pid, time)

database_data_dir = None
def check_database(db_names, check_vacuum = True, user='ri'):
    '''
    Finds the number of connections per db (and allocated per remote
    IP) on localhost.  Also uses the postgres "show data_directory"
    command to figure out the db partition disk usage.  Optionally
    checks to see if the db is vacuuming.
    '''
    conn_failure = set([])
    
    def simple_query(query, _db = None):
        if not _db: _db = list(db_names)[0]
        cmd = (r"( echo '\\t'; echo '%(query)s' ) " +
               "| psql -U %(user)s %(db)s")
        cmd = cmd % dict(query = query, user = user, db = _db)
        handle = ShellProcess(cmd)
        if handle.rcode and not handle.timeout:
            conn_failure.add(_db)
            return []
        return iter(handle)
        
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
            for line in simple_query('select current_query from active;', db):
                cmd = line.strip(' ').lower()
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

    # best to only have to fetch the db dir once.  It shouldn't be
    # moving around
    global database_data_dir  
    if database_data_dir is None:
        for line in simple_query('show data_directory'):
            line = line.strip(' \n')
            if os.path.exists(line):
                 database_data_dir = line
                 break

    if database_data_dir:
        for line in  ShellProcess("/usr/bin/env df %s" % database_data_dir):
            line = filter(None, line.split(' '))
            if len(line) > 4 and line[4].endswith('%'):
                try:
                    res['disk_usage'] = float(line[4].strip('%'))/100
                except ValueError:
                    pass
                    
    res['failures'] = conn_failure
    return res    

def monitor_cache_lifetime(minutes, retest = 10, ntest = -1,
                           cache_name = "memcaches", verbose = False):

    # list of list of active memcache test keys
    keys = []
    period = 60  # 1 minute cycle time
    data = DataLogger()
    
    # we'll create an independent connection to memcached for this test
    mc = Memcache(getattr(g, cache_name))

    counter = 0
    while ntest:

        if counter == 0 or (retest and counter % retest == 0):
            randstr = random.random()
            newkeys = [("%s_lifetime_%s_%d" % (cache_name, randstr, x), x+1)
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
                AppServiceMonitor.set_cache_lifetime(data, key = cache_name)
                # wipe out the list for removal by the subsequent filter
                while k: k.pop()

        # clear out any empty key lists
        if [] in keys:
            keys = filter(None, keys)
            ntest -= 1

