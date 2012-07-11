r.adminbar = {}

r.adminbar.AdminBar = Backbone.View.extend({
    events: {
        'click .show-button': 'toggleVisibility',
        'click .hide-button': 'toggleVisibility',
        'click .timings-button': 'toggleTimings',
        'click .expand-button': 'toggleFullTimings',
        'click .admin-off': 'adminOff'
    },

    initialize: function() {
        this.hidden = store.get('adminbar.hidden') == true
        this.showTimings = store.get('adminbar.timings.show') == true
        this.showFullTimings = store.get('adminbar.timings.full') == true

        this.serverTimingGraph = new r.adminbar.TimingBarGraph({
            collection: r.adminbar.timings,
            el: this.$('.timeline-server')
        })

        this.browserTimingGraph = new r.adminbar.TimingBarGraph({
            collection: r.adminbar.browserTimings,
            el: this.$('.timeline-browser')
        })

        r.adminbar.timings.on('reset', this.render, this)
        r.adminbar.browserTimings.on('reset', this.render, this)
    },

    adminOff: function() {
        window.location = '/adminoff'
    },

    render: function() {
        this.$el.toggleClass('hidden', this.hidden)

        this.$('.timings-bar')
            .toggle(this.showTimings)
            .toggleClass('mini-timings', !this.showFullTimings)
            .toggleClass('full-timings', this.showFullTimings)

        this.$('.status-bar .timings-button .state')
            .text(this.showTimings ? '-' : '+')

        this.$('.timings-bar .expand-button')
            .text(this.showFullTimings ? '-' : '+')

        this.$el.parent().css('height', this.$el.outerHeight())

        if (r.adminbar.timings.isEmpty()) {
            return
        }

        var bt = r.adminbar.browserTimings
        if (this.showFullTimings && !bt.isEmpty()) {
            this.serverTimingGraph.setBounds(bt.startTime, bt.endTime)
        } else {
            this.serverTimingGraph.setBounds()
        }

        // if showing full times, avoid rendering until both timelines loaded
        // to avoid a flicker when the server timing graph rescales.
        if (!this.showFullTimings || !bt.isEmpty()) {
            this.serverTimingGraph.render()
            this.browserTimingGraph.render()
        }
    },

    toggleVisibility: function() {
        this.hidden = !this.hidden
        store.set('adminbar.hidden', this.hidden)
        this.render()
    },

    toggleTimings: function() {
        this.showTimings = !this.showTimings
        store.set('adminbar.timings.show', this.showTimings)
        this.render()
    },

    toggleFullTimings: function(value) {
        this.showFullTimings = !this.showFullTimings
        store.set('adminbar.timings.full', this.showFullTimings)
        this.render()
    }
})

r.adminbar.TimingBarGraph = Backbone.View.extend({
    setBounds: function(start, end) {
        this.options.startBound = start
        this.options.endBound = end
    },

    render: function() {
        var startBound = this.options.startBound || this.collection.startTime,
            endBound = this.options.endBound || this.collection.endTime,
            boundDuration = endBound - startBound,
            pos = function(time) {
                var frac = time / boundDuration
                return (frac * 100).toFixed(2)
            }

        if (this.collection.endTime < this.options.startBound) {
            this.$el.append($('<div class="event out-of-bounds">'))
            return
        }

        this.$el.empty()
        var eventsEl = $('<ol class="events">')
        this.collection.each(function(timing) {
            var key = timing.get('key'),
                keyParts = key.split('.')

            if (keyParts[keyParts.length-1] == 'total') {
                return
            }

            eventsEl.append($('<li class="event">')
                .addClass(keyParts[0])
                .addClass(keyParts[1])
                .attr('title', key)
                .css({
                    left: pos(timing.get('start') - startBound) + '%',
                    right: pos(endBound - timing.get('end')) + '%'
                })
            )
        }, this)
        this.$el.append(eventsEl)

        var elapsed = this.collection.endTime - this.collection.startTime
        if (elapsed) {
            this.$el.append($('<span class="elapsed">')
                .text(elapsed.toFixed(2) + 's'))
        }

        return this
    }
})

r.adminbar.Timings = Backbone.Collection.extend({
    model: Backbone.Model.extend({
        idAttribute: 'key',
        duration: function() {
            return this.get('end') - this.get('start')
        }
    }),

    initialize: function() {
        this.on('reset', this.calculate, this)
    },

    calculate: function() {
        this.startTime = this.min(function(timing) {
            return timing.get('start')
        }).get('start')
        this.endTime = this.max(function(timing) {
            return timing.get('end')
        }).get('end')
        this.duration = this.endTime - this.startTime
    }
})

r.adminbar.NavigationTimings = r.adminbar.Timings.extend({
    fetch: function() {
        if (!window.performance || !window.performance.timing) {
            return
        }

        var pt = window.performance.timing,
            timings = []

        function timing(key, start, end) {
            if (!pt[start] || !pt[end]) {
                return
            }
            timings.push({
                key: key,
                start: pt[start] / 1000,
                end: pt[end] / 1000
            })
        }

        timing('redirect', 'redirectStart', 'redirectEnd')
        timing('start', 'fetchStart', 'domainLookupStart')
        timing('dns', 'domainLookupStart', 'domainLookupEnd')
        timing('tcp', 'connectStart', 'connectEnd')
        timing('https', 'secureConnectionStart', 'connectEnd')
        timing('request', 'requestStart', 'responseStart')
        timing('response', 'responseStart', 'responseEnd')
        timing('domLoading', 'domLoading', 'domInteractive')
        timing('domInteractive', 'domInteractive', 'domContentLoadedEventStart')
        timing('domContentLoaded', 'domContentLoadedEventStart', 'domContentLoadedEventEnd')
        this.reset(_.values(timings))
    }
})

r.adminbar.timings = new r.adminbar.Timings()
r.adminbar.browserTimings = new r.adminbar.NavigationTimings()

r.adminbar.bar = new r.adminbar.AdminBar({
    el: $('#admin-bar')
}).render()

$(function() {
    if (!r.timings) { return }
    r.adminbar.timings.reset(r.timings)
    setTimeout(function() {
        r.adminbar.browserTimings.fetch()
    }, 0)
})
