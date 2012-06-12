import sys
import os.path
import pkg_resources
from pylons import config


class Plugin(object):
    js = {}
    config = {}

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

    def on_load(self):
        pass

    def add_js(self, module_registry=None):
        if not module_registry:
            from r2.lib import js
            module_registry = js.module

        for name, module in self.js.iteritems():
            if name not in module_registry:
                module_registry[name] = module
            else:
                module_registry[name].extend(module)

    def add_routes(self, mc):
        pass

    def load_controllers(self):
        pass


class PluginLoader(object):
    def __init__(self):
        self.plugins = {}

    def __len__(self):
        return len(self.plugins)

    def __iter__(self):
        return self.plugins.itervalues()

    def __getitem__(self, key):
        return self.plugins[key]

    @staticmethod
    def available_plugins(name=None):
        return pkg_resources.iter_entry_points('r2.plugin', name)

    @staticmethod
    def plugin_path(plugin):
        if isinstance(plugin, str):
            try:
                plugin = pkg_resources.iter_entry_points("r2.plugin", name).next()
            except StopIteration:
                return None
        return os.path.join(plugin.dist.location, plugin.module_name)

    def load_plugins(self, plugin_names):
        g = config['pylons.g']
        for name in plugin_names:
            try:
                entry_point = self.available_plugins(name).next()
            except StopIteration:
                g.log.warning('Unable to locate plugin "%s". Skipping.' % name)
                continue
            plugin_cls = entry_point.load()
            plugin = self.plugins[name] = plugin_cls()
            g.config.add_spec(plugin.config)
            config['pylons.paths']['templates'].extend(plugin.template_dirs)
            plugin.add_js()
            plugin.on_load()
        return self

    def load_controllers(self):
        for plugin in self:
            plugin.load_controllers()
