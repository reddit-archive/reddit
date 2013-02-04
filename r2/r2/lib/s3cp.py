#!/usr/bin/env python
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

import boto
from boto.s3.connection import S3Connection
from boto.s3.key import Key
from pylons import g

KEY_ID = g.S3KEY_ID
SECRET_KEY = g.S3SECRET_KEY

NEVER = 'Thu, 31 Dec 2037 23:59:59 GMT'

class S3Exception(Exception): pass

def send_file(bucketname, filename, content, content_type='text/plain', never_expire=False, replace=True, reduced_redundancy=False):
    # this function is pretty low-traffic, but if we start using it a
    # lot more we'll want to maintain a connection pool across the app
    # rather than connecting on every invocation

    # TODO: add ACL support instead of always using public-read

    # the "or None" business is so that a blank string becomes None to cause
    # boto to look for credentials in other places.
    connection = S3Connection(KEY_ID or None, SECRET_KEY or None)
    bucket = connection.get_bucket(bucketname, validate=False)
    k = bucket.new_key(filename)

    headers={'Content-Type': content_type}
    if never_expire:
        headers['Expires'] = NEVER

    k.set_contents_from_string(content, policy='public-read',
                               headers=headers,
                               replace=replace,
                               reduced_redundancy=reduced_redundancy)
