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

    if (request.type == 'GET' && _.isEmpty(request.data)) {
        var preloaded = r.preload.read(url)
        if (preloaded != null) {
            if (request.dataFilter) {
                preloaded = request.dataFilter(preloaded, 'json')
            }

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

r.sync = function(method, model, options) {
  var wrappedDataFilter = options.dataFilter
  options.dataFilter = function(data, type) {
    var filteredData

    if (type === 'json') {
      filteredData = r.utils.unescapeJson(data)
    } else {
      filteredData = data
    }

    if (wrappedDataFilter) {
      return wrappedDataFilter(filteredData)
    } else {
      return filteredData
    }
  }
  return r.backboneSync.call(Backbone, method, model, options)
}

store.safeGet = function(key, errorValue) {
    if (store.disabled) {
        return errorValue
    }

    // errorValue defaults to undefined, equivalent to the key being unset.
    try {
        return store.get(key)
    } catch (err) {
        r.sendError('Unable to read storage key "%(key)s" (%(err)s)'.format({
            key: key,
            err: err
        }))
        // TODO: reset value to errorValue?
        return errorValue
    }
}

store.safeSet = function(key, val) {
    if (store.disabled) {
        return false
    }

    // swallow exceptions upon storage set for non-trivial operations. returns
    // a boolean value indicating success.
    try {
        store.set(key, val)
        return true
    } catch (err) {
        r.warn('Unable to set storage key "%(key)s" (%(err)s)'.format({
            key: key,
            err: err
        }))
        return false
    }
}

r.setupBackbone = function() {
    Backbone.emulateJSON = true
    Backbone.ajax = r.ajax

    if (!r.backboneSync) {
        r.backboneSync = Backbone.sync
        Backbone.sync = r.sync
    }
}

$(function() {
    try {
        r.setupBackbone()

        r.login.ui.init()
        r.analytics.init()
        r.ui.init()
        r.interestbar.init()
        r.visited.init()
        r.apps.init()
        r.wiki.init()
        r.gold.init()
        r.multi.init()
        r.recommend.init()
        r.saved.init()
        r.messages.init()
        r.filter.init()
        r.newsletter.ui.init()
    } catch (err) {
        r.sendError('Error during base.js init', err)
    }
})
