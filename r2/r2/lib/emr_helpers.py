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
# The Original Code is reddit.
#
# The Original Developer is the Initial Developer.  The Initial Developer of
# the Original Code is reddit Inc.
#
# All portions of the code written by reddit are Copyright (c) 2006-2013 reddit
# Inc. All Rights Reserved.
###############################################################################

from copy import copy
import datetime

from pylons import g

from r2.lib.memoize import memoize
from r2.lib.utils import storage

LIVE_STATES = ['RUNNING', 'STARTING', 'WAITING', 'BOOTSTRAPPING']
COMPLETED = 'COMPLETED'
PENDING = 'PENDING'
NOTFOUND = 'NOTFOUND'


@memoize('emr_describe_jobflows', time=30, timeout=60)
def describe_jobflows_cached(emr_connection):
    """Return a list of jobflows on this connection.

    It's good to cache this information because hitting AWS too often can
    result in rate limiting, and it's not particularly detrimental to have
    slightly out of date information in most cases. Non-running jobflows and
    information we don't need are discarded to reduce the size of cached data.

    """

    jobflows = emr_connection.describe_jobflows()

    r_jobflows = []
    for jf in jobflows:
        # skip old not live jobflows
        d = jf.steps[-1].creationdatetime.split('T')[0]
        last_step_start = datetime.datetime.strptime(d, '%Y-%m-%d').date()
        now = datetime.datetime.now().date()
        if (jf.state not in LIVE_STATES and
            now - last_step_start > datetime.timedelta(2)):
            continue

        # keep only fields we need
        r_jf = storage(name=jf.name,
                       jobflowid=jf.jobflowid,
                       state=jf.state)
        r_bootstrapactions = []
        for i in jf.bootstrapactions:
            s = storage(name=i.name,
                        path=i.path,
                        args=[a.value for a in i.args])
            r_bootstrapactions.append(s)
        r_jf['bootstrapactions'] = r_bootstrapactions
        r_steps = []
        for i in jf.steps:
            s = storage(name=i.name,
                        state=i.state,
                        jar=i.jar,
                        args=[a.value for a in i.args])
            r_steps.append(s)
        r_jf['steps'] = r_steps
        r_instancegroups = []
        for i in jf.instancegroups:
            s = storage(name=i.name,
                        instancegroupid=i.instancegroupid,
                        instancerequestcount=i.instancerequestcount)
            r_instancegroups.append(s)
        r_jf['instancegroups'] = r_instancegroups
        r_jobflows.append(r_jf)
    return r_jobflows


def update_jobflows_cached(emr_connection):
    r = describe_jobflows_cached(emr_connection, _update=True)


def describe_jobflows_by_ids(emr_connection, jobflow_ids, _update=False):
    g.reset_caches()
    jobflows = describe_jobflows_cached(emr_connection, _update=_update)
    return [jf for jf in jobflows if jf.jobflowid in jobflow_ids]


def describe_jobflows_by_state(emr_connection, states, _update=False):
    g.reset_caches()
    jobflows = describe_jobflows_cached(emr_connection, _update=_update)
    return [jf for jf in jobflows if jf.state in states]


def describe_jobflows(emr_connection, _update=False):
    g.reset_caches()
    jobflows = describe_jobflows_cached(emr_connection, _update=_update)
    return jobflows


def describe_jobflow(emr_connection, jobflow_id, _update=False):
    r = describe_jobflows_by_ids(emr_connection, [jobflow_id], _update=_update)
    if r:
        return r[0]


def get_compatible_jobflows(emr_connection, bootstrap_actions=None,
                            setup_steps=None):
    """Return jobflows that have specified bootstrap actions and setup steps.

    Assumes there are no conflicts with bootstrap actions or setup steps:
    a jobflow is compatible if it contains at least the requested
    bootstrap_actions and setup_steps (may contain additional).

    """

    bootstrap_actions = bootstrap_actions or []
    setup_steps = setup_steps or []

    # update list of running jobflows--ensure we don't pick a recently dead one
    update_jobflows_cached(emr_connection)

    jobflows = describe_jobflows_by_state(emr_connection, LIVE_STATES,
                                          _update=True)
    if not jobflows:
        return []

    required_bootstrap_actions = set((i.name, i.path, tuple(sorted(i.args())))
                                     for i in bootstrap_actions)
    required_setup_steps = set((i.name, i.jar(), tuple(sorted(i.args())))
                               for i in setup_steps)

    if not required_bootstrap_actions and not required_setup_steps:
        return jobflows

    running = []
    for jf in jobflows:
        extant_bootstrap_actions = set((i.name, i.path, tuple(sorted(i.args)))
                                       for i in jf.bootstrapactions)
        if not (required_bootstrap_actions <= extant_bootstrap_actions):
            continue

        extant_setup_steps = set((i.name, i.jar, tuple(sorted(i.args)))
                                 for i in jf.steps)
        if not (required_setup_steps <= extant_setup_steps):
            continue
        running.append(jf)
    return running


def get_step_state(emr_connection, jobflowid, step_name):
    """Return the state of a step.

    If jobflowid/step_name combination is not unique this will return the state
    of the most recent step.

    """

    jobflow = describe_jobflow(emr_connection, jobflowid)
    if not jobflow:
        return NOTFOUND

    for step in reversed(jobflow.steps):
        if step.name == step_name:
            return step.state
    else:
        return NOTFOUND


def get_jobflow_by_name(emr_connection, jobflow_name):
    """Return the most recent jobflow with specified name."""
    jobflows = describe_jobflows_by_state(emr_connection, LIVE_STATES,
                                          _update=True)
    for jobflow in jobflows:
        if jobflow.name == jobflow_name:
            return jobflow
    else:
        return None


def terminate_jobflow(emr_connection, jobflow_name):
    jobflow = get_jobflow_by_name(emr_connection, jobflow_name)
    if jobflow:
        emr_connection.terminate_jobflow(jobflow.jobflowid)


def modify_slave_count(emr_connection, jobflow_name, num_slaves=1):
    jobflow = get_jobflow_by_name(emr_connection, jobflow_name)
    if not jobflow:
        return

    slave_instancegroupid = None
    slave_instancerequestcount = 0
    for instance in jobflow.instancegroups:
        if instance.name == 'slave':
            slave_instancegroupid = instance.instancegroupid
            slave_instancerequestcount = instance.instancerequestcount
            break

    if slave_instancegroupid and slave_instancerequestcount != num_slaves:
        print ('Modifying slave instance count of %s (%s -> %s)' %
               (jobflow_name, slave_instancerequestcount, num_slaves))
        emr_connection.modify_instance_groups(slave_instancegroupid,
                                              num_slaves)


class EmrJob(object):
    def __init__(self, emr_connection, name, steps=[], setup_steps=[],
                 bootstrap_actions=[], log_uri=None, keep_alive=True,
                 ec2_keyname=None, hadoop_version='0.20.205',
                 ami_version='latest', master_instance_type='m1.small',
                 slave_instance_type='m1.small', num_slaves=1,
                 visible_to_all_users=True):

        self.jobflowid = None
        self.conn = emr_connection
        self.name = name
        self.steps = steps
        self.setup_steps = setup_steps
        self.bootstrap_actions = bootstrap_actions
        self.log_uri = log_uri
        self.enable_debugging = bool(log_uri)
        self.keep_alive = keep_alive
        self.ec2_keyname = ec2_keyname
        self.hadoop_version = hadoop_version
        self.ami_version = ami_version
        self.master_instance_type = master_instance_type
        self.slave_instance_type = slave_instance_type
        self.num_instances = num_slaves + 1
        self.visible_to_all_users = visible_to_all_users

    def run(self):
        steps = copy(self.setup_steps)
        steps.extend(self.steps)

        job_flow_args = dict(name=self.name,
            steps=steps, bootstrap_actions=self.bootstrap_actions,
            keep_alive=self.keep_alive, ec2_keyname=self.ec2_keyname,
            hadoop_version=self.hadoop_version, ami_version=self.ami_version,
            master_instance_type=self.master_instance_type,
            slave_instance_type=self.slave_instance_type,
            num_instances=self.num_instances,
            enable_debugging=self.enable_debugging,
            log_uri=self.log_uri,
            visible_to_all_users=self.visible_to_all_users)

        self.jobflowid = self.conn.run_jobflow(**job_flow_args)
        return

    @property
    def jobflow_state(self):
        if self.jobflowid:
            return describe_jobflow(self.conn, self.jobflowid).state
        else:
            return NOTFOUND

    def terminate(self):
        terminate_jobflow(self.conn, self.name)

    def modify_slave_count(self, num_slaves=1):
        modify_slave_count(self.conn, self.name, num_slaves)


class EmrException(Exception):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg
