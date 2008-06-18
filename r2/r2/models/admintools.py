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

class AdminTools(object):
    def spam(self, thing):
        pass

    def report(self, thing):
        pass

    def add_thing(self, thing):
        pass

    def ban_info(self, thing):
        return {}

    def get_corrections(self, cls, min_date = None, max_date = None, limit = 50):
        return []

admintools = AdminTools()

def is_banned_IP(ip):
    return False

def is_banned_domain(dom):
    return False

def valid_thing(v, karma):
    return True

def valid_user(v, sr, karma):
    return True

def update_score(obj, up_change, down_change, new_valid_thing, old_valid_thing):
     obj._incr('_ups',   up_change)
     obj._incr('_downs', down_change)

def compute_votes(wrapper, item):
    wrapper.upvotes   = item._ups
    wrapper.downvotes = item._downs


try:
    from r2admin.models.admintools import *
except:
    pass


