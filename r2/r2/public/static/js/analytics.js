r.analytics = {
    init: function() {
        // these guys are relying on the custom 'onshow' from jquery.reddit.js
        $(document).delegate(
            '.organic-listing .promotedlink.promoted',
            'onshow',
            _.bind(function(ev) {
                this.fireTrackingPixel(ev.target)
            }, this)
        )

        $('.promotedlink.promoted:visible').trigger('onshow')
        $('form.gold-checkout').one('submit', this.fireGoldCheckout)
    },

    fireGAEvent: function(category, action, opt_label, opt_value, opt_noninteraction) {
      opt_label = opt_label || '';
      opt_value = opt_value || 0;
      opt_noninteraction = !!opt_noninteraction;

      if (window._gaq) {
        _gaq.push(['_trackEvent', category, action, opt_label, opt_value, opt_noninteraction]);
      }
    },

    fireTrackingPixel: function(el) {
        var $el = $(el),
            onCommentsPage = $('body').hasClass('comments-page')

        if ($el.data('trackerFired') || onCommentsPage)
            return

        var pixel = new Image(),
            impPixel = $el.data('impPixel')

        if (impPixel) {
            pixel.src = impPixel
        }

        var adServerPixel = new Image(),
            adServerImpPixel = $el.data('adserverImpPixel'),
            adServerClickUrl = $el.data('adserverClickUrl')

        if (adServerImpPixel) {
            adServerPixel.src = adServerImpPixel
        }

        $el.data('trackerFired', true)
    },

    fireUITrackingPixel: function(action, srname, extraParams) {
        var pixel = new Image()
        pixel.src = r.config.uitracker_url + '?' + $.param(
            _.extend(
                {
                    'act': action,
                    'sr': srname,
                    'r': Math.round(Math.random() * 2147483647) // cachebuster
                },
                r.analytics.breadcrumbs.toParams(),
                extraParams
            )
        )
    },

    fireGoldCheckout: function(event) {
        var form = $(this),
            vendor = form.data('vendor')
        form.parent().addClass('working')

        // If we don't have _gaq, just return and let the event bubble and
        // call its own submit.
        if (!window._gaq) {
            return;
        }
        
        // Track a virtual pageview indicating user went off-site to "vendor."
        // If GA is loaded, have GA process form submission after firing
        // (and cancel the default).
        _gaq.push(['_trackPageview', '/gold/external/' + vendor])
        _gaq.push(function() {
            // Give GA half a second to send out its pixel.
            setTimeout(function() {
                form.submit()
            }, 500)
        })

        if (_gat && _gat._getTracker){
          // GA is loaded; form will submit via the _gaq.push'ed function
          event.preventDefault();
          event.stopPropagation();
        }
    }
}

r.analytics.breadcrumbs = {
    selector: '.thing, .side, .sr-list, .srdrop, .tagline, .md, .organic-listing, .gadget, .sr-interest-bar, .trending-subreddits, a, button, input',
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
