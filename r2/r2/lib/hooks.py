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
"""A very simple system for event hooks for plugins etc."""


_HOOKS = {}


class Hook(object):
    """A single hook that can be listened for."""
    def __init__(self):
        self.handlers = []

    def register_handler(self, handler):
        """Register a handler to call from this hook."""
        self.handlers.append(handler)

    def call(self, **kwargs):
        """Call handlers and return their results.

        Handlers will be called in the same order they were registered and
        their results will be returned in the same order as well.

        """
        return [handler(**kwargs) for handler in self.handlers]


def get_hook(name):
    """Return the named hook `name` creating it if necessary."""
    # this should be atomic as long as `name`'s __hash__ isn't python code
    # or for all types after the fixes in python#13521 are merged into 2.7.
    return _HOOKS.setdefault(name, Hook())


class HookRegistrar(object):
    """A registry for deferring module-scope hook registrations.

    This registry allows us to use module-level decorators but not actually
    register with global hooks unless we're told to.

    """
    def __init__(self):
        self.registered = False
        self.connections = []

    def on(self, name):
        """Return a decorator that registers the wrapped function."""

        hook = get_hook(name)

        def hook_decorator(fn):
            if self.registered:
                hook.register_handler(fn)
            else:
                self.connections.append((hook, fn))
            return fn
        return hook_decorator

    def register_all(self):
        """Complete all deferred registrations."""
        for hook, handler in self.connections:
            hook.register_handler(handler)
        self.registered = True
