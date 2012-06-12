from r2.lib.translation import I18N_PATH
from r2.lib.plugin import PluginLoader
from r2.lib import js

print 'I18NPATH := ' + I18N_PATH

plugins = list(PluginLoader.available_plugins())
print 'PLUGINS := ' + ' '.join(plugin.name for plugin in plugins)
for plugin in plugins:
    print 'PLUGIN_PATH_%s := %s' % (plugin.name, PluginLoader.plugin_path(plugin))

js.load_plugin_modules()
modules = dict((k, m) for k, m in js.module.iteritems() if m.should_compile)
print 'JS_MODULES := ' + ' '.join(modules.iterkeys())
outputs = []
for name, module in modules.iteritems():
    outputs.extend(module.outputs)
    print 'JS_MODULE_OUTPUTS_%s := %s' % (name, ' '.join(module.outputs))
    print 'JS_MODULE_DEPS_%s := %s' % (name, ' '.join(module.dependencies))

print 'JS_OUTPUTS := ' + ' '.join(outputs)
