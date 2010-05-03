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
import os, re, sys, time, smtplib
from r2.lib.services import AppServiceMonitor

def Alert(restart_list = ['MEM','CPU'],
          alert_recipients = ['nerds@reddit.com'],
          alert_sender = 'nerds@reddit.com',
          cpu_limit = 99, mem_limit = 8,
          smtpserver = 'nt03.wireddit.com', test = False):

    p = re.compile("newreddit(\d+)")
    cache_key = 'already_alerted_'
    from pylons import g
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

def Run(srvname, *a, **kw):
    args = {}
    if kw.has_key('queue_length_max'):
        args['queue_length_max'] = kw.pop('queue_length_max')
    AppServiceMonitor(**args).monitor(srvname, *a, **kw)

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
    Run(sys.argv[1:] if sys.argv[1:] else ['newreddit'])
