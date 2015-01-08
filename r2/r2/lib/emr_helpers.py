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
# All portions of the code written by reddit are Copyright (c) 2006-2015 reddit
# Inc. All Rights Reserved.
###############################################################################

from copy import copy

from pylons import g

from r2.lib.memoize import memoize

LIVE_STATES = ['RUNNING', 'STARTING', 'WAITING', 'BOOTSTRAPPING']
COMPLETED = 'COMPLETED'
PENDING = 'PENDING'
NOTFOUND = 'NOTFOUND'


def get_compatible_jobflows(emr_connection, bootstrap_actions=None,
                            setup_steps=None):
    """Return jobflows that have specified bootstrap actions and setup steps.

    Assumes there are no conflicts with bootstrap actions or setup steps:
    a jobflow is compatible if it contains at least the requested
    bootstrap_actions and setup_steps (may contain additional).

    """

    bootstrap_actions = bootstrap_actions or []
    setup_steps = setup_steps or []

    jobflows = emr_connection.describe_jobflows(states=LIVE_STATES)
    if not jobflows:
        return []

    # format of step objects returned from describe_jobflows differs from those
    # created locally, so they must be compared carefully
    def args_tuple_emr(step):
        return tuple(sorted(arg.value for arg in step.args))

    def args_tuple_local(step):
        return tuple(sorted(step.args()))

    required_bootstrap_actions = {(step.name, step.path, args_tuple_local(step))
                                  for step in bootstrap_actions}
    required_setup_steps = {(step.name, step.jar(), args_tuple_local(step))
                            for step in setup_steps}

    if not required_bootstrap_actions and not required_setup_steps:
        return jobflows

    running = []
    for jf in jobflows:
        extant_bootstrap_actions = {(step.name, step.path, args_tuple_emr(step))
                                    for step in jf.bootstrapactions}
        if not (required_bootstrap_actions <= extant_bootstrap_actions):
            continue

        extant_setup_steps = {(step.name, step.jar, args_tuple_emr(step))
                              for step in jf.steps}
        if not (required_setup_steps <= extant_setup_steps):
            continue
        running.append(jf)
    return running


@memoize('get_step_states', time=60, timeout=60)
def get_step_states(emr_connection, jobflowid):
    """Return the names and states of all steps in the jobflow.

    Memoized to prevent ratelimiting.

    """

    jobflow = emr_connection.describe_jobflow(jobflowid)

    if jobflow:
        return [(step.name, step.state) for step in jobflow.steps]
    else:
        return []


def get_step_state(emr_connection, jobflowid, step_name, update=False):
    """Return the state of a step.

    If jobflowid/step_name combination is not unique this will return the state
    of the most recent step.

    """

    g.reset_caches()
    steps = get_step_states(emr_connection, jobflowid, _update=update)

    for name, state in reversed(steps):
        if name == step_name:
            return state
    else:
        return NOTFOUND


def get_jobflow_by_name(emr_connection, jobflow_name):
    """Return the most recent jobflow with specified name."""
    jobflows = emr_connection.describe_jobflows(states=LIVE_STATES)

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
                 ec2_keyname=None, hadoop_version='1.0.3',
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
            return self.conn.describe_jobflow(self.jobflowid).state
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
