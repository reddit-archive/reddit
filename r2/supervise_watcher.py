# "The contents of this file are subject to the Common Public Attribution
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
import os, re, sys
from datetime import datetime, timedelta

cache = g.cache

try:
    handle = open('/etc/hostname', 'r')
    host = handle.read().strip('\n')
    handle.close()
except:
    host = "UNDEFINED"

 
default_services = ['newreddit']
default_servers = g.monitored_servers 

class Service:
    maxlen = 300
    __slots__ = ['host', 'name', 'pid', 'load']


    def __init__(self, name, pid, age, time):
        self.host = host
        self.name = name
        self.pid = pid
        self.age = age
        self.time = time
        self._cpu = []
        self.load = 0
        self.mem = 0
        self.age = 0

    def __iter__(self):
        for x in self.__slots__:
            yield (x, getattr(self, x))

        yield ('last_seen', (datetime.now() - self.time).seconds)
        for t in (0, 5, 60, 300):
            yield ('cpu_%d' % t, self.cpu(t))
        yield ('mem', self.mem)
        yield ('age', self.age)
        

    def __str__(self):
        return ("%(host)s\t%(cpu_0)5.2f%%\t%(cpu_5)5.2f%%\t%(cpu_60)5.2f%%\t%(cpu_300)5.2f%%" + 
                "\t%(pid)s\t%(name)s\t(%(last_seen)s seconds)") % dict(self)

    def track_cpu(self, usage):
        self.time = datetime.now()
        self._cpu.append((usage, self.time))
        if len(self._cpu) > self.maxlen:
            self._cpu = self._cpu[-self.maxlen:]

    def track_mem(self, usage):
        self.mem = usage

    def track_age(self, usage):
        self.age = usage

    def cpu(self, interval = 60):
        time = datetime.now()
        if interval > 0:
            cpu = filter(lambda x: time - x[1] <= timedelta(0, interval), self._cpu)
        elif self._cpu:
            cpu = [self._cpu[-1]]
        else:
            cpu = []
        return sum(c[0] for c in cpu)/max(len(cpu), 1)

class Services:
    cache_key = "supervise_services_"

    def __init__(self, _host = host):
        self.last_update = None
        self._services = {}
        self._host = _host
        self.load = 0.
        
    
    def track(self, pid, cpu, mem, age):
        try:
            if isinstance(pid, str):
                pid = int(pid)
            if self._services.has_key(pid):
                self._services[pid].track_cpu(cpu)
                self._services[pid].track_mem(mem)
                self._services[pid].track_age(age)
        except ValueError:
            pass    
        
    def add(self, name, pid, age):
        self.last_update = datetime.now()
        if not self._services.has_key(pid):
            self._services[pid] = Service(name, pid, age, self.last_update)
        else:
            self._services[pid].time = self.last_update
            self._services[pid].age = age
   
    def __iter__(self):
        return self._services.itervalues()

    def get_cache(self):
        key = self.cache_key + str(self._host)
        res = cache.get(key)
        if isinstance(res, dict):
            services = res.get("services", [])
            self.load = res.get("load", 0)
        else:
            services = res
            self.load = services[0].get("load", 0) if services else 0

        return services

    def set_cache(self):
        key = self.cache_key + str(self._host)
        svs = [dict(s) for s in self]
        cache.set(key, dict(load = self.load, 
                            services = svs,
                            host = self._host))
    
    def clean_dead(self, age = 30):
        time = datetime.now()
        active = filter(lambda s: time - self._services[s].time <= timedelta(0, age), 
                        self._services.keys())
        existing = self._services.keys()
        for pid in existing:
            if pid not in active:
                del self._services[pid]

from r2.config.templates import tpm
from r2.lib.wrapped import Wrapped
tpm.add('service_page', 'html', file = "server_status_page.html")
tpm.add('service_page', 'htmllite', file = "server_status_page.htmllite")

class Service_Page(Wrapped):
    def __init__(self, machines = default_servers):
        self.services = [Services(m) for m in machines]
    def __repr__(self):
        return "service page"

def Alert(restart_list=['MEM','CPU']):
    import time
    import smtplib
    import re
    p=re.compile("/service/newreddit(\d+)\:")
    cache_key = 'already_alerted_'
    alert_recipients = ['nerds@reddit.com']
    alert_sender = 'nerds@reddit.com'
    smtpserver = 'nt03.wireddit.com'
    
    for m in default_servers:
        s = Services(m)
        services = s.get_cache() or []
        services.sort(lambda x, y: 1 if x['name'] > y['name'] else -1)
        for service in services:
            output = "\nCPU:   "
            #output += (str(service['host']) + " " + str(service['name']))
            pegged_count = 0
            need_restart = False

            # Check for pegged procs
            for x in (0, 5, 60, 300):
                val = service['cpu_' + str(x)]
                if val > 99:
                    pegged_count += 1
                output += " %6.2f%%" % val
            service_name = str(service['host']) + " " + str(service['name'])

            if (pegged_count > 3):
                if 'CPU' in restart_list:
                    need_restart = True

            # Check for out of memory situation
            output += "\nMEMORY: %6.2f%%" % service.get('mem', 0)
            mem_pegged = (service.get('mem', 0) > 20)
            if (mem_pegged):
                if 'MEM' in restart_list:
                    need_restart = True

            if (need_restart):
                mesg = ("To: nerds@gmail.com\n" + 
                        "Subject: " + service_name.replace("/service/","") 
                          +" needs attention\n\n" 
                        + service_name.replace("/service/","") 
                        + (" is out of mem: " if mem_pegged else " is pegged:" )
                        + output)
                m = p.match(service['name'])
                # If we can restart this process, we do it here
                if m:
                    proc_number = str(m.groups()[0])
                    cmd = "/usr/local/bin/push -h " + \
                        service['host'] + " -r " + proc_number
                    result = ""
                    result = os.popen3(cmd)[2].read()
                    # We override the other message to show we restarted it
                    mesg = "To: nerds@gmail.com\n" + "Subject: " + "Process " + \
                           proc_number + " on " + service['host'] + \
                           " was automatically restarted due to the following:\n\n" + \
                           output + "\n\n" + \
                           "Here was the output:\n" + result
                    # Uncomment this to disable restart messages
                    #mesg = ""
                last_alerted = cache.get(cache_key + service_name) or 0
                #last_alerted = 0
                if (time.time() - last_alerted < 300):
                    pass
                else:
                    cache.set(cache_key + service_name, time.time())
                    if mesg is not "":
                        session = smtplib.SMTP(smtpserver)
                        smtpresult = session.sendmail(alert_sender, 
                                                      alert_recipients, mesg)
                    #print mesg
                    #print "Email sent"
           
def Write(file = None, servers = default_servers):
    if file:
        handle = open(file, "w")
    else:
        handle = sys.stdout
    handle.write(Service_Page(servers).render())
    if file:
        handle.close()
        

def Run(srvname=None, loop = True, loop_time = 2):
    services = Services()        
    pidi = 0
    cpuid = 8
    memid = 9
    ageid = 10
    procid = 11
    text = re.compile('\S+')


    from time import sleep
    counter = 0
    while True:
        # reload the processes
        if counter % 10 == 0:
            handle = os.popen("/usr/local/bin/svstat /service/*")
            for line in handle:
                try:
                    name, status, blah, pid, time, label = line.split(' ')
                    pid = int(pid.strip(')'))
                    if not srvname or any(s in name for s in srvname):
                        services.add(name, pid, time)
                except ValueError:
                    pass
            services.clean_dead()
            handle.close()

        counter +=1
        cmd = ('/usr/bin/top -b -n 1 ' +
               ' '.join("-p%d"%x.pid for x in services))
        handle = os.popen(cmd)
        for line in handle:
            line = text.findall(line)
            try:
                services.track(line[pidi], float(line[cpuid]),
                               float(line[memid]), 
                               float(line[ageid].split(':')[0]))
            except (ValueError, IndexError):
                pass
        handle.close()

        handle = os.popen('/usr/bin/uptime')
        foo = handle.read()
        services.load=float(foo.split("average:")[1].strip(' ').split(',')[0])
        handle.close()

        res = ''
        services.set_cache()

        if loop: 
            sleep(loop_time)
        else:
            break

if __name__ == '__main__':
    Run(sys.argv[1:] if sys.argv[1:] else default_services)
