r.spotlight = {}

r.spotlight.init = function() {
    var listing = $('.organic-listing')
    if (!listing.length) {
        return
    }

    $('.organic-listing .arrow.prev').on('click', $.proxy(this, 'prev'))
    $('.organic-listing .arrow.next').on('click', $.proxy(this, 'next'))

    _.each(this.link_by_camp, function(fullname, campaign) {
        if (!listing.find('.id-' + fullname).length) {
            this.createStub(fullname, campaign)
        }
    }, this)

    var selectedThing,
        lastClickFullname = r.analytics.breadcrumbs.lastClickFullname(),
        lastClickThing = $(lastClickFullname ? '.id-' + lastClickFullname : null)
    if (lastClickThing.length && listing.has(lastClickThing).length) {
        r.debug('restoring spotlight selection to last click')
        selectedThing = lastClickThing
    } else {
        selectedThing = this.chooseRandom()
    }

    this.lineup = _.chain(listing.find('.thing'))
        .reject(function(el) { return selectedThing.is(el) })
        .shuffle()
        .unshift(selectedThing)
        .map(function(el) {
            var fullname = $(el).data('fullname')
            if (fullname) {
                // convert things with ids to queries to handle stub replacement
                return '.id-' + fullname
            } else {
                return el
            }
        })
        .value()

    this.lineup.pos = 0
    r.spotlight._advance(0)
}

r.spotlight.setup = function(links, interest_prob, promotion_prob) {
    this.link_by_camp = {},
    this.weights = {},
    this.organics = []

    for (var index in links) {
        var link = links[index][0],
            is_promo = links[index][1],
            campaign = links[index][2],
            weight = links[index][3]

        if (is_promo) {
            this.link_by_camp[campaign] = link
            this.weights[campaign] = weight
        } else {
            this.organics.push(link)
        }
    }

    this.interest_prob = interest_prob
    this.promotion_prob = promotion_prob
}

r.spotlight.createStub = function(fullname, campaign) {
    var stub = $('<div>')
            .addClass('thing stub')
            .addClass('id-'+fullname)
            .attr('data-fullname', fullname)
            .attr('data-cid', campaign)
            .prependTo('.organic-listing')
}

r.spotlight.chooseRandom = function() {
    var listing = $('.organic-listing')
    if (!_.isEmpty(this.weights)
            && Math.random() < this.promotion_prob) {
        var campaign_name = this.weighted_lottery(this.weights),
            link_name = this.link_by_camp[campaign_name]
        return listing.find('.id-' + link_name)
    } else if (Math.random() < this.interest_prob) {
        return listing.find('.interestbar')
    } else {
        var name = this.organics[Math.floor(Math.random() * this.organics.length)]
        return listing.find('.id-' + name)
    }
}

r.spotlight._advance = function(dir) {
    var listing = $('.organic-listing'),
        visible = listing.find('.thing:visible'),
        nextPos = (this.lineup.pos + dir + this.lineup.length) % this.lineup.length,
        next = listing.find(this.lineup[nextPos])

    if (next.hasClass('stub')) {
        var fullname = next.data('fullname'),
            campaign = next.data('cid')
        r.debug('fetching promo %s from campaign %s', fullname, campaign)

        next = $.getJSON('/api/fetch_promo', {
            link: fullname,
            campaign: campaign
        }).pipe(function(resp) {
            $.handleResponse('fetch_promo')(resp)
            return listing.find('.id-' + fullname)
        })
    }

    $.when(next).done(_.bind(function(next) {
        // size the rank element so that spotlight box
        // items line up with the main page listing
        next.find('.rank')
            .width($('#siteTable .rank').width())
            .end()

        visible.hide()
        next.show()

        this.lineup.pos = nextPos
        this.help(next)
    }, this))
}

r.spotlight.next = $.proxy(r.spotlight, '_advance', 1)
r.spotlight.prev = $.proxy(r.spotlight, '_advance', -1)

r.spotlight.help = function(thing) {
    var help = $('#spotlight-help')

    if (!help.length) {
        return
    }

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
