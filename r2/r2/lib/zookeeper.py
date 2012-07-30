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
# All portions of the code written by reddit are Copyright (c) 2006-2012 reddit
# Inc. All Rights Reserved.
###############################################################################

import functools

from kazoo.client import KazooClient
from kazoo.security import make_digest_acl


def connect_to_zookeeper(hostlist, credentials):
    """Create a connection to the ZooKeeper ensemble.

    If authentication credentials are provided (as a two-tuple: username,
    password), we will ensure that they are provided to the server whenever we
    establish a connection.

    """

    client = KazooClient(hostlist,
                         timeout=5,
                         max_retries=3)

    # convenient helper function for making credentials
    client.make_acl = functools.partial(make_digest_acl, *credentials)

    client.connect()
    client.add_auth("digest", ":".join(credentials))
    return client
