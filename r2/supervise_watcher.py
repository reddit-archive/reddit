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
#!/usr/bin/env python
from pylons import g
import os, re, sys, socket, time, smtplib
import subprocess
from datetime import datetime, timedelta
from r2.lib.wrapped import Wrapped

host  = g.reddit_host
default_services = ['newreddit']

def is_db_machine(host):
    """
    Given a host name, checks the list of known DB machines to
    determine if the host is one of them.
    """
    ips = set(v for k,v in g._current_obj().__dict__.iteritems() 
              if k.endswith("db_host"))

    for ip in ips:
        name = socket.gethostbyaddr(ip)[0]
        if (name == host or ("." in host and name.endswith("." + host)) or
            name.endswith(host + ".")):
            return True

    return False


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
            return 0

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
        self.ip_conn = {}
        self.db_conn = {}
    

    def track(self, conn = 0, ip_conn = {}, db_conn = {}, vacuums = {}):

        #log the number of connections
        self.connections.add(conn)

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
        
        
class HostLogger(object):
    cache_key = "machine_datalog_data_"

    def __init__(self, host):
        self.host = host
        self.load = DataLogger()
        self.services = {}
        self.database = Database() if is_db_machine(host) else None

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
        
    def set_cache(self):
        key = self.cache_key + str(self.host)
        g.rendercache.set(key, self)

    @classmethod
    def from_cache(cls, host):
        key = cls.cache_key + str(host)
        return g.rendercache.get(key)

    def clean_dead(self, age = 10):
        time = datetime.now()
        for pid, s in list(self.services.iteritems()):
            t = s.last_update()
            if not t or t < time - timedelta(0, age):
                del self.services[pid]


    def monitor(self, srvname = None, loop = True, loop_time = 2,
                srv_params = {}, top_params = {}, db_params = {}):
        while True:
            # (re)populate the service listing
            for name, status, pid, t in supervise_list(**srv_params):
                if not srvname or any(s in name for s in srvname):
                    self.add_service(name, pid, t)

            # check process usage
            proc_info = run_top(proc_ids = self.service_pids(), **top_params)
            for pid, info in proc_info.iteritems():
                self.track(pid, **info)

            #check db usage:
            if self.database:
                self.database.track(**check_database(**db_params))

            handle = os.popen('/usr/bin/uptime')
            foo = handle.read()
            foo = foo.split("load average")[1].split(':')[1].strip(' ')
            self.load.add(float(foo.split(' ')[1].strip(',')))
            handle.close()



            self.clean_dead()
            self.set_cache()
            
            if loop:
                time.sleep(loop_time)
            else:
                break

    def __iter__(self):
        s = self.services
        pids = s.keys()
        pids.sort(lambda x, y: 1 if s[x].name > s[y].name else -1)
        for pid in pids:
            yield s[pid]
        

class AppServiceMonitor(Wrapped):
    def __init__(self, hosts = None):
        hosts = hosts or g.monitored_servers 
        self.hostlogs = [HostLogger.from_cache(host) for host in hosts]
        self.hostlogs = filter(lambda x: x, self.hostlogs)

    def __iter__(self):
        return iter(self.hostlogs)


def Alert(restart_list = ['MEM','CPU'],
          alert_recipients = ['nerds@reddit.com'],
          alert_sender = 'nerds@reddit.com',
          cpu_limit = 99, mem_limit = 10,
          smtpserver = 'nt03.wireddit.com', test = False):

    p = re.compile("newreddit(\d+)")
    cache_key = 'already_alerted_'
    
    for host in AppServiceMonitor(g.monitored_servers):
        for service in host:
            # cpu values
            cpu = [service.cpu(x) for x in (0, 5, 60, 300)]

            output =  "\nCPU:   " + ' '.join("%6.2f%%" % x for x in cpu)
            output += "\nMEMORY: %6.2f%%" % service.mem()

            service_name = "%s %s" % (host.host, service.name)

            # is this service pegged?
            mem_pegged = ('MEM' in restart_list and service.mem() > mem_limit)
            need_restart = (('CPU' in restart_list and
                             all(x >= cpu_limit for x in cpu)) or mem_pegged)
                            

            if (need_restart):
                mesg = ("To: " + ', '.join(alert_recipients) + 
                        "\nSubject: " + service_name +" needs attention\n\n" 
                        + service_name
                        + (" is out of mem: " if mem_pegged else " is pegged:" )
                        + output)
                m = p.match(service.name)
                # If we can restart this process, we do it here
                if m:
                    proc_number = str(m.groups()[0])
                    cmd = "/usr/local/bin/push -h " + \
                        host.host + " -r " + proc_number
                    if test:
                        print ("would have restarted the app with command '%s'"
                               % cmd)
                    else:
                        result = os.popen3(cmd)[2].read()
                        # We override the other message to show we restarted it
                        mesg = ("To: nerds@gmail.com\n" + 
                                "Subject: " + "Process " + 
                                proc_number + " on " + host.host + 
                                " was automatically restarted " +
                                "due to the following:\n\n" + 
                                output + "\n\n" + 
                                "Here was the output:\n" + result)
                    # Uncomment this to disable restart messages
                    #mesg = ""
                last_alerted = g.rendercache.get(cache_key + service_name) or 0
                #last_alerted = 0
                if mesg is not "":
                    if test:
                        print "would have sent email\n '%s'" % mesg
                    elif (time.time() - last_alerted > 300):
                        g.rendercache.set(cache_key + service_name, time.time())
                        session = smtplib.SMTP(smtpserver)
                        smtpresult = session.sendmail(alert_sender, 
                                                    alert_recipients,
                                                      mesg)
                        session.quit()
           

re_text = re.compile('\S+')
def run_top(proc_ids = [], name = '', exe = "/usr/bin/top"):
    pidi = 0
    cpuid = 8
    memid = 9
    ageid = 10
    procid = 11

    if not os.path.exists(exe):
        raise ValueError, "bad executable specified for top"

    cmd = [exe, '-b', '-n1'] + ["-p%d" % x for x in proc_ids]

    handle = subprocess.Popen(cmd, stdout = subprocess.PIPE,
                              stderr = subprocess.PIPE)
    if handle.wait():
        cmd = [exe, '-l', '1', '-p',
               "^aaaaa ^nnnnnnnnn X X X X X X ^ccccc 0.0" +
               " ^wwwwwwwwwww ^bbbbbbbbbbbbbbb"]
        handle = subprocess.Popen(cmd, stdout = subprocess.PIPE,
                                  stderr = subprocess.PIPE)
        if handle.wait():
            raise ValueError, "failed to run top"

    proc_ids = set(map(int, proc_ids))
    res = {}
    for line in handle.communicate()[0].split('\n'):
        line = re_text.findall(line)
        try:
            pid = int(line[pidi])
            n = line[-1]
            if (n.startswith(name) and
                (not proc_ids or int(pid) in proc_ids)):
                res[pid] =  dict(cpu = float(line[cpuid]),
                                 mem = float(line[memid]),
                                 age = float(line[ageid].split(':')[0]),
                                 name = n)
        except (ValueError, IndexError):
            pass
    return res


def supervise_list(exe = "/usr/local/bin/svstat", path = '/service/'):
    handle = os.popen("%s %s*" % (exe, path))
    for line in handle:
        try:
            name, status, blah, pid, time, label = line.split(' ')[:6]
            name = name[len(path):].strip(':')
            if status == 'up':
                pid = int(pid.strip(')'))
                time = int(time)
            else:
                pid = -1
                time = 0
            yield (name, status, pid, time)
        except ValueError:
            pass
    handle.close()

def check_database(proc = "postgres", check_vacuum = True, user='ri'):
    handle = os.popen("ps auxwww | grep ' %s'" %proc)
    lines = [l.strip() for l in handle]
    handle.close()

    by_ip = {}
    by_db = {}
    total = 0
    for line in lines:
        line = re_text.findall(line)[10:]
        if line[0].startswith(proc) and len(line) > 4:
            db = line[2]
            try:
                ip, port = line[3].strip(')').split('(')
            except ValueError:
                ip = '127.0.0.1'

            by_ip[ip] = by_ip.get(ip, 0) + 1
            by_db[db] = by_db.get(db, 0) + 1
            total += 1

    vacuums = {}
    if check_vacuum:
        vac = ("(echo '\t'; echo 'select * from active;') " +
               "| psql -U %(user)s %(db)s | grep -i '| vacuum'")
        for db in by_db:
            handle = os.popen(vac % dict(user=user, db=db))
            vacuums[db] = bool(handle.read())
            handle.close()
                            
    return dict(conn = total,
                ip_conn = by_ip,
                db_conn = by_db,
                vacuums = vacuums)


def Run(*a, **kw):
    HostLogger(g.reddit_host).monitor(*a, **kw)

def Test(num, load = 1., pid = 0):
    services = Services()
    for i in xrange(num):
        name = 'testproc' + str(i)
        p = i or pid
        services.add(name, p, "10")
        
        services.track(p, 100. * (i+1) / (num),
                       20. * (i+1) / num, 1.)
    services.load = load
    services.set_cache()

if __name__ == '__main__':
    Run(sys.argv[1:] if sys.argv[1:] else default_services)
