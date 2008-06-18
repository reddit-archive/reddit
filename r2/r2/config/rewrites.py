# "The contents of this file are subject to the Common Public Attribution
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
# The Original Code is Reddit.
# 
# The Original Developer is the Initial Developer.  The Initial Developer of the
# Original Code is CondeNet, Inc.
# 
# All portions of the code written by CondeNet are Copyright (c) 2006-2008
# CondeNet, Inc. All Rights Reserved.
################################################################################
import re

rewrites = (#these first two rules prevent the .embed rewrite from
            #breaking other js that should work
            ("^/_(.*)", "/_$1"),
            ("^/static/(.*\.js)", "/static/$1"),
            #This next rewrite makes it so that all the embed stuff works.
            ("^(.*)(?<!button)(\.js)$", "$1.embed"),
            ("^/favicon.ico$", "/static/favicon.ico"),
            ("^/akamai-sureroute-test-object.html$", "/static/sureroute.html"),
            ("^/apple-touch-icon.png$", "/static/apple-touch-icon.png"))

rewrites = tuple((re.compile(r[0]), r[1]) for r in rewrites)
