#!/usr/bin/python
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


import os
import mimetypes

from r2.lib.utils import read_static_file_config


NEVER = 'Thu, 31 Dec 2037 23:59:59 GMT'

mimetypes.encodings_map['.gzip'] = 'gzip'

def upload(config_file):
    bucket, config = read_static_file_config(config_file)

    # upload local files not already in the bucket
    for root, dirs, files in os.walk(config["static_root"]):
        for file in files:
            absolute_path = os.path.join(root, file)

            key_name = os.path.relpath(absolute_path,
                                       start=config["static_root"])

            type, encoding = mimetypes.guess_type(file)
            if not type:
                continue
            headers = {}
            headers['Expires'] = NEVER
            headers['Content-Type'] = type
            if encoding:
                headers['Content-Encoding'] = encoding

            existing_key = bucket.get_key(key_name)
            key = bucket.new_key(key_name)
            with open(absolute_path, 'rb') as f:
                etag, base64_tag = key.compute_md5(f)

                if existing_key and existing_key.etag.strip('"') == etag:
                    continue

                print "uploading", key_name, "to S3..."
                key.set_contents_from_file(
                    f,
                    headers=headers,
                    policy='public-read',
                    md5=(etag, base64_tag),
                )


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print >> sys.stderr, "USAGE: %s /path/to/config-file.ini" % sys.argv[0]
        sys.exit(1)

    upload(sys.argv[1])
