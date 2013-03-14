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
import mimetypes

from mako.lookup import TemplateLookup
from pylons.error import handle_mako_error
from pylons import config

import r2.config
import r2.lib.helpers
from r2.config import routing
from r2.lib.app_globals import Globals
from r2.lib.configparse import ConfigValue


mimetypes.init()


def load_environment(global_conf={}, app_conf={}, setup_globals=True):
    # Setup our paths
    root_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    paths = {'root': root_path,
             'controllers': os.path.join(root_path, 'controllers'),
             'templates': [os.path.join(root_path, 'templates')],
             }

    if ConfigValue.bool(global_conf.get('uncompressedJS')):
        paths['static_files'] = os.path.join(root_path, 'public')
    else:
        paths['static_files'] = os.path.join(os.path.dirname(root_path), 'build/public')

    config.init_app(global_conf, app_conf, package='r2',
                    template_engine='mako', paths=paths)

    # don't put action arguments onto c automatically
    config['pylons.c_attach_args'] = False
    # when accessing non-existent attributes on c, return "" instead of dying
    config['pylons.strict_c'] = False

    g = config['pylons.g'] = Globals(global_conf, app_conf, paths)
    if setup_globals:
        g.setup()
        g.plugins.declare_queues(g.queues)
        r2.config.cache = g.cache
    g.plugins.load_plugins()
    config['r2.plugins'] = g.plugins
    g.startup_timer.intermediate("plugins")

    config['pylons.h'] = r2.lib.helpers
    config['routes.map'] = routing.make_map()

    #override the default response options
    config['pylons.response_options']['headers'] = {}

    # when mako loads a previously compiled template file from its cache, it
    # doesn't check that the original template path matches the current path.
    # in the event that a new plugin defines a template overriding a reddit
    # template, unless the mtime newer, mako doesn't update the compiled
    # template. as a workaround, this makes mako store compiled templates with
    # the original path in the filename, forcing it to update with the path.
    if "cache_dir" in app_conf:
        module_directory = os.path.join(app_conf['cache_dir'], 'templates')

        def mako_module_path(filename, uri):
            filename = filename.lstrip('/').replace('/', '-')
            path = os.path.join(module_directory, filename + ".py")
            return os.path.abspath(path)
    else:
        # we're probably in "paster run standalone" mode. we'll just avoid
        # caching templates since we don't know where they should go.
        module_directory = mako_module_path = None

    # set up the templating system
    config["pylons.g"].mako_lookup = TemplateLookup(
        directories=paths["templates"],
        error_handler=handle_mako_error,
        module_directory=module_directory,
        input_encoding="utf-8",
        default_filters=["mako_websafe"],
        filesystem_checks=getattr(g, "reload_templates", False),
        imports=[
            "from r2.lib.filters import websafe, unsafe, mako_websafe",
            "from pylons import c, g, request",
            "from pylons.i18n import _, ungettext",
        ],
        modulename_callable=mako_module_path,
    )

    if setup_globals:
        g.setup_complete()
