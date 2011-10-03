#!/usr/bin/python

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
    destination = request.args['url']
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
