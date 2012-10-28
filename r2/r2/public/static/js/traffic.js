r.traffic = {
    init: function () {
        // add a simple method of jumping to any subreddit's traffic page
        if ($('body').hasClass('traffic-sitewide'))
            this.addSubredditSelector()
    },

    addSubredditSelector: function () {
        $('<form>').append(
            $('<fieldset>').append(
                $('<legend>').text(r.strings('view_subreddit_traffic')),
                $('<input type="text" id="srname">'),
                $('<input type="submit">').attr('value', r.strings('go'))
            )
        ).submit(r.traffic._onSubredditSelected)
        .prependTo('.traffic-tables-side')
    },

    _onSubredditSelected: function () {
        var srname = $(this.srname).val()

        window.location = window.location.protocol + '//' +
                          r.config.cur_domain +
                          '/r/' + srname +
                          '/about/traffic'

        return false
    }
}

$(function () {
    r.traffic.init()
})
