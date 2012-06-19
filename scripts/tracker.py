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
# All portions of the code written by reddit are Copyright (c) 2006-2012 reddit
# Inc. All Rights Reserved.
###############################################################################


import time
import hashlib
from ConfigParser import RawConfigParser
from wsgiref.handlers import format_date_time

from flask import Flask, request, json, make_response, abort, redirect

application = Flask(__name__)

# fullname can include the sr name and a codename, leave room for those
MAX_FULLNAME_LENGTH = 128

def jsonpify(callback_name, data):
    data = callback_name + '(' + json.dumps(data) + ')'
    response = make_response(data)
    response.mimetype = 'text/javascript'
    return response

config = RawConfigParser()
config.read(['production.ini'])
tracking_secret = config.get('DEFAULT', 'tracking_secret')
adtracker_url = config.get('DEFAULT', 'adtracker_url')

@application.route('/fetch-trackers')
def fetch_trackers():
    ip = request.environ['REMOTE_ADDR']
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
    ip = request.environ['REMOTE_ADDR']
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
    application.run()
