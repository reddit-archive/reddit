// polyfill, see https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Date/now
if (!Date.now) {
    Date.now = function now() {
        return new Date().getTime()
    }
}

r.timetext = {
    _maxAge: 24 * 60 * 60,
    _chunks: [
        [60 * 60 * 24 * 365, r.NP_('a year ago', '%(num)s years ago')],
        [60 * 60 * 24 * 30, r.NP_('a month ago', '%(num)s months ago')],
        [60 * 60 * 24, r.NP_('a day ago', '%(num)s days ago')],
        [60 * 60, r.NP_('an hour ago', '%(num)s hours ago')],
        [60, r.NP_('a minute ago', '%(num)s minutes ago')]
    ],

    init: function () {
        this.refresh()
        setInterval(this.refresh, 20 * 1000)
    },

    refresh: function () {
        var now = Date.now()

        $('time.live').each(function () {
            r.timetext.refreshOne(this, now)
        })
    },

    refreshOne: function (el, now) {
        if (!now)
            now = Date.now()

        var $el = $(el)
        var timestamp = $el.data('timestamp')

        if (!timestamp) {
            var isoTimestamp = $el.attr('datetime')
            timestamp = Date.parse(isoTimestamp)
            $el.data('timestamp', timestamp)
        }

        var age = (now - timestamp) / 1000
        if (age > this._maxAge) {
            return
        }

        var chunks = r.timetext._chunks
        var text = r._('just now')

        $.each(r.timetext._chunks, function (ix, chunk) {
            var count = Math.floor(age / chunk[0])
            if (count > 0) {
                var keys = chunk[1]
                text = r.P_(keys[0], keys[1], count).format({num: count})
                return false
            }
        })

        $el.text(text)
    }
}

$(function () {
    r.timetext.init()
})
