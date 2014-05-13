r.spotlight = {}

r.spotlight.init = function() {
    var listing = $('.organic-listing')
    if (!listing.length) {
        return
    }

    $('.organic-listing .arrow.prev').on('click', $.proxy(this, 'prev'))
    $('.organic-listing .arrow.next').on('click', $.proxy(this, 'next'))

    var selectedThing,
        lastClickFullname = r.analytics.breadcrumbs.lastClickFullname(),
        lastClickThing = $(lastClickFullname ? '.id-' + lastClickFullname : null)
    if (lastClickThing.length && listing.has(lastClickThing).length) {
        r.debug('restoring spotlight selection to last click')
        selectedThing = {fullname: lastClickFullname}
    } else {
        selectedThing = this.chooseRandom()
    }

    this.lineup = _.chain(this.lineup)
        .reject(function(el) { return _.isEqual(selectedThing, el) })
        .shuffle()
        .unshift(selectedThing)
        .value()

    this.lineup.pos = 0
    r.spotlight._advance(0)
}

r.spotlight.setup = function(organic_links, interest_prob, show_promo, srnames) {
    this.organics = []
    this.lineup = []

    _.each(organic_links, function (name) {
        this.organics.push(name)
        this.lineup.push({fullname: name})
    }, this)

    if (interest_prob) {
        this.lineup.push('.interestbar')
    }

    this.interest_prob = interest_prob
    this.show_promo = show_promo
    this.srnames = srnames

    this.init()
}

r.spotlight.requestPromo = function() {
    return $.ajax({
        type: "POST",
        url: '/api/request_promo',
        timeout: 1000,
        data: {
            'srnames': this.srnames,
            'r': r.config.post_site
        }
    }).pipe(function(promo) {
        if (promo) {
            $item = $(promo)
            $item.hide().appendTo($('.organic-listing'))
            return $item
        } else {
            return false
        }
    })
}

r.spotlight.chooseRandom = function() {
    var listing = $('.organic-listing')
    if (this.show_promo) {
        return this.requestPromo()
    } else if (Math.random() < this.interest_prob) {
        return '.interestbar'
    } else {
        var name = this.organics[Math.floor(Math.random() * this.organics.length)]
        return {fullname: name}
    }
}

r.spotlight._materialize = function(item) {
    if (!item || item instanceof $ || item.promise) {
        return item
    }

    var listing = $('.organic-listing'),
        itemSel

    if (_.isString(item)) {
        itemSel = item
    } else if (item.campaign) {
        itemSel = '[data-cid="' + item.campaign + '"]'
    } else {
        itemSel = '[data-fullname="' + item.fullname + '"]'
    }
    var $item = listing.find(itemSel)

    if ($item.length) {
        return $item
    } else {
        r.error('unable to locate spotlight item', itemSel, item)
    }
}

r.spotlight._advancePos = function(dir) {
    return (this.lineup.pos + dir + this.lineup.length) % this.lineup.length
}

r.spotlight._materializePos = function(pos) {
    return this.lineup[pos] = this._materialize(this.lineup[pos])
}

r.spotlight._advance = function(dir) {
    var listing = $('.organic-listing'),
        $nextprev = listing.find('.nextprev'),
        visible = listing.find('.thing:visible'),
        nextPos = this._advancePos(dir),
        $next = this._materializePos(nextPos)

    var showWorking = setTimeout(function() {
        $nextprev.toggleClass('working', $next.state && $next.state() == 'pending')
    }, 200)

    this.lineup.pos = nextPos

    var $nextLoad = $.when($next)
    $nextLoad.always(_.bind(function($next) {
        clearTimeout(showWorking)

        if (this.lineup.pos != nextPos) {
            // we've been passed!
            return
        }

        if ($nextLoad.state() == "rejected" || !$next) {
            if (this.lineup.length > 1) {
                this._advance(dir || 1)
                return
            } else {
                listing.hide()
                return
            }
        }

        $nextprev.removeClass('working')
        listing.removeClass('loading')

        // match the listing background to that of the displayed thing
        listing.css('background-color', $next.css('background-color'))

        visible.hide()
        $next.show()

        this.help($next)

        // prefetch forward and backward if advanced beyond default state
        if (this.lineup.pos != 0) {
            this._materializePos(this._advancePos(1))
            this._materializePos(this._advancePos(-1))
        }
    }, this))
}

r.spotlight.next = $.proxy(r.spotlight, '_advance', 1)
r.spotlight.prev = $.proxy(r.spotlight, '_advance', -1)

r.spotlight.help = function(thing) {
    var help = $('#spotlight-help')

    if (!help.length) {
        return
    }

    // this function can be called before the help bubble has initialized
    $(function() {
        help.data('HelpBubble').hide(function() {
            help.find('.help-section').hide()
            if (thing.hasClass('promoted')) {
                help.find('.help-promoted').show()
            } else if (thing.hasClass('interestbar')) {
                help.find('.help-interestbar').show()
            } else {
                help.find('.help-organic').show()
            }
        })
    })
}
