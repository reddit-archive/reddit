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

$(function() {
    r.login.ui.init()
    r.analytics.init()
    r.ui.init()
    r.spotlight.init()
    r.interestbar.init()
    r.apps.init()
    r.wiki.init()
    r.gold.init()
})
