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
        $('form.google-checkout').on('submit', this.fireGoogleCheckout)
        $('form.gold-checkout').one('submit', this.fireGoldCheckout)
    },

    fetchTrackingHashes: function() {
        var fullnames = {}

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

                if (!fullname || fullname in r.analytics.trackers)
                    return

                var trackingName = fullname

                if (sponsorship)
                    trackingName += '_' + sponsorship

                // append a hyphen even if there's no campaign
                trackingName += '-' + (campaign || '')

                if (!r.config.is_fake)
                    trackingName += '-' + r.config.post_site

                thing.data('trackingName', trackingName)
                fullnames[fullname] = trackingName
            })

        var xhr = $.ajax({
                url: r.config.fetch_trackers_url,
                type: 'get',
                dataType: 'jsonp',
                data: { 'ids': _.values(fullnames) },
                success: function(data) {
                    $.extend(r.analytics.trackers, data)
                }
            })

        _.each(fullnames, function(trackingName, fullname) {
            this.trackers[fullname] = xhr
        }, this)
    },

    fetchTrackersOrFirePixel: function(e) {
        var target = $(e.target),
            fullname = target.data('fullname')

        if (!fullname)
            return

        if (!(fullname in this.trackers)) {
            this.fetchTrackingHashes()
        }

        $.when(this.trackers[fullname]).done(_.bind(function() {
            this.fireTrackingPixel(target)
        }, this))
    },

    fireTrackingPixel: function(thing) {
        if (thing.data('trackerFired'))
            return

        var trackingName = thing.data('trackingName'),
            hash = this.trackers[trackingName]

        var pixel = new Image()
        pixel.src = r.config.adtracker_url + '?' + $.param({
            'id': trackingName,
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
            'id': trackingName,
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
    },

    fireGoldCheckout: function(event) {
        var form = $(this),
            vendor = form.data('vendor')
        form.parent().addClass('working')
        
        // Track a virtual pageview indicating user went off-site to "vendor."
        // If GA is loaded, have GA process form submission after firing
        // (and cancel the default).
        _gaq.push(['_trackPageview', '/gold/external/' + vendor])
        _gaq.push(function(){ form.submit() })
        
        if (_gat && _gat._getTracker){
          // GA is loaded; form will submit via the _gaq.push'ed function
          event.preventDefault()
        }
    },
    
    fireGoogleCheckout: function(event) {
        var form = $(this)
        form.parent().addClass('working')
        _gaq.push(function(){
          var pageTracker = _gaq._getAsyncTracker()
          setUrchinInputCode(pageTracker)
        })
    }
}

r.analytics.breadcrumbs = {
    selector: '.thing, .side, .sr-list, .srdrop, .tagline, .md, .organic-listing, .gadget, .sr-interest-bar, a, button, input',
    maxLength: 3,
    sendLength: 2,

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

    store: function() {
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
        this.data = this.data.slice(0, this.maxLength)
        this.store()
    },

    storeLastClick: function(el) {
        try {
            this.data[0]['click'] =
                r.utils.querySelectorFromEl(el, this.selector)
            this.store()
        } catch (e) {
            // Band-aid for Firefox NS_ERROR_DOM_SECURITY_ERR until fixed.
        }
    },

    lastClickFullname: function() {
        var lastClick = _.find(this.data, function(crumb) {
            return crumb.click
        })
        if (lastClick) {
            var match = lastClick.click.match(/.*data-fullname="(\w+)"/)
            return match && match[1]
        }
    },

    toParams: function() {
        params = []
        for (var i = 0; i < this.sendLength; i++) {
            _.each(this.data[i], function(v, k) {
                params['c'+i+'_'+k] = v
            })
        }
        return params
    }
}
