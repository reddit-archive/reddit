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
from __future__ import with_statement
import cPickle as pickle
import os, shutil, time
from utils import Storage
from datetime import datetime, timedelta


class LoggedSlots(object):

    def __init__(self, logfile, **kw):
        for k, v in kw.iteritems():
            super(LoggedSlots, self).__setattr__(k, v)
        self.__logfile = logfile
        self.load_slots()
        
    def __setattr__(self, k, v):
        super(LoggedSlots, self).__setattr__(k, v)
        if k in self.__slots__:
            self.dump_slots()
        
    def load_slots(self):
        d = self._get_slots(self.__logfile)
        for k, v in d.iteritems():
            super(LoggedSlots, self).__setattr__(k, v)

    def dump_slots(self):
        if self.__logfile:
            with WithWriteLock(self.__logfile) as handle:
                d = {}
                for s in self.__slots__:
                    try:
                        d[s] = getattr(self, s)
                    except AttributeError:
                        continue
                pickle.dump(d, handle)

    @classmethod
    def _get_slots(self, file):
        if os.path.exists(file):
            with open(file) as handle:
                return Storage(pickle.load(handle))
        return Storage()
            
        

class WriteLockExistsException(): pass

class WithWriteLock():
    def __init__(self, file_name, mode = 'w', force = False, age = 60):
        self.fname = file_name
        self.lock_file = file_name + ".write_lock"
        self.time = datetime.now()
        self.handle = None
        self.created = True

        if self.exists():
            if force:
                self.destroy()
            elif not self.try_expire(age):
                raise WriteLockExistsException

        # back up the file to be written to
        if os.path.exists(self.fname):
            shutil.copyfile(self.fname, self.backup_file)
        # write out a lock file
        with open(self.lock_file, 'w') as handle:
            pickle.dump(self.time, handle)
        # lastly, open the file!
        self.handle = open(file_name, mode)

    def write(self, *a, **kw):
        self.handle.write(*a, **kw)
            

    @property
    def backup_file(self):
        return "%s-%s.bak" % (self.fname,
                              time.mktime(self.time.timetuple()))
        
    def exists(self):
        return os.path.exists(self.lock_file)

    def try_expire(self, age):
        '''destroys an existing lock file if it is more than age seconds old'''
        with open(self.lock_file, 'r') as handle:
            time = pickle.load(handle)
        if self.time - time > timedelta(0, age):
            self.destroy()
            return True
        return False

    def destroy(self):
        # close any open handles
        if self.handle:
            self.handle.close()
            self.handle = None

        # wipe the lock file and the back-up
        if self.created:
            self.created = False
            if self.exists():
                os.unlink(self.lock_file)
            if os.path.exists(self.backup_file):
                os.unlink(self.backup_file)

    def close(self):
        self.destroy()

    def rollback(self):
        # close any open handles
        if self.handle:
            self.handle.close()
            self.handle = None

        if self.created:
            # clobber any changes to the file with our archive
            if os.path.exists(self.backup_file):
                shutil.copyfile(self.backup_file, self.fname)

        #destroy as usual
        self.destroy()
                
    def __enter__(self):
        return self
    

    def __exit__(self, type, value, tb):
        if tb is None:
            self.close()
        else:
            self.rollback()

