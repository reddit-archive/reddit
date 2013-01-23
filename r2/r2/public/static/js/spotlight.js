r.spotlight = {}

r.spotlight.link_by_camp = {}
r.spotlight.weights = {}
r.spotlight.organics = []
r.spotlight.interest_prob = 0
r.spotlight.promotion_prob = 1

r.spotlight.init = function(links, interest_prob, promotion_prob) {
    var link_by_camp = {},
        weights = {},
        organics = []

    for (var index in links) {
        var link = links[index][0],
            is_promo = links[index][1],
            campaign = links[index][2],
            weight = links[index][3]

        if (is_promo) {
            link_by_camp[campaign] = link
            weights[campaign] = weight
        } else {
            organics.push(link)
        }
    }

    _.extend(r.spotlight.link_by_camp, link_by_camp)
    _.extend(r.spotlight.weights, weights)
    _.extend(r.spotlight.organics, organics)
    r.spotlight.interest_prob = interest_prob
    r.spotlight.promotion_prob = promotion_prob
}

r.spotlight.shuffle = function() {
    var listing = $('.organic-listing'),
        visible = listing.find(".thing:visible")

    if (listing.length == 0) {
        $.debug('exiting, no organic listing')
        return
    }

    if(Math.random() < r.spotlight.promotion_prob) {
        $.debug('showing promoted link')
        var campaign_name = r.spotlight.weighted_lottery(r.spotlight.weights),
            link_name = r.spotlight.link_by_camp[campaign_name],
            thing = listing.find(".id-" + link_name)
        $.debug('showing ' + campaign_name)
        if (thing.hasClass('stub')) {
            $.debug('fetching')
            $.request("fetch_promo", {
                    link: link_name,
                    campaign: campaign_name,
                    show: true,
                    listing: listing.attr("id")
                },
                null, null, null, true
            )
        } else {
            $.debug('no need to fetch')
            $.debug('setting cid')
            thing.data('cid', campaign_name)
        }
        r.spotlight.help('promoted')
    } else if (Math.random() < r.spotlight.interest_prob) {
        $.debug('showing interest bar')
        var thing = listing.find(".interestbar")
        r.spotlight.help('interestbar')
    } else {
        $.debug('showing organic link')
        var name = r.spotlight.organics[Math.floor(Math.random() * r.spotlight.organics.length)],
            thing = listing.find(".id-" + name)
        r.spotlight.help('organic')
    }
    visible.hide()
    thing.show()
}

r.spotlight.help = function(type) {
    var help = $('#spotlight-help')

    if (!help.length) {
        return
    }

    help.data('HelpBubble').hide(function() {
        help.find('.help-section').hide()
        if (type == 'promoted') {
            help.find('.help-promoted').show()
        } else if (type == 'interestbar') {
            help.find('.help-interestbar').show()
        } else {
            help.find('.help-organic').show()
        }
    })
}

r.spotlight.weighted_lottery = function(weights) {
    var seed_rand = Math.random(),
        t = 0

    $.debug('random: ' + seed_rand)
    for (var name in weights) {
        weight = weights[name]
        t += weight
        $.debug(name + ': ' + weight)
        if (t > seed_rand) {
            $.debug('picked ' + name)
            return name
        }
    }
    $.debug('whoops, fell through!')
}
