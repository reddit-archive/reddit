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
import sys
from unittest import TestCase

import pkg_resources
import paste.fixture
import paste.script.appinstall
from paste.deploy import loadapp

__all__ = ['RedditTestCase']

here_dir = os.path.dirname(os.path.abspath(__file__))
conf_dir = os.path.dirname(os.path.dirname(here_dir))

sys.path.insert(0, conf_dir)
pkg_resources.working_set.add_entry(conf_dir)
pkg_resources.require('Paste')
pkg_resources.require('PasteScript')


def stage_for_paste():
     wsgiapp = loadapp('config:test.ini', relative_to=conf_dir)
     test_app = paste.fixture.TestApp(wsgiapp)

     # this is basically what 'paster run' does (see r2/commands.py)
     test_response = test_app.get("/_test_vars")
     request_id = int(test_response.body)
     test_app.pre_request_hook = lambda self: \
         paste.registry.restorer.restoration_end()
     test_app.post_request_hook = lambda self: \
         paste.registry.restorer.restoration_begin(request_id)
     paste.registry.restorer.restoration_begin(request_id)


class RedditTestCase(TestCase):
    """Base Test Case for tests that require the app environment to run.

    App startup does take time, so try to use unittest.TestCase directly when
    this isn't necessary as it'll save time.

    """
    def __init__(self, *args, **kwargs):
        stage_for_paste()
        TestCase.__init__(self, *args, **kwargs)
