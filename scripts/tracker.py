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
"""
This is a tiny Flask app used for a couple of self-serve ad tracking
mechanisms. The URLs it provides are:

/fetch-trackers

    Given a list of Ad IDs, generate tracking hashes specific to the user's
    IP address. This must run outside the original request because the HTML
    may be cached by the CDN.

/click

    Promoted links have their URL replaced with a /click URL by the JS
    (after a call to /fetch-trackers). Redirect to the actual URL after logging
    the click. This must be run in a place whose logs are stored for traffic
    analysis.

For convenience, the script can compile itself into a Zip archive suitable for
use on Amazon Elastic Beanstalk (and possibly other systems).

"""


import cStringIO
import hashlib
import time

from ConfigParser import RawConfigParser
from wsgiref.handlers import format_date_time

from flask import Flask, request, json, make_response, abort, redirect


application = Flask(__name__)
MAX_FULLNAME_LENGTH = 128  # can include srname and codename, leave room
REQUIRED_PACKAGES = [
    "flask",
]


class ApplicationConfig(object):
    """A thin wrapper around ConfigParser that remembers what we read.

    The remembered settings can then be written out to a minimal config file
    when building the Elastic Beanstalk zipfile.

    """
    def __init__(self):
        self.input = RawConfigParser()
        with open("production.ini") as f:
            self.input.readfp(f)
        self.output = RawConfigParser()

    def get(self, section, key):
        value = self.input.get(section, key)

        # remember that we needed this configuration value
        if (section.upper() != "DEFAULT" and
            not self.output.has_section(section)):
            self.output.add_section(section)
        self.output.set(section, key, value)

        return value

    def to_config(self):
        io = cStringIO.StringIO()
        self.output.write(io)
        return io.getvalue()


config = ApplicationConfig()
tracking_secret = config.get('DEFAULT', 'tracking_secret')
adtracker_url = config.get('DEFAULT', 'adtracker_url')


def jsonpify(callback_name, data):
    data = callback_name + '(' + json.dumps(data) + ')'
    response = make_response(data)
    response.mimetype = 'text/javascript'
    return response


def get_client_ip():
    """Figure out the IP address of the remote client.

    If the remote address is on the 10.* network, we'll assume that it is a
    trusted load balancer and that the last component of X-Forwarded-For is
    trustworthy.

    """

    if request.remote_addr.startswith("10."):
        # it's a load balancer, use x-forwarded-for
        return request.access_route[-1]
    else:
        # direct connection to someone outside
        return request.remote_addr


@application.route("/")
def healthcheck():
    return "I am healthy."


@application.route('/fetch-trackers')
def fetch_trackers():
    ip = get_client_ip()
    jsonp_callback = request.args['callback']
    ids = request.args.getlist('ids[]')

    if len(ids) > 32:
        abort(400)

    hashed = {}
    for fullname in ids:
        if len(fullname) > MAX_FULLNAME_LENGTH:
            continue
        text = ''.join((ip, fullname, tracking_secret))
        hashed[fullname] = hashlib.sha1(text).hexdigest()
    return jsonpify(jsonp_callback, hashed)


@application.route('/click')
def click_redirect():
    ip = get_client_ip()
    destination = request.args['url'].encode('utf-8')
    fullname = request.args['id']
    observed_hash = request.args['hash']

    expected_hash_text = ''.join((ip, fullname, tracking_secret))
    expected_hash = hashlib.sha1(expected_hash_text).hexdigest()

    if expected_hash != observed_hash:
        abort(403)

    now = format_date_time(time.time())
    response = redirect(destination)
    response.headers['Cache-control'] = 'no-cache'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Date'] = now
    response.headers['Expires'] = now
    return response


if __name__ == "__main__":
    # package up for elastic beanstalk
    import zipfile

    with zipfile.ZipFile("/tmp/tracker.zip", "w", zipfile.ZIP_DEFLATED) as zip:
        zip.write(__file__, "application.py")
        zip.writestr("production.ini", config.to_config())
        zip.writestr("requirements.txt", "\n".join(REQUIRED_PACKAGES) + "\n")
