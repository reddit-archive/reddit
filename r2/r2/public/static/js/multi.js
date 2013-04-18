r.multi = {
    init: function() {
        this.mine = new r.multi.MyMultiCollection()

        var detailsEl = $('.multi-details')
        if (detailsEl.length) {
            var multi = new r.multi.MultiReddit({
                path: detailsEl.data('path')
            })
            multi.fetch()
            new r.multi.MultiDetails({
                model: multi,
                el: detailsEl
            })
        }

        var subscribeBubbleGroup = {}
        $('.subscribe-button').each(function(idx, el) {
            new r.multi.SubscribeButton({
                el: el,
                bubbleGroup: subscribeBubbleGroup
            })
        })

        $('.listing-chooser').each(function(idx, el) {
            new r.multi.ListingChooser({el: el})
        })
    }
}

r.multi.MultiRedditList = Backbone.Collection.extend({
    model: Backbone.Model.extend({
        initialize: function() {
            this.id = this.get('name').toLowerCase()
        }
    }),
    comparator: function(model) {
        return model.id
    },

    getByName: function(name) {
        return this.get(name.toLowerCase())
    }
})

r.multi.MultiReddit = Backbone.Model.extend({
    idAttribute: 'path',
    url: function() {
        return r.utils.joinURLs('/api/multi', this.id)
    },

    initialize: function() {
        this.subreddits = new r.multi.MultiRedditList(this.get('subreddits'))
        this.subreddits.url = this.url() + '/r/'
        this.on('change:subreddits', function(model, value) {
            this.subreddits.reset(value)
        }, this)
        this.subreddits.on('request', function(model, xhr, options) {
            this.trigger('request', model, xhr, options)
        }, this)
    },

    parse: function(response) {
        return response.data
    },

    addSubreddit: function(name, options) {
        this.subreddits.create({name: name}, options)
    },

    removeSubreddit: function(name, options) {
        this.subreddits.getByName(name).destroy(options)
    }
})

r.multi.MyMultiCollection = Backbone.Collection.extend({
    url: '/api/multi/mine',
    model: r.multi.MultiReddit,
    comparator: function(model) {
        return model.get('path').toLowerCase()
    },

    create: function(attributes, options) {
        if ('name' in attributes) {
            attributes['path'] = '/user/' + r.config.logged + '/m/' + attributes['name']
            delete attributes['name']
        }
        Backbone.Collection.prototype.create.call(this, attributes, options)
    }
})

r.multi.MultiDetails = Backbone.View.extend({
    itemTemplate: _.template('<li data-name="<%= name %>"><a href="/r/<%= name %>">/r/<%= name %></a><button class="remove-sr">x</button></li>'),
    events: {
        'submit .add-sr': 'addSubreddit',
        'click .remove-sr': 'removeSubreddit',
        'change [name="visibility"]': 'setVisibility',
        'confirm .delete': 'deleteMulti'
    },

    initialize: function() {
        this.showWorkingDeferred = _.partial(r.ui.showWorkingDeferred, this.$el)
        this.model.subreddits.on('add remove', this.render, this)
        this.model.on('request', function(model, xhr) {
            this.showWorkingDeferred(xhr)
        }, this)
        new r.ui.ConfirmButton({el: this.$('button.delete')})
    },

    render: function() {
        var srList = this.$('.subreddits')
        srList.empty()
        this.model.subreddits.each(function(sr) {
            srList.append(this.itemTemplate({
                name: sr.get('name')
            }))
        }, this)
    },

    addSubreddit: function(ev) {
        ev.preventDefault()

        var nameEl = this.$('.add-sr .sr-name'),
            srName = $.trim(nameEl.val())
        srName = srName.split('r/').pop()
        if (!srName) {
            return
        }

        nameEl.val('')
        this.$('.add-error').css('visibility', 'hidden')
        this.model.addSubreddit(srName, {
            wait: true,
            success: _.bind(function() {
                this.showWorkingDeferred(r.ui.refreshListing())
                this.$('.add-error').hide()
            }, this),
            error: _.bind(function(model, xhr) {
                var resp = JSON.parse(xhr.responseText)
                this.$('.add-error')
                    .text(resp.explanation)
                    .css('visibility', 'visible')
                    .show()
            }, this)
        })
    },

    removeSubreddit: function(ev) {
        var srName = $(ev.target).parent().data('name')
        this.model.removeSubreddit(srName, {
            success: _.compose(this.showWorkingDeferred, r.ui.refreshListing)
        })
    },

    setVisibility: function() {
        this.model.save({
            visibility: this.$('[name="visibility"]:checked').val()
        })
    },

    deleteMulti: function() {
        this.model.destroy({
            success: function() {
                window.location = '/'
            }
        })
    }
})

r.multi.SubscribeButton = Backbone.View.extend({
    initialize: function() {
        this.bubble = new r.multi.MultiSubscribeBubble({
            parent: this.$el,
            group: this.options.bubbleGroup,
            sr_name: this.$el.data('sr_name')
        })
    }
})

r.multi.MultiSubscribeBubble = r.ui.Bubble.extend({
    className: 'multi-selector hover-bubble anchor-right',
    template: _.template('<div class="title"><strong><%= title %></strong><a class="sr" href="/r/<%= sr_name %>">/r/<%= sr_name %></a></div><div class="throbber"></div>'),
    itemTemplate: _.template('<label><input type="checkbox" data-path="<%= path %>" <%= checked %>><%= name %><a href="<%= path %>" target="_blank">&rsaquo;</a></label>'),

    events: {
        'click input': 'toggleSubscribed'
    },

    initialize: function() {
        this.on('show', this.load, this)
        this.listenTo(r.multi.mine, 'reset add', this.render)
        r.ui.Bubble.prototype.initialize.apply(this)
    },

    load: function() {
        r.ui.showWorkingDeferred(this.$el, r.multi.mine.fetch())
    },

    render: function() {
        this.$el.html(this.template({
            title: r.strings('categorize'),
            sr_name: this.options.sr_name
        }))

        var content = $('<div class="multi-list">')
        r.multi.mine.chain()
            .sortBy(function(multi) {
                // sort multireddits containing this subreddit to the top.
                return multi.subreddits.getByName(this.options.sr_name)
            }, this)
            .each(function(multi) {
                content.append(this.itemTemplate({
                    name: multi.get('name'),
                    path: multi.get('path'),
                    checked: multi.subreddits.getByName(this.options.sr_name)
                             ? 'checked' : ''
                }))
            }, this)
        this.$el.append(content)
    },

    toggleSubscribed: function(ev) {
        var checkbox = $(ev.target),
            multi = r.multi.mine.get(checkbox.data('path'))
        if (checkbox.is(':checked')) {
            multi.addSubreddit(this.options.sr_name)
        } else {
            multi.removeSubreddit(this.options.sr_name)
        }
    }
})

r.multi.ListingChooser = Backbone.View.extend({
    events: {
        'submit .create': 'createClick'
    },

    createClick: function(ev) {
        ev.preventDefault()
        if (!this.$('.create').is('.expanded')) {
            this.$('.create').addClass('expanded')
            this.$('.create input[type="text"]').focus()
        } else {
            var name = this.$('.create input[type="text"]').val()
            name = $.trim(name)
            if (name) {
                r.multi.mine.create({name: name}, {
                    success: function(multi) {
                        window.location = multi.get('path')
                    },
                    error: _.bind(function(multi, xhr) {
                        var resp = JSON.parse(xhr.responseText)
                        this.$('.error').text(resp.explanation).show()
                    }, this),
                    beforeSend: _.bind(r.ui.showWorkingDeferred, this, this.$el)
                })
            }
        }
    }
})
