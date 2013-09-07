r.logging = {}

r.logging.pageAgeLimit = 5*60  // seconds
r.logging.sendThrottle = 8  // seconds

r.logging.init = function() {
    _.each(['debug', 'log', 'warn', 'error'], function(name) {
        // suppress debug messages unless config.debug is set
        r[name] = (name != 'debug' || r.config.debug)
                && window.console && console[name]
                ? _.bind(console[name], console)
                : function() {}
    })
    r.sendError = r.logging.sendError
}

r.logging.serverLogger = {
    logCount: 0,
    _queuedLogs: [],

    queueLog: function(logData) {
        if (this.logCount >= 3) {
            r.warn('Not sending debug log; already sent', this.logCount)
            return
        }

        // don't send messages for pages older than 5 minutes to prevent CDN cached
        // pages from slamming us if we need to turn off logs
        var pageAge = (new Date / 1000) - r.config.server_time
        if (Math.abs(pageAge) > r.logging.pageAgeLimit) {
            r.warn('Not sending debug log; page too old:', pageAge)
            return
        }

        if (!r.config.send_logs) {
            r.warn('Server-side debug logging disabled')
            return
        }

        logData.url = window.location.toString()
        this._queuedLogs.push(logData)
        this.logCount++

        // defer so that errors get batched until JS yields
        _.defer(_.bind(function() {
            this._sendLogs()
        }, this))
    },

    _sendLogs: _.throttle(function() {
        var queueCount = this._queuedLogs.length
        r.ajax({
            type: 'POST',
            url: '/web/log/error.json',
            data: {logs: JSON.stringify(this._queuedLogs)},
            headers: {
                'X-Loggit': true
            },
            success: function() {
                r.log('Sent', queueCount, 'debug logs to server')
            },
            error: function(xhr, err, status) {
                r.warn('Error sending debug logs to server:', err, ';', status)
            }
        })
        this._queuedLogs = []
    }, r.logging.sendThrottle * 1000)
}

r.logging.sendError = function() {
    r.error.apply(r, arguments)
    r.logging.serverLogger.queueLog({msg: _.toArray(arguments).join(' ')})
}
