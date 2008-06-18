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
import socket, cPickle as pickle
from threading import Thread
from SocketServer import DatagramRequestHandler, StreamRequestHandler, ThreadingMixIn, UDPServer, TCPServer

class CustomThreadingMixIn(ThreadingMixIn):
    """Mix-in class to handle each request in a new thread."""
    
    def __init__(self, thread_class = Thread):
        self.thread_class = thread_class

    def process_request(self, request, client_address):
        """Start a new thread to process the request."""
        t = self.thread_class(target = self.process_request_thread,
                              args = (request, client_address))
        if self.daemon_threads:
            t.setDaemon (1)
            t.start()
            

class Responses:
    OK, ERROR = range(2)

class SimpleHandler:
    def handle(self):
        try:
            fn_name, a, kw = pickle.load(self.rfile)
            fn = getattr(self.server.container, fn_name)
            res = (Responses.OK, fn(*a, **kw))
        except Exception, e:
            res = (Responses.ERROR, e)
        try:
            self.wfile.write(pickle.dumps(res, -1))
        except:
            res = (Responses.ERROR, 'Error while pickling.' )
            self.wfile.write(pickle.dumps(res, -1))

class SimpleUDPHandler(SimpleHandler, DatagramRequestHandler): pass
class SimpleTCPHandler(SimpleHandler, StreamRequestHandler): pass

class ThreadedUDPServer(CustomThreadingMixIn, UDPServer): 
    def __init__(self, server_address, RequestHandlerClass, container,
                 thread_class = Thread):
        UDPServer.__init__(self, server_address, RequestHandlerClass)
        CustomThreadingMixIn.__init__(self, thread_class)
        self.container = container
        self.daemon_threads = True

class ThreadedTCPServer(CustomThreadingMixIn, TCPServer): 
    def __init__(self, server_address, RequestHandlerClass, container,
                 thread_class = Thread):
        self.allow_reuse_address = True
        TCPServer.__init__(self, server_address, RequestHandlerClass)
        CustomThreadingMixIn.__init__(self, thread_class)
        self.container = container
        self.daemon_threads = True


class Server:
    def __init__(self, container, addr='', port=5000,
                 daemon=True, tcp=False, thread_class = Thread):
        if tcp:
            self.s = ThreadedTCPServer((addr, port), SimpleTCPHandler,
                                       container, thread_class)
        else:
            self.s = ThreadedUDPServer((addr, port), SimpleUDPHandler,
                                       container, thread_class)

        self.handle_thread = thread_class(target = self.s.serve_forever)
        self.handle_thread.setDaemon(daemon)
        self.handle_thread.start()


class RemoteCall:
    def __init__(self, client, response_required):
        self.client = client
        self.response_required = response_required

    def __getattr__(self, attr):
        def fn(*a, **kw):
            return self.client.send(self.response_required, attr, a, kw)
        return fn

class Client:
    def __init__(self, host='localhost', port=5000, tcp=False):
        self.conninfo = (host, port)
        self.call = RemoteCall(self, True)
        self.call_nr = RemoteCall(self, False)
        self.tcp = tcp

    def send(self, response_required, fn, a, kw):
        msg = pickle.dumps((fn, a, kw), -1)

        #get socket + send
        if self.tcp:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.connect(self.conninfo)
            except:
                return
            s.send(msg)
        else:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(10)
            s.sendto(msg, self.conninfo)

        if response_required:
            infile = s.makefile('rb')
            error_code, res = pickle.load(infile)
            #close
            try:
                if self.tcp: s.close()
            except: pass
            #return
            if error_code == Responses.OK:
                return res
            else:
                raise Exception, res
        elif self.tcp:
            try:
                s.close()
            except: pass

class TH:
    def add(self, x,y):
        return x + y

    def echo(self, str):
        return str

#s = Server(TH)
#c = Client()
#print c.call.add(1,2)

def test_length(client):
    x = 0
    while True:
        print len(client.call.echo(['x' for i in range(x)]))
        x += 100

def perf_test(client):
    for x in range(1000):
        client.call.echo('test')
