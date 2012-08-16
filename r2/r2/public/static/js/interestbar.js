r.interestbar = {
    init: function() {
        new r.ui.InterestBar($('.sr-interest-bar'))
    }
}

r.ui.InterestBar = function() {
    r.ui.Base.apply(this, arguments)
    this.$query = this.$el.find('.query')
    this.queryChangedDebounced = _.debounce($.proxy(this, 'queryChanged'), 500)
    this.$query.on('keyup', $.proxy(this, 'keyPressed'))

    this.$query
        .on('focus', $.proxy(function() {
            this.$el.addClass('focus')
        }, this))
        .on('blur', $.proxy(function() {
            this.$el.removeClass('focus')
        }, this))
}
r.ui.InterestBar.prototype = {
    keyPressed: function() {
        var query = this.$query.val()
        query = $.trim(query)
        if (query != this._lastQuery) {
            this._lastQuery = query
            this.$el.addClass('working')
            this.queryChangedDebounced(query)
        }

        if (!query) {
            this.$el.removeClass('working error')
            this.hideResults()
        }
    },

    queryChanged: function(query) {
        if (query) {
            $.ajax({
                url: '/api/subreddits_by_topic.json',
                data: {'query': query},
                success: $.proxy(this, 'displayResults'),
                error: $.proxy(this, 'displayError')
            })
        }
    },

    displayResults: function(results) {
        this.$el.removeClass('working error')

        var first = this.$el.find('.results li:first'),
            last = this.$el.find('.results li:last')

        var item = _.template(
            '<li><a href="/r/<%= name %>" target="_blank">'
                +'/r/<%= name %>'
            +'</a></li>'
        )

        this.$el.find('.results')
            .empty()
            .append(first)
            .append(_.map(results, item).join(''))
            .append(last)
            .slideDown(150)
    },

    hideResults: function() {
        this.$el.find('.results').slideUp(150)
    },

    displayError: function(xhr) {
        this.$el
            .removeClass('working')
            .addClass('error')
            .find('.error-caption')
                .text(r.strings.an_error_occurred_friendly + ' (' + xhr.status + ')')

        this.hideResults()
    }
}
