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

from pylons import g
import hashlib
from mako.template import Template as mTemplate
from mako.exceptions import TemplateLookupException
from r2.lib.filters import websafe, unsafe

from r2.lib.utils import Storage

import inspect, re, os

class tp_manager:
    def __init__(self, template_cls=mTemplate):
        self.templates = {}
        self.Template = template_cls

    def add(self, name, style, file = None):
        key = (name.lower(), style.lower())
        if file is None:
            file = "/%s.%s" % (name, style)
        elif not file.startswith('/'):
            file = '/' + file
        self.templates[key] = file
        return file

    def add_handler(self, name, style, handler):
        key = (name.lower(), style.lower())
        self.templates[key] = handler

    def get(self, thing, style, cache = True):
        if not isinstance(thing, type(object)):
            thing = thing.__class__

        style = style.lower()
        top_key = (thing.__name__.lower(), style)

        template = None
        for cls in inspect.getmro(thing):
            name = cls.__name__.lower()
            key = (name, style)

            template_or_name = self.templates.get(key)
            if not template_or_name:
                template_or_name = self.add(name, style)

            if isinstance(template_or_name, self.Template):
                template = template_or_name
                break
            else:
                try:
                    template = g.mako_lookup.get_template(template_or_name)
                    if cache:
                        self.templates[key] = template
                        # also store a hash for the template
                        if (not hasattr(template, "hash") and
                            hasattr(template, "filename")):
                            with open(template.filename, 'r') as handle:
                                template.hash = hashlib.sha1(handle.read()).hexdigest()
                        # cache also for the base class so
                        # introspection is not required on subsequent passes
                        if key != top_key:
                            self.templates[top_key] = template
                    break
                except TemplateLookupException:
                    pass

        if not template or not isinstance(template, self.Template):
            raise AttributeError, ("template doesn't exist for %s" % str(top_key))
        return template

