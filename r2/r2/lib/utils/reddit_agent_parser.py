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
# All portions of the code written by reddit are Copyright (c) 2006-2016 reddit
# Inc. All Rights Reserved.
###############################################################################

from httpagentparser import (
    AndroidBrowser,
    Browser,
    detect as de,
    DetectorBase,
    detectorshub)
import re
from inspect import isclass


def register_detector(cls):
    """Collector of all the reddit detectors."""
    detectorshub.register(cls())
    return cls


class RedditDetectorBase(DetectorBase):
    agent_string = None
    version_string = '(\.?\d+)*'

    def __init__(self):
        if self.agent_string:
            self.agent_regex = re.compile(self.agent_string.format(
                look_for=self.look_for, version_string=self.version_string))
        else:
            self.agent_regex = None

        self.version_regex = re.compile('(?P<version>{})'.format(
            self.version_string))

    def getVersion(self, agent, word):
        match = None
        if self.agent_regex:
            match = self.agent_regex.search(agent)

        if not match:
            match = self.version_regex.search(agent)

        if match and 'version' in match.groupdict().keys():
            return match.group('version')

    def detect(self, agent, result):
        detected = super(RedditDetectorBase, self).detect(agent, result)

        if not detected or not self.agent_regex:
            return detected

        match = self.agent_regex.search(agent)
        groups = match.groupdict()
        platform_name = groups.get('platform')
        version = groups.get('pversion')

        if platform_name:
            platform = {}
            platform['name'] = platform_name
            if version:
                platform['version'] = version
            result['platform'] = platform

        if self.is_app:
            result['app_name'] = result['browser']['name']

        return True


class RedditBrowser(RedditDetectorBase, Browser):
    """Base class for all reddit specific browsers."""
    # is_app denotes a client that is a native mobile application, but not a
    # browser.
    is_app = False


@register_detector
class RedditIsFunDetector(RedditBrowser):
    is_app = True
    look_for = 'reddit is fun'
    name = 'reddit is fun'
    agent_string = ('^{look_for} \((?P<platform>.*?)\) '
                    '(?P<version>{version_string})$')
    override = [AndroidBrowser]


@register_detector
class RedditAndroidDetector(RedditBrowser):
    is_app = True
    look_for = 'RedditAndroid'
    name = 'Reddit: The Official App'
    agent_string = '{look_for} (?P<version>{version_string})$'


@register_detector
class RedditIOSDetector(RedditBrowser):
    is_app = True
    look_for = 'Reddit'
    name = 'reddit iOS'
    skip_if_found = ['Android']
    agent_string = (
        '{look_for}\/Version (?P<version>{version_string})\/Build '
        '(?P<b_number>\d+)\/(?P<platform>.*?) Version '
        '(?P<pversion>{version_string}) \(Build .*?\)')


@register_detector
class AlienBlueDetector(RedditBrowser):
    is_app = True
    look_for = 'AlienBlue'
    name = 'Alien Blue'
    agent_string = (
        '{look_for}\/(?P<version>{version_string}) CFNetwork\/'
        '{version_string} (?P<platform>.*?)\/(?P<pversion>{version_string})')


@register_detector
class RelayForRedditDetector(RedditBrowser):
    is_app = True
    look_for = 'Relay by /u/DBrady'
    name = 'relay for reddit'
    agent_string = '{look_for} v(?P<version>{version_string})'


@register_detector
class RedditSyncDetector(RedditBrowser):
    is_app = True
    look_for = 'reddit_sync'
    name = 'Sync for reddit'
    agent_string = (
        'android:com\.laurencedawson\.{look_for}'
        ':v(?P<version>{version_string}) \(by /u/ljdawson\)')


@register_detector
class NarwhalForRedditDetector(RedditBrowser):
    is_app = True
    look_for = 'narwhal'
    name = 'narwhal for reddit'
    agent_string = '{look_for}-(?P<platform>.*?)\/\d+ by det0ur'


@register_detector
class McRedditDetector(RedditBrowser):
    is_app = True
    look_for = 'McReddit'
    name = 'McReddit'
    agent_string = '{look_for} - Reddit Client for (?P<platform>.*?)$'


@register_detector
class ReaditDetector(RedditBrowser):
    look_for = 'Readit'
    name = 'Readit'
    agent_string = '(\({look_for} for WP /u/MessageAcrossStudios\) ?){{1,2}}'


@register_detector
class BaconReaderDetector(RedditBrowser):
    is_app = True
    look_for = 'BaconReader'
    name = 'Bacon Reader'
    agent_string = (
        '{look_for}\/(?P<version>{version_string}) \([a-zA-Z]+; '
        '(?P<platform>.*?) (?P<pversion>{version_string}); '
        'Scale\/{version_string}\)')


def detect(*args, **kw):
    return de(*args, **kw)
