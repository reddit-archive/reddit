r.multi = {
    init: function() {
        this.multis = new r.multi.GlobalMultiCache()
        this.mine = new r.multi.MyMultiCollection()

        // this collection gets fetched frequently by hover bubbles.
        this.mine.fetch = _.throttle(this.mine.fetch, 60 * 1000)

        var detailsEl = $('.multi-details')
        if (detailsEl.length) {
            var multi = this.multis.touch(detailsEl.data('path'))
            new r.multi.MultiDetails({
                model: multi,
                el: detailsEl
            })
            multi.fetch()
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

    toJSON: function() {
        data = Backbone.Model.prototype.toJSON.apply(this)
        data.subreddits = this.subreddits.toJSON()
        return data
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
    },

    parse: function(data) {
        return _.map(data, function(multiData) {
            return r.multi.multis.reify(multiData)
        })
    }
})

r.multi.GlobalMultiCache = Backbone.Collection.extend({
    model: r.multi.MultiReddit,

    touch: function(path) {
        var multi = this.get(path)
        if (!multi) {
            multi = new r.multi.MultiReddit({
                path: path
            })
            this.add(multi)
        }
        return multi
    },

    reify: function(response) {
        var data = r.multi.MultiReddit.prototype.parse(response),
            multi = this.touch(data.path)

        multi.set(data)
        return multi
    }
})

r.multi.MultiSubredditItem = Backbone.View.extend({
    tagName: 'li',

    template: _.template('<a href="/r/<%= srName %>">/r/<%= srName %></a><button class="remove-sr">x</button>'),

    events: {
        'click .remove-sr': 'removeSubreddit'
    },

    render: function() {
        this.$el.addClass('sr-' + this.model.get('name'))
        this.$el.append(this.template({
            srName: this.model.get('name')
        }))

        if (r.config.logged) {
            this.bubble = new r.multi.MultiSubscribeBubble({
                parent: this.$el,
                group: this.options.bubbleGroup,
                srName: this.model.get('name')
            })
        }

        return this
    },

    remove: function() {
        if (this.bubble) {
            this.bubble.remove()
        }
        Backbone.View.prototype.remove.apply(this)
    },

    removeSubreddit: function(ev) {
        this.options.multi.removeSubreddit(this.model.get('name'))
    }
})

r.multi.MultiDetails = Backbone.View.extend({
    events: {
        'submit .add-sr': 'addSubreddit',
        'change [name="visibility"]': 'setVisibility',
        'click .show-copy': 'showCopyMulti',
        'click .copy': 'copyMulti',
        'confirm .delete': 'deleteMulti'
    },

    initialize: function() {
        this.listenTo(this.model.subreddits, 'add', this.addOne)
        this.listenTo(this.model.subreddits, 'remove', this.removeOne)
        this.listenTo(this.model.subreddits, 'reset', this.addAll)
        new r.ui.ConfirmButton({el: this.$('button.delete')})

        this.listenTo(this.model.subreddits, 'add remove', function() {
            r.ui.showWorkingDeferred(this.$el, r.ui.refreshListing())
        })

        this.model.on('request', function(model, xhr) {
            r.ui.showWorkingDeferred(this.$el, xhr)
        }, this)

        this.bubbleGroup = {}
    },

    addOne: function(sr) {
        var view = new r.multi.MultiSubredditItem({
            model: sr,
            multi: this.model,
            bubbleGroup: this.bubbleGroup
        })
        this.itemViews[sr.id] = view

        var $el = view.render().$el,
            index = this.model.subreddits.indexOf(sr),
            $list = this.$('.subreddits'),
            $cur = $list.children().eq(index)

        if ($cur.length) {
            $cur.before($el)
        } else {
            $list.append($el)
        }
    },

    removeOne: function(sr) {
        this.itemViews[sr.id].remove()
        delete this.itemViews[sr.id]
    },

    addAll: function() {
        this.itemViews = {}
        this.$('.subreddits').empty()
        this.model.subreddits.each(this.addOne, this)
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

    setVisibility: function() {
        this.model.save({
            visibility: this.$('[name="visibility"]:checked').val()
        })
    },

    showCopyMulti: function() {
        this.$('form.copy-multi')
            .show()
            .find('.copy-name').focus()
    },

    copyMulti: function(ev) {
        ev.preventDefault()

        var nameEl = this.$('.copy-multi .copy-name'),
            multiName = $.trim(nameEl.val())
        if (!multiName) {
            return
        }

        this.$('.copy-error').css('visibility', 'hidden')

        var attrs = _.clone(this.model.attributes)
        delete attrs.path
        attrs.name = multiName
        r.multi.mine.create(attrs, {
            wait: true,
            success: function(multi) {
                window.location = multi.get('path')
            },
            error: _.bind(function(multi, xhr) {
                var resp = JSON.parse(xhr.responseText)
                this.$('.copy-error')
                    .text(resp.explanation)
                    .css('visibility', 'visible')
                    .show()
            }, this),
            beforeSend: _.bind(r.ui.showWorkingDeferred, this, this.$el)
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
            srName: this.$el.data('sr_name')
        })
    }
})

r.multi.MultiSubscribeBubble = r.ui.Bubble.extend({
    className: 'multi-selector hover-bubble anchor-right',
    template: _.template('<div class="title"><strong><%= title %></strong><a class="sr" href="/r/<%= srName %>">/r/<%= srName %></a></div><div class="throbber"></div>'),
    itemTemplate: _.template('<label><input type="checkbox" data-path="<%= path %>" <%= checked %>><%= name %><a href="<%= path %>" target="_blank">&rsaquo;</a></label>'),

    events: {
        'click input': 'toggleSubscribed'
    },

    initialize: function() {
        this.listenTo(this, 'show', this.load)
        this.listenTo(r.multi.mine, 'reset add', this.render)
        r.ui.Bubble.prototype.initialize.apply(this)
    },

    load: function() {
        r.ui.showWorkingDeferred(this.$el, r.multi.mine.fetch())
    },

    render: function() {
        this.$el.html(this.template({
            title: r.strings('categorize'),
            srName: this.options.srName
        }))

        var content = $('<div class="multi-list">')
        r.multi.mine.chain()
            .sortBy(function(multi) {
                // sort multireddits containing this subreddit to the top.
                return multi.subreddits.getByName(this.options.srName)
            }, this)
            .each(function(multi) {
                content.append(this.itemTemplate({
                    name: multi.get('name'),
                    path: multi.get('path'),
                    checked: multi.subreddits.getByName(this.options.srName)
                             ? 'checked' : ''
                }))
            }, this)
        this.$el.append(content)
    },

    toggleSubscribed: function(ev) {
        var checkbox = $(ev.target),
            multi = r.multi.mine.get(checkbox.data('path'))
        if (checkbox.is(':checked')) {
            multi.addSubreddit(this.options.srName)
        } else {
            multi.removeSubreddit(this.options.srName)
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
