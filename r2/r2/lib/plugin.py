import sys
import os.path
import pkg_resources
from pylons import config


class Plugin(object):
    @property
    def path(self):
        module = sys.modules[type(self).__module__]
        return os.path.dirname(module.__file__)

    @property
    def template_dirs(self):
        """Add module/templates/ as a template directory."""
        return [os.path.join(self.path, 'templates')]

    @property
    def static_dir(self):
        return os.path.join(self.path, 'public')

    def add_routes(self, mc):
        pass


def load_plugins(plugin_names):
    plugins = {}
    for name in plugin_names:
        try:
            entry_point = pkg_resources.iter_entry_points('r2.plugin', name).next()
        except StopIteration:
            config['pylons.g'].log.warning('Unable to locate plugin "%s". Skipping.' % name)
            continue
        plugin_cls = entry_point.load()
        plugin = plugins[name] = plugin_cls()
        config['pylons.paths']['templates'].extend(plugin.template_dirs)
    return plugins
