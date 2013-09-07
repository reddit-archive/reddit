r = window.r || {}

r.setup = function(config) {
    r.config = config
    // Set the legacy config global
    reddit = config

    r.logging.init()

    r.config.currentOrigin = location.protocol+'//'+location.host
    r.analytics.breadcrumbs.init()
}

r.ajax = function(request) {
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

    return $.ajax(request)
}

r.setupBackbone = function() {
    Backbone.emulateJSON = true
    Backbone.ajax = r.ajax
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
