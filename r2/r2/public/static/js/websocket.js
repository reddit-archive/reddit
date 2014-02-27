r.WebSocket = function (url) {
    this._url = url
    this._connectionAttempts = 0

    var websocketsAvailable = 'WebSocket' in window
    if (websocketsAvailable) {
        this._connect()
    }
}
_.extend(r.WebSocket.prototype, Backbone.Events, {
    _backoffTime: 2000,
    _maximumRetries: 9,

    _connect: function () {
        r.debug('websocket: connecting')
        this.trigger('connecting')

        this._socket = new WebSocket(this._url)
        this._socket.onopen = _.bind(this._onOpen, this)
        this._socket.onmessage = _.bind(this._onMessage, this)
        this._socket.onclose = _.bind(this._onClose, this)

        this._connectionAttempts += 1
    },

    _onOpen: function (ev) {
        r.debug('websocket: connected')
        this.trigger('connected')
        this._connectionAttempts = 0
    },

    _onMessage: function (ev) {
        var parsed = JSON.parse(ev.data)
        r.debug('websocket: received "' + parsed.type + '" message')
        this.trigger('message message:' + parsed.type, parsed.payload)
    },

    _onClose: function (ev) {
        if (this._connectionAttempts < this._maximumRetries) {
            var delay = this._backoffTime * Math.pow(2, this._connectionAttempts)
            r.debug('websocket: connection lost, reconnecting in ' + delay + 'ms')
            this.trigger('reconnecting', delay)
            setTimeout(_.bind(this._connect, this), delay)
        } else {
            r.debug('websocket: maximum retries exceeded. bailing out')
            this.trigger('disconnected')
        }
    }
})
