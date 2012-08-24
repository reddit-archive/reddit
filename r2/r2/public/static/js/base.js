r = window.r || {}

r.setup = function(config) {
    r.config = config
    // Set the legacy config global
    reddit = config

    r.config.currentOrigin = location.protocol+'//'+location.host
    r.analytics.breadcrumbs.init()
}

$(function() {
    r.login.ui.init()
    r.analytics.init()
    r.ui.HelpBubble.init()
    r.interestbar.init()
    r.apps.init()
    r.wiki.init()
})
