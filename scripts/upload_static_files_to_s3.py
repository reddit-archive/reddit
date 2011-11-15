#!/usr/bin/python

import os
import boto
import mimetypes

NEVER = 'Thu, 31 Dec 2037 23:59:59 GMT'

def upload(static_root, bucket_name):
    s3 = boto.connect_s3()
    bucket = s3.get_bucket(bucket_name)

    # build a list of files already in the bucket
    remote_files = {}
    for key in bucket.list():
        remote_files[key.name] = key.etag.strip('"')

    # upload local files not already in the bucket
    for root, dirs, files in os.walk(static_root):
        for file in files:
            absolute_path = os.path.join(root, file)

            key_name = os.path.relpath(absolute_path, start=static_root)

            type, encoding = mimetypes.guess_type(file)
            if not type:
                continue
            headers = {}
            headers['Expires'] = NEVER
            headers['Content-Type'] = type
            if encoding:
                headers['Content-Encoding'] = encoding

            key = bucket.new_key(key_name)
            with open(absolute_path, 'rb') as f:
                etag, base64_tag = key.compute_md5(f)

                # don't upload the file if it already exists unmodified in the bucket
                if remote_files.get(key_name, None) == etag:
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

    if len(sys.argv) < 3:
        print >> sys.stderr, "USAGE: %s static_root bucket_name" % sys.argv[0]
        sys.exit(1)

    upload(sys.argv[1], sys.argv[2])
