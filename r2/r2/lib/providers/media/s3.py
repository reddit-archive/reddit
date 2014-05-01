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
# All portions of the code written by reddit are Copyright (c) 2006-2014 reddit
# Inc. All Rights Reserved.
###############################################################################

import mimetypes
import os

import boto

from pylons import g

from r2.lib.configparse import ConfigValue
from r2.lib.providers.media import MediaProvider


_NEVER = "Thu, 31 Dec 2037 23:59:59 GMT"
_S3_DOMAIN = "s3.amazonaws.com"


class S3MediaProvider(MediaProvider):
    """A media provider using Amazon S3.

    Credentials for uploading objects can be provided via `S3KEY_ID` and
    `S3SECRET_KEY`. If not provided, boto will search for credentials in
    alternate venues including environment variables and EC2 instance roles if
    on Amazon EC2.

    The `s3_media_direct` option configures how URLs are generated. When true,
    URLs will use Amazon's domain name meaning a zero-DNS configuration. If
    false, the bucket name will be assumed to be a valid domain name that is
    appropriately CNAME'd to S3 and URLs will be generated accordingly.

    If more than one bucket is provided in `s3_media_buckets`, items will be
    sharded out to the various buckets based on their filename. This allows for
    hostname parallelization in the non-direct HTTP case.

    """
    config = {
        ConfigValue.str: [
            "S3KEY_ID",
            "S3SECRET_KEY",
        ],
        ConfigValue.bool: [
            "s3_media_direct",
        ],
        ConfigValue.tuple: [
            "s3_media_buckets",
        ],
    }

    def put(self, name, contents):
        # choose a bucket based on the filename
        name_without_extension = os.path.splitext(name)[0]
        index = ord(name_without_extension[-1]) % len(g.s3_media_buckets)
        bucket_name = g.s3_media_buckets[index]

        # guess the mime type
        mime_type, encoding = mimetypes.guess_type(name)

        # send the key
        s3 = boto.connect_s3(g.S3KEY_ID or None, g.S3SECRET_KEY or None)
        bucket = s3.get_bucket(bucket_name, validate=False)
        key = bucket.new_key(name)
        key.set_contents_from_string(
            contents,
            headers={
                "Content-Type": mime_type,
                "Expires": _NEVER,
            },
            policy="public-read",
            reduced_redundancy=True,
            replace=True,
        )

        if g.s3_media_direct:
            return "http://%s/%s/%s" % (_S3_DOMAIN, bucket_name, name)
        else:
            return "http://%s/%s" % (bucket_name, name)

    def convert_to_https(self, http_url):
        """Convert an HTTP URL on S3 to an HTTPS URL.

        This currently assumes that no HTTPS-configured CDN is present, so
        HTTPS URLs must be direct-S3 URLs so that we can use Amazon's certs.

        """
        if http_url.startswith("http://%s" % _S3_DOMAIN):
            # it's already a direct url, just change scheme
            return http_url.replace("http://", "https://")
        else:
            # an indirect url, put the s3 domain in there too
            return http_url.replace("http://", "https://%s/" % _S3_DOMAIN)
