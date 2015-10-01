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

import base64
import boto
import hashlib
import hmac
import json
import os
import sys
import time

from pylons import app_globals as g


HADOOP_FOLDER_SUFFIX = '_$folder$'


def _to_path(bucket, key):
    if not bucket:
        raise ValueError
    return 's3://%s/%s' % (bucket, key)


def _from_path(path):
    """Return bucket and key names from an s3 path.

    Path of 's3://BUCKET/KEY/NAME' would return 'BUCKET', 'KEY/NAME'.

    """

    if not path.startswith('s3://'):
        raise ValueError('Bad S3 path %s' % path)

    r = path[len('s3://'):].split('/', 1)
    bucket = key = None

    if len(r) == 2:
        bucket, key = r[0], r[1]
    else:
        bucket = r[0]

    if not bucket:
        raise ValueError('Bad S3 path %s' % path)

    return bucket, key


def get_text_from_s3(s3_connection, path):
    """Read a file from S3 and return it as text."""
    bucket_name, key_name = _from_path(path)
    bucket = s3_connection.get_bucket(bucket_name)
    k = boto.s3.Key(bucket)
    k.key = key_name
    txt = k.get_contents_as_string()
    return txt


def mv_file_s3(s3_connection, src_path, dst_path):
    """Move a file within S3."""
    src_bucket_name, src_key_name = _from_path(src_path)
    dst_bucket_name, dst_key_name = _from_path(dst_path)

    src_bucket = s3_connection.get_bucket(src_bucket_name)
    k = boto.s3.Key(src_bucket)
    k.key = src_key_name
    k.copy(dst_bucket_name, dst_key_name)
    k.delete()


def s3_key_exists(s3_connection, path):
    bucket_name, key_name = _from_path(path)
    bucket = s3_connection.get_bucket(bucket_name)
    key = bucket.get_key(key_name)
    return bool(key)


def copy_to_s3(s3_connection, local_path, dst_path, verbose=False):
    def callback(trans, total):
        sys.stdout.write('%s/%s' % trans, total)
        sys.stdout.flush()

    dst_bucket_name, dst_key_name = _from_path(dst_path)
    bucket = s3_connection.get_bucket(dst_bucket_name)

    filename = os.path.basename(local_path)
    if not filename:
        return

    key_name = os.path.join(dst_key_name, filename)
    k = boto.s3.Key(bucket)
    k.key = key_name

    kw = {}
    if verbose:
        print 'Uploading %s to %s' % (local_path, dst_path)
        kw['cb'] = callback

    k.set_contents_from_filename(logfile, **kw)


def get_connection():
    return boto.connect_s3(g.S3KEY_ID or None, g.S3SECRET_KEY or None)


def get_key(bucket_name, key, connection=None):
    connection = connection or get_connection()
    bucket = connection.get_bucket(bucket_name)

    return bucket.get_key(key)

def get_keys(bucket_name, meta=False, connection=None, **kwargs):
    connection = connection or get_connection()
    bucket = connection.get_bucket(bucket_name)
    keys = bucket.get_all_keys(**kwargs)

    if not meta:
        return keys

    return [bucket.get_key(key.name)
            for key in keys]


def delete_keys(bucket_name, prefix, connection=None):
    connection = connection or get_connection()

    keys = get_keys(bucket_name, prefix=prefix, connection=connection)
    return connection.get_bucket(bucket_name).delete_keys(keys)


def _get_upload_policy(
        bucket, key, acl, ttl=60,
        success_action_redirect=None,
        success_action_status="201",
        content_type=None,
        max_content_length=((1024**2) * 3),
        storage_class="STANDARD",
        meta=None,
        connection=None,
    ):

    connection = connection or get_connection()
    meta = meta or {}

    expiration = time.gmtime(int(time.time() + ttl))
    conditions = []

    conditions.append({"bucket": bucket})

    if key.endswith("${filename}"):
        conditions.append(["starts-with", "$key", key[:-len("${filename}")]])
    else:
        conditions.append({"key": key})

    conditions.append({"acl": acl})
    conditions.append({"x-amz-storage-class": storage_class})

    if success_action_redirect:
        conditions.append([
            "starts-with",
            "$success_action_redirect",
            success_action_redirect,
        ])
    else:
        conditions.append({
            "success_action_status": success_action_status,
        })

    conditions.append([
        "content-length-range", 0, max_content_length])

    for key, value in meta.iteritems():
        conditions.append({key: value})

    if content_type:
        conditions.append({"content-type": content_type})

    return base64.b64encode(json.dumps({
        "expiration": time.strftime(boto.utils.ISO8601, expiration),
        "conditions": conditions,
    }))


def _get_upload_signature(
        policy,
        connection=None,
    ):

    connection = connection or get_connection()

    key = connection.provider.secret_key.encode("utf-8")
    hashed = hmac.new(key, policy, hashlib.sha1)
    return base64.encodestring(
        hashed.digest()).decode("utf-8").strip()


def get_post_args(
        bucket, key,
        acl="public-read",
        success_action_redirect=None,
        success_action_status="201",
        content_type=None,
        storage_class="STANDARD",
        meta=None,
        connection=None,
        **kwargs
    ):

    meta = meta or []
    connection = connection or get_connection()
    policy = _get_upload_policy(
        bucket=bucket,
        key=key,
        acl=acl,
        success_action_redirect=success_action_redirect,
        success_action_status=success_action_status,
        content_type=content_type,
        storage_class=storage_class,
        meta=meta,
        connection=connection,
    )
    signature = _get_upload_signature(
        policy, connection=connection)

    fields = []

    fields.append({
        "name": "AWSAccessKeyId",
        "value": connection.provider.access_key,
    })

    fields.append({
        "name": "acl",
        "value": acl,
    })

    fields.append({
        "name": "key",
        "value": key,
    })

    if success_action_redirect:
        fields.append({
            "name": "success_action_redirect",
            "value": success_action_redirect,
        })
    else:
        fields.append({
            "name": "success_action_status",
            "value": success_action_status,
        })

    fields.append({
        "name": "content-type",
        "value": content_type,
    })

    fields.append({
        "name": "x-amz-storage-class",
        "value": storage_class,
    })

    for key, value in meta.iteritems():
        fields.append({
            "name": key,
            "value": value,
        })

    fields.append({
        "name": "policy",
        "value": policy,
    })

    fields.append({
        "name": "signature",
        "value": signature,
    })

    return {
        "action": "//%s.%s" % (bucket, g.s3_media_domain),
        "fields": fields,
    }

