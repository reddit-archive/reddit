r.multi = {
    init: function() {
        this.multis = new r.multi.GlobalMultiCache()
        this.mine = new r.multi.MyMultiCollection()

        // this collection gets fetched frequently by hover bubbles.
        this.mine.fetch = _.throttle(this.mine.fetch, 60 * 1000)

        var detailsEl = $('.multi-details')
        if (detailsEl.length) {
            var multi = this.multis.touch(detailsEl.data('path'))
            multi.fetch()

            var detailsView = new r.multi.MultiDetails({
                model: multi,
                el: detailsEl
            }).render()

            if (location.hash == '#created') {
                detailsView.focusAdd()
            }
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

    initialize: function(attributes, options) {
        this.uncreated = options && !!options.isNew
        this.subreddits = new r.multi.MultiRedditList(this.get('subreddits'), {parse: true})
        this.subreddits.url = this.url() + '/r/'
        this.on('change:subreddits', function(model, value) {
            this.subreddits.set(value, {parse: true})
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

    isNew: function() {
        return this.uncreated
    },

    name: function() {
        return this.get('path').split('/').pop()
    },

    sync: function(method, model, options) {
        var res = Backbone.sync.apply(this, arguments)
        if (method == 'create') {
            res.done(_.bind(function() {
                // upon successful creation, unset new flag
                this.uncreated = false
            }, this))
        }
        return res
    },

    addSubreddit: function(names, options) {
        names = r.utils.tup(names)
        if (names.length == 1) {
            this.subreddits.create({name: names[0]}, options)
        } else {
            // batch add by syncing the entire multi
            var subreddits = this.subreddits,
                tmp = subreddits.clone()
            tmp.add(_.map(names, function(srName) {
                return {name: srName}
            }))

            // temporarily swap out the subreddits collection so we can
            // serialize and send the new data without updating the UI
            // this is similar to how the "wait" option is handled in
            // Backbone.Model.set
            this.subreddits = tmp
            this.save(null, options)
            this.subreddits = subreddits
        }
    },

    removeSubreddit: function(name, options) {
        this.subreddits.getByName(name).destroy(options)
    },

    copyTo: function(newMulti) {
        var attrs = _.clone(this.attributes)
        delete attrs.path
        attrs.visibility = 'private'
        newMulti.set(attrs)
        return newMulti
    }
})

r.multi.MyMultiCollection = Backbone.Collection.extend({
    url: '/api/multi/mine',
    model: r.multi.MultiReddit,
    comparator: function(model) {
        return model.get('path').toLowerCase()
    },

    parse: function(data) {
        return _.map(data, function(multiData) {
            return r.multi.multis.reify(multiData)
        })
    },

    pathByName: function(name) {
        return '/user/' + r.config.logged + '/m/' + name
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

    template: _.template('<a href="/r/<%- srName %>">/r/<%- srName %></a><button class="remove-sr">x</button>'),

    events: {
        'click .remove-sr': 'removeSubreddit'
    },

    render: function() {
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
        'confirm .delete': 'deleteMulti'
    },

    initialize: function() {
        this.listenTo(this.model, 'change', this.render)
        this.listenTo(this.model.subreddits, 'add', this.addOne)
        this.listenTo(this.model.subreddits, 'remove', this.removeOne)
        this.listenTo(this.model.subreddits, 'sort', this.resort)
        this.listenTo(this.model.subreddits, 'add remove reset', this.render)
        new r.ui.ConfirmButton({el: this.$('button.delete')})

        this.listenTo(this.model.subreddits, 'add remove', function() {
            r.ui.showWorkingDeferred(this.$el, r.ui.refreshListing())
        })

        this.model.on('request', function(model, xhr) {
            r.ui.showWorkingDeferred(this.$el, xhr)
        }, this)

        this.bubbleGroup = {}
        this.addBubble = new r.multi.MultiAddNoticeBubble({
            parent: this.$('.add-sr .sr-name'),
            trackHover: false
        })

        this.itemViews = {}
        this.$('.subreddits').empty()
        this.model.subreddits.each(this.addOne, this)
    },

    render: function() {
        var canEdit = this.model.get('can_edit')
        if (canEdit) {
            if (this.model.subreddits.isEmpty()) {
                this.addBubble.show()
            } else {
                this.addBubble.hide()
            }
        }

        this.$el.toggleClass('readonly', !canEdit)

        return this
    },

    addOne: function(sr) {
        var view = new r.multi.MultiSubredditItem({
            model: sr,
            multi: this.model,
            bubbleGroup: this.bubbleGroup
        })
        this.itemViews[sr.id] = view
        this.$('.subreddits').append(view.render().$el)
    },

    resort: function() {
        this.model.subreddits.each(function(sr) {
            this.itemViews[sr.id].$el.appendTo(this.$('.subreddits'))
        }, this)
    },

    removeOne: function(sr) {
        this.itemViews[sr.id].remove()
        delete this.itemViews[sr.id]
    },

    addSubreddit: function(ev) {
        ev.preventDefault()

        var nameEl = this.$('.add-sr .sr-name'),
            srNames = nameEl.val()
        srNames = _.compact(srNames.split(/[\/+,\s]+(?:r\/)?/))
        if (!srNames.length) {
            return
        }

        nameEl.val('')
        this.$('.add-error').css('visibility', 'hidden')
        this.model.addSubreddit(srNames, {
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
        var $copyForm = this.$('form.copy-multi')

        $copyForm
            .show()
            .find('.multi-name')
                .val(this.model.name())
                .select()
                .focus()

        this.copyForm = new r.multi.MultiCreateForm({
            el: $copyForm,
            navOnCreate: true,
            createMulti: _.bind(function(name) {
                var newMulti = new r.multi.MultiReddit({
                    path: r.multi.mine.pathByName(name)
                }, {isNew: true})
                this.model.copyTo(newMulti)
                return newMulti
            }, this)
        })
    },

    deleteMulti: function() {
        this.model.destroy({
            success: function() {
                window.location = '/'
            }
        })
    },

    focusAdd: function() {
        this.$('.add-sr .sr-name').focus()
    }
})

r.multi.MultiAddNoticeBubble = r.ui.Bubble.extend({
    className: 'multi-add-notice hover-bubble anchor-right',
    template: _.template('<h3><%- awesomeness_goes_here %></h3><p><%- add_multi_sr %></p>'),

    render: function() {
        this.$el.html(this.template({
            awesomeness_goes_here: r.strings('awesomeness_goes_here'),
            add_multi_sr: r.strings('add_multi_sr')
        }))
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
    template: _.template('<div class="title"><strong><%- title %></strong><a class="sr" href="/r/<%- srName %>">/r/<%- srName %></a></div><div class="throbber"></div>'),
    itemTemplate: _.template('<label><input class="add-to-multi" type="checkbox" data-path="<%- path %>" <%- checked %>><%- name %><a href="<%- path %>" target="_blank">&rsaquo;</a></label>'),
    itemCreateTemplate: _.template('<label><form class="create-multi"><input type="text" class="multi-name" placeholder="<%- createMsg %>"><div class="error create-multi-error"></div></form></label>'),

    events: {
        'click .add-to-multi': 'toggleSubscribed'
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
        content.append(this.itemCreateTemplate({
            createMsg: r.strings('create_multi')
        }))
        this.$el.append(content)

        this.createForm = new r.multi.MultiCreateForm({
            el: this.$('form.create-multi')
        })
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

r.multi.MultiCreateForm = Backbone.View.extend({
    events: {
        'submit': 'createMulti'
    },

    initialize: function() {
        this.showWorkingDeferred = _.bind(r.ui.showWorkingDeferred, this, this.$el)
    },

    createMulti: function(ev) {
        ev.preventDefault()

        var name = this.$('input.multi-name').val()
        name = $.trim(name)
        if (!name) {
            return
        }

        var newMulti
        if (this.options.createMulti) {
            newMulti = this.options.createMulti(name)
        } else {
            var newMulti = new r.multi.MultiReddit({
                path: r.multi.mine.pathByName(name)
            }, {isNew: true})
        }

        r.multi.mine.create(newMulti, {
            wait: true,
            beforeSend: this.showWorkingDeferred,
            success: _.bind(function(multi) {
                this.trigger('create', multi)
                if (this.options.navOnCreate) {
                    window.location = multi.get('path') + '#created'
                }
            }, this),
            error: _.bind(function(multi, xhr) {
                var resp = JSON.parse(xhr.responseText)
                this.showError(resp.explanation)
            }, this)
        })
    },

    showError: function(error) {
        this.$('.error').text(error).show()
    },

    focus: function() {
        this.$('.multi-name').focus()
    }
})

r.multi.ListingChooser = Backbone.View.extend({
    events: {
        'click .create button': 'createClick',
        'click .grippy': 'toggleCollapsed'
    },

    createClick: function(ev) {
        if (!this.$('.create').is('.expanded')) {
            ev.preventDefault()
            this.$('.create').addClass('expanded')
            this.createForm = new r.multi.MultiCreateForm({
                el: this.$('.create form'),
                navOnCreate: true
            })
            this.createForm.focus()
        }
    },

    toggleCollapsed: function() {
        $('body').toggleClass('listing-chooser-collapsed')
        store.set('ui.collapse.listingchooser', $('body').is('.listing-chooser-collapsed'))
    }
})
