r.analytics = {
    trackers: {},

    init: function() {
        // these guys are relying on the custom 'onshow' from jquery.reddit.js
        $(document).delegate(
            '.promotedlink.promoted, .sponsorshipbox',
            'onshow',
            $.proxy(this, 'fetchTrackersOrFirePixel')
        )

        $('.promotedlink.promoted:visible, .sponsorshipbox:visible').trigger('onshow')
    },

    fetchTrackingHashes: function(callback) {
        var fullnames = []

        $('.promotedlink.promoted, .sponsorshipbox')
            .each(function() {
                var thing = $(this),
                    fullname = thing.data('fullname'),
                    sponsorship = thing.data('sponsorship')

                if (sponsorship)
                    fullname += '_' + sponsorship

                if (!r.config.is_fake)
                    fullname += '-' + r.config.post_site

                thing.data('trackingName', fullname)

                if (!(fullname in r.analytics.trackers))
                    fullnames.push(fullname)
            })

        $.ajax({
            url: 'http://' + r.config.tracking_domain + '/fetch-trackers',
            type: 'get',
            dataType: 'jsonp',
            data: { 'ids': fullnames },
            success: function(data) {
                $.extend(r.analytics.trackers, data)
                callback()
            }
        })
    },

    fetchTrackersOrFirePixel: function(e) {
        var target = $(e.target),
            fullname = target.data('fullname')

        if (fullname in this.trackers) {
            this.fireTrackingPixel(target)
        } else {
            this.fetchTrackingHashes($.proxy(this, 'fireTrackingPixel', target))
        }
    },

    fireTrackingPixel: function(thing) {
        if (thing.data('trackerFired'))
            return

        var fullname = thing.data('trackingName'),
            hash = this.trackers[fullname]

        var pixel = new Image()
        pixel.src = r.config.adtracker_url + '?' + $.param({
            'id': fullname,
            'hash': hash,
            'r': Math.round(Math.random() * 2147483647) // cachebuster
        })

        // If IE7/8 thinks the text of a link looks like an email address
        // (e.g. it has an @ in it), then setting the href replaces the
        // text as well. We'll store the original text and replace it to
        // hack around this. Distilled reproduction in: http://jsfiddle.net/JU2Vj/1/
        var link = thing.find('a.title'),
            old_html = link.html(),
            dest = link.attr('href'),
            click_url = r.config.clicktracker_url + '?' + $.param({
            'id': fullname,
            'hash': hash,
            'url': dest
        })

        save_href(link)
        link.attr('href', click_url)

        if (link.html() != old_html)
            link.html(old_html)

        // also do the thumbnail
        var thumb = thing.find('a.thumbnail')
        save_href(thumb)
        thumb.attr('href', click_url)

        thing.data('trackerFired', true)
    }
}
