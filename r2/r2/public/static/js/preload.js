r.preload = {
    timestamp: new Date(),
    maxAge: 5 * 60 * 1000,
    data: {},

    isExpired: function() {
        return new Date() - this.timestamp > this.maxAge
    },

    set: function(data) {
        var unescapedData = r.utils.structuredMap(data, function(val) {
            if (_.isString(val)) {
                return _.unescape(val)
            } else {
                return val
            }
        })
        _.extend(this.data, unescapedData)
    },

    read: function(url) {
        var data = this.data[url]

        // short circuit "client side" fragment urls (which don't expire)
        if (url[0] == '#') {
            return data
        }

        if (this.isExpired()) {
            return
        }

        return data
    }
}

