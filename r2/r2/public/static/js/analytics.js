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

        /*------------------------------------------* 
           Generates a trackingName like:
           t3_ab-t8_99-pics if targeted with campaign
           t3_ab-t8_99      not targeted with campaign
           t3_ab--pics      targeted with no campaign
           t3_ab-           not targeted, no campaign 
         *------------------------------------------*/

        $('.promotedlink.promoted, .sponsorshipbox')
            .each(function() {
                var thing = $(this),
                    fullname = thing.data('fullname'),
                    sponsorship = thing.data('sponsorship'),
                    campaign = thing.data('cid')

                if (sponsorship)
                    fullname += '_' + sponsorship

                // append a hyphen even if there's no campaign
                fullname += '-' + (campaign || '')

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
    },

    fireUITrackingPixel: function(action, srname) {
        var pixel = new Image()
        pixel.src = r.config.uitracker_url + '?' + $.param(
            _.extend(
                {
                    'act': action,
                    'sr': srname,
                    'r': Math.round(Math.random() * 2147483647) // cachebuster
                },
                r.analytics.breadcrumbs.toParams()
            )
        )
    }
}

r.analytics.breadcrumbs = {
    selector: '.thing, .side, .sr-list, .srdrop, .tagline, .md, .organic-listing, .gadget, .sr-interest-bar, a, button, input',

    init: function() {
        this.hasSessionStorage = this._checkSessionStorage()
        this.data = this._load()

        var refreshed = this.data[0] && this.data[0]['url'] == window.location
        if (!refreshed) {
            this._storeBreadcrumb()
        }

        $(document).delegate('a, button', 'click', $.proxy(function(ev) {
            this.storeLastClick($(ev.target))
        }, this))
    },

    _checkSessionStorage: function() {
        // Via modernizr.com's sessionStorage check.
        try {
            sessionStorage.setItem('__test__', 'test')
            sessionStorage.removeItem('__test__')
            return true
        } catch(e) {
            return false
        }
    },

    _load: function() {
        if (!this.hasSessionStorage) {
            return [{stored: false}]
        }

        var data
        try {
            data = JSON.parse(sessionStorage['breadcrumbs'])
        } catch (e) {
            data = []
        }

        if (!_.isArray(data)) {
            data = []
        }

        return data
    },

    store: function(data) {
        if (this.hasSessionStorage) {
            sessionStorage['breadcrumbs'] = JSON.stringify(this.data)
        }
    },

    _storeBreadcrumb: function() {
        var cur = {
            'url': location.toString()
        }

        if ('referrer' in document) {
            var referrerExternal = !document.referrer.match('^' + r.config.currentOrigin),
                referrerUnexpected = this.data[0] && document.referrer != this.data[0]['url']

            if (referrerExternal || referrerUnexpected) {
                cur['ref'] = document.referrer
            }
        }

        this.data.unshift(cur)
        this.data = this.data.slice(0, 2)
        this.store()
    },

    storeLastClick: function(el) {
        this.data[0]['click'] =
            r.utils.querySelectorFromEl(el, this.selector)
        this.store()
    },

    toParams: function() {
        params = []
        for (var i = 0; i < this.data.length; i++) {
            _.each(this.data[i], function(v, k) {
                params['c'+i+'_'+k] = v
            })
        }
        return params
    }
}
