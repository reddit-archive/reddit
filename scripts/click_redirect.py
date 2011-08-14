#!/usr/bin/python
"""
A simple raw WSGI app to take click-tracking requests, verify
the hash to make sure they're valid, and redirect the client
accordingly.
"""

import time
import hashlib
import urlparse
from ConfigParser import RawConfigParser
from wsgiref.handlers import format_date_time

config = RawConfigParser()
config.read(['production.ini'])
tracking_secret = config.get('DEFAULT', 'tracking_secret')


def click_redirect(environ, start_response):
    if environ['REQUEST_METHOD'] != 'GET':
        start_response('405 Method Not Allowed', [])
        return

    if environ.get('PATH_INFO') != '/click':
        start_response('404 Not Found', [])
        return

    query = environ.get('QUERY_STRING', '')
    params = urlparse.parse_qs(query)

    try:
        destination = params['url'][0]
        ip = environ['REMOTE_ADDR']
    except KeyError:
        start_response('400 Bad Request', [])
        return

    try:
        hash = params['hash'][0]
        fullname = params['id'][0]
        expected_hash_text = ''.join((ip, fullname, tracking_secret))
        expected_hash = hashlib.sha1(expected_hash_text).hexdigest()
        assert hash == expected_hash
    except (KeyError, AssertionError):
        start_response('403 Forbidden', [])
        return

    now = format_date_time(time.time())
    start_response('301 Moved Permanently', [
        ('Location', destination),
        ('Date', now),
        ('Expires', now),
        ('Cache-Control', 'no-cache'),
        ('Pragma', 'no-cache'),
    ])
