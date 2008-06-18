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
import pylons
from mako.template import Template as mTemplate
from mako.exceptions import TemplateLookupException
from r2.lib.filters import websafe, unsafe

from r2.lib.utils import Storage

import inspect, re, os

class tp_manager:
    def __init__(self, engine = 'mako', template_cls = mTemplate):
        self.templates = {}
        self.engine = engine
        self.Template = template_cls

    def add(self, name, style, file = None):
        key = (name.lower(), style.lower())
        if file is None:
            file = "/%s.%s" % (name, style)
        elif not file.startswith('/'):
            file = '/' + file
        self.templates[key] = file

    def add_handler(self, name, style, handler):
        key = (name.lower(), style.lower())
        self.templates[key] = handler

    def get(self, thing, style, cache = True):
        style = style.lower()
        top_key = (thing.__class__.__name__.lower(), style)

        template = None
        for cls in inspect.getmro(thing.__class__):
            name = cls.__name__.lower()
            key = (name, style)
            if not self.templates.has_key(key):
                self.add(name, style)
            if isinstance(self.templates[key], self.Template):
                template = self.templates[key]
            else:
                try:
                    _loader = pylons.buffet.engines[self.engine]['engine']
                    template = _loader.load_template(self.templates[key])
                    if cache:
                        self.templates[key] = template
                        # cache also for the base class so
                        # introspection is not required on subsequent passes
                        if key != top_key:
                            self.templates[top_key] = template
                except TemplateLookupException:
                    continue
            break

        if not template or not isinstance(template, self.Template):
            raise AttributeError, ("template doesn't exist for %s" % str(top_key))
        return template
