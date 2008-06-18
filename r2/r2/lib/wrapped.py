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
from filters import unsafe
from utils import storage

import sys
sys.setrecursionlimit(500)

class NoTemplateFound(Exception): pass

class Wrapped(object):
    
    def __init__(self, *lookups, **context):
        self.lookups = lookups
        for k, v in context.iteritems():
            setattr(self, k, v)

    def __getattr__(self, attr):
        #print "GETATTR: " + str(attr)
        res = None
        found = False
        for lookup in self.lookups:
            try:
                res = getattr(lookup, attr)
                found = True
                break
            except AttributeError:
                pass
            
        if not found:
            raise AttributeError, attr

        setattr(self, attr, res)
        return res


    def __repr__(self):
        return '<%s %s %s>' % (self.__class__.__name__,
                               self.lookups, self.context)


    def template(self, style = 'html'):
        from r2.config.templates import tpm
        from pylons import g
        debug = g.template_debug
        template = None
        if self.__class__ == Wrapped:
            for lookup in self.lookups:
                try:
                    template = tpm.get(lookup, style, cache = not debug)
                except KeyError:
                    continue
        else:
            try:
                template = tpm.get(self, style, cache = not debug)
            except KeyError:
                raise NoTemplateFound, repr(self)
                
        return template

    #TODO is this the best way to override style?
    def render(self, style = None):
        """Renders the template corresponding to this class in the given style."""
        from pylons import c
        style = style or c.render_style or 'html'
        template = self.template(style)
        if template:
            res = template.render(thing = self)
            return res if (style and style.startswith('api')) else unsafe(res)
        else:
            raise NoTemplateFound, repr(self)

    def part_render(self, attr, *a, **kw):
        """Renders the part of a template associated with the %def
        whose name is 'attr'.  This is used primarily by
        r2.lib.menus.Styled"""
        style = kw.get('style', 'html')
        template = self.template(style)
        dt = template.get_def(attr)
        return unsafe(dt.render(thing = self, *a, **kw))


def SimpleWrapped(**kw):
    class _SimpleWrapped(Wrapped):
        def __init__(self, *a, **kw1):
            kw.update(kw1)
            Wrapped.__init__(self, *a, **kw)
    return _SimpleWrapped
