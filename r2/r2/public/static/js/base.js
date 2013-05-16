r = window.r || {}

r.setup = function(config) {
    r.config = config
    // Set the legacy config global
    reddit = config

    _.each(['debug', 'warn', 'error'], function(name) {
        // suppress debug messages unless config.debug is set
        r[name] = (name != 'debug' || config.debug)
                && window.console && console[name]
                ? _.bind(console[name], console)
                : function() {}
    })

    r.config.currentOrigin = location.protocol+'//'+location.host
    r.analytics.breadcrumbs.init()
}

r.setupBackbone = function() {
    Backbone.emulateJSON = true
    Backbone.ajax = function(request) {
        var url = request.url

        if (request.type == 'GET') {
            var preloaded = r.preload.read(url)
            if (preloaded != null) {
                request.success(preloaded)

                var deferred = new jQuery.Deferred
                deferred.resolve(preloaded)
                return deferred
            }
        }

        var isLocal = url && (url[0] == '/' || url.lastIndexOf(r.config.currentOrigin, 0) == 0)
        if (isLocal) {
            if (!request.headers) {
                request.headers = {}
            }
            request.headers['X-Modhash'] = r.config.modhash
        }

        return Backbone.$.ajax(request)
    }
}

$(function() {
    r.setupBackbone()

    r.login.ui.init()
    r.analytics.init()
    r.ui.init()
    r.interestbar.init()
    r.apps.init()
    r.wiki.init()
    r.gold.init()
    r.multi.init()
})
