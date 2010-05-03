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
# The Original Code is Reddit.
#
# The Original Developer is the Initial Developer.  The Initial Developer of the
# Original Code is CondeNet, Inc.
#
# All portions of the code written by CondeNet are Copyright (c) 2006-2010
# CondeNet, Inc. All Rights Reserved.
################################################################################

import base64, hmac, sha, os, sys, getopt
from datetime import datetime
from pylons import g,config

KEY_ID = g.S3KEY_ID
SECRET_KEY = g.S3SECRET_KEY

class S3Exception(Exception): pass

def make_header(verb, date, amz_headers, resource, content_type):
    content_md5 = ''

    #amazon headers
    lower_head = dict((key.lower(), val)
                      for key, val in amz_headers.iteritems())
    keys = lower_head.keys()
    keys.sort()
    amz_lst = ['%s:%s' % (key, lower_head[key]) for key in keys]
    amz_str = '\n'.join(amz_lst)

    s = '\n'.join((verb,
                   content_md5,
                   content_type,
                   date,
                   amz_str,
                   resource))

    h = hmac.new(SECRET_KEY, s, sha)
    return base64.encodestring(h.digest()).strip()
                   
def send_file(filename, resource, content_type, acl, rate, meter):
    date = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
    amz_headers = {'x-amz-acl': acl}

    auth_header = make_header('PUT', date, amz_headers, resource, content_type)

    params = ['-T', filename,
              '-H', 'x-amz-acl: %s' % amz_headers['x-amz-acl'],
              '-H', 'Authorization: AWS %s:%s' % (KEY_ID, auth_header),
              '-H', 'Date: %s' % date]

    if content_type:
        params.append('-H')
        params.append('Content-Type: %s' % content_type)

    if rate:
        params.append('--limit-rate')
        params.append(rate)

    if meter:
        params.append('-o')
        params.append('s3cp.output')
    else:
        params.append('-s')

    params.append('https://s3.amazonaws.com%s' % resource)

    exit_code = os.spawnlp(os.P_WAIT, 'curl', 'curl', *params)
    if exit_code:
        raise S3Exception(exit_code)

               
if __name__ == '__main__':
    options = "a:c:l:m"
    try:
        opts, args = getopt.getopt(sys.argv[1:], options)
    except:
        sys.exit(2)
        
    opts = dict(opts)

    send_file(args[0], args[1],
              opts.get('-c', ''),
              opts.get('-a', 'private'),
              opts.get('-l'),
              opts.has_key('-m'))
