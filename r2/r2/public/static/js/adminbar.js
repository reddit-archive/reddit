r.adminbar = {}

r.adminbar.AdminBar = Backbone.View.extend({
    events: {
        'click .show-button': 'toggleVisibility',
        'click .hide-button': 'toggleVisibility',
        'click .timings-button': 'toggleTimings',
        'click .expand-button': 'toggleFullTimings',
        'click .timelines': 'toggleZoom',
        'click .admin-off': 'adminOff'
    },

    initialize: function() {
        this.hidden = store.get('adminbar.hidden') == true
        this.showTimings = store.get('adminbar.timings.show') == true
        this.showFullTimings = store.get('adminbar.timings.full') == true
        this.zoomTimings = store.get('adminbar.timings.zoom') != false
        this.timingScale = store.get('adminbar.timings.scale') || 8.0

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

        this.$('.timelines').toggleClass('zoomed', this.zoomTimings)

        $('body').css({
            'margin-top': this.$el.outerHeight(),
            'position': 'relative'
        })

        if (r.adminbar.timings.isEmpty()) {
            return
        }

        var bt = r.adminbar.browserTimings,
            browserEndBound = bt.endTime
        if (!this.zoomTimings && (bt.endTime - bt.startTime) < this.timingScale) {
            browserEndBound = bt.startTime + this.timingScale
        }
        this.browserTimingGraph.setBounds(bt.startTime, browserEndBound)

        if (this.showFullTimings && !bt.isEmpty()) {
            this.serverTimingGraph.setBounds(bt.startTime, browserEndBound)
        } else {
            var scaleStart = r.adminbar.timings.startTime,
                scaleEnd = r.adminbar.timings.endTime
            if (!this.zoomTimings && (scaleEnd - scaleStart) < this.timingScale) {
                scaleEnd = scaleStart + this.timingScale
            }
            this.serverTimingGraph.setBounds(scaleStart, scaleEnd)
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
    },

    toggleZoom: function(value) {
        this.zoomTimings = !this.zoomTimings
        store.set('adminbar.timings.zoom', this.zoomTimings)
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

            var eventDuration = (timing.get('end') - timing.get('start')).toFixed(2)
            eventsEl.append($('<li class="event">')
                .addClass(keyParts[0])
                .addClass(keyParts[1])
                .addClass(keyParts[2])
                .attr('title', key + ': ' + eventDuration + 's')
                .css({
                    left: pos(timing.get('start') - startBound) + '%',
                    right: pos(endBound - timing.get('end')) + '%',
                    zIndex: 1000 - Math.min(800, Math.floor(timing.duration() * 100))
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







r.adminbar.timings = new r.Timings()
r.adminbar.browserTimings = new r.NavigationTimings()

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
