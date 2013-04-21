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

r.spotlight.setup = function(links, interest_prob, promotion_prob) {
    this.link_by_camp = {},
    this.weights = {},
    this.organics = []
    this.lineup = []

    for (var index in links) {
        var link = links[index][0],
            is_promo = links[index][1],
            campaign = links[index][2],
            weight = links[index][3]

        if (is_promo) {
            this.link_by_camp[campaign] = link
            this.weights[campaign] = weight
            this.lineup.push({fullname: link, campaign: campaign})
        } else {
            this.organics.push(link)
            this.lineup.push({fullname: link})
        }
    }
    this.lineup.push('.interestbar')

    this.interest_prob = interest_prob
    this.promotion_prob = promotion_prob

    this.init()
}

r.spotlight.chooseRandom = function() {
    var listing = $('.organic-listing')
    if (!_.isEmpty(this.weights)
            && Math.random() < this.promotion_prob) {
        var campaign_name = this.weighted_lottery(this.weights),
            link_name = this.link_by_camp[campaign_name]
        return {fullname: link_name, campaign: campaign_name}
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
    } else {
        itemSel = '[data-fullname="' + item.fullname + '"]'
        if (item.campaign) {
            itemSel += '[data-cid="' + item.campaign + '"]'
        }
    }
    var $item = listing.find(itemSel)

    if ($item.length) {
        return $item
    } else if (item.campaign) {
        r.debug('fetching promo %s from campaign %s', item.fullname, item.campaign)

        return $.get('/api/fetch_promo', {
            link: item.fullname,
            campaign: item.campaign
        }).pipe(function (data) {
            $item = $(data)
            $item.hide().appendTo(listing)
            return $item
        })
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
    $.when($next).done(_.bind(function($next) {
        clearTimeout(showWorking)

        if (this.lineup.pos != nextPos) {
            // we've been passed!
            return
        }

        $nextprev.removeClass('working')
        listing.removeClass('loading')

        // size the rank element so that spotlight box
        // items line up with the main page listing
        $next
            .find('.rank')
            .width($('#siteTable .rank').width())
            .end()

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

r.spotlight.weighted_lottery = function(weights) {
    var seed_rand = Math.random(),
        t = 0

    for (var name in weights) {
        weight = weights[name]
        t += weight
        if (t > seed_rand) {
            return name
        }
    }
    r.warn('weighted_lottery fell through!')
}
