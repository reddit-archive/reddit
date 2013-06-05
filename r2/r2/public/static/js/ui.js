r.ui.init = function() {
    // welcome bar
    if ($.cookie('reddit_first')) {
        // save welcome seen state and delete obsolete cookie
        $.cookie('reddit_first', null, {domain: r.config.cur_domain})
        store.set('ui.shown.welcome', true)
    } else if (store.get('ui.shown.welcome') != true) {
        $('.infobar.welcome').show()
        store.set('ui.shown.welcome', true)
    }

    // mobile suggest infobar
    var smallScreen = window.matchMedia
                      ? matchMedia('(max-device-width: 700px)').matches
                      : $(window).width() < 700,
        onFrontPage = $.url().attr('path') == '/'
    if (smallScreen && onFrontPage && r.config.renderstyle != 'compact') {
        var infobar = $('<div class="infobar mellow">')
            .html(r.utils.formatMarkdownLinks(
                r.strings('compact_suggest', {
                    url: location + '.compact'
                })
            ))
        $('body > .content > :not(.infobar):first').before(infobar)
    }

    $('.help-bubble').each(function(idx, el) {
        $(el).data('HelpBubble', new r.ui.Bubble({el: el}))
    })

    r.ui.PermissionEditor.init()
}

r.ui.showWorkingDeferred = function(el, deferred) {
    if (!deferred) {
        return
    }

    var flickerDelay = 200,
        key = '_workingCount',
        $el = $(el)

    // keep a count of active calls on this element so we can track multiple
    // deferreds at the same time.
    $el.data(key, ($el.data(key) || 0) + 1)

    // prevent flicker
    var flickerTimeout = setTimeout(function() {
        $el.addClass('working')
    }, flickerDelay)

    deferred.always(function() {
        clearTimeout(flickerTimeout)
        var count = Math.max(0, $el.data(key) - 1)
        $el.data(key, count)
        if (count == 0) {
            $el.removeClass('working')
        }
    })

    return deferred
}

r.ui.refreshListing = function() {
    var url = $.url(),
        params = url.param()
    params['bare'] = 'y'
    return $.ajax({
        type: 'GET',
        url: url.attr('base') + url.attr('path'),
        data: params
    }).done(function(resp) {
        $('body > .content')
            .html(resp)
            .find('.promotedlink.promoted:visible')
                .trigger('onshow')
    })
}

r.ui.Form = function(el) {
    r.ui.Base.call(this, el)
    this.$el.submit($.proxy(function(e) {
        e.preventDefault()
        this.submit(e)
    }, this))
}
r.ui.Form.prototype = $.extend(new r.ui.Base(), {
    showStatus: function(msg, isError) {
        this.$el.find('.status')
            .show()
            .toggleClass('error', !!isError)
            .text(msg)
    },

    showErrors: function(errors) {
        statusMsgs = []
        $.each(errors, $.proxy(function(i, err) {
            var errName = err[0],
                errMsg = err[1],
                errField = err[2],
                errCls = '.error.'+errName + (errField ? '.field-'+errField : ''),
                errEl = this.$el.find(errCls)

            if (errEl.length) {
                errEl.show().text(errMsg)
            } else {
                statusMsgs.push(errMsg)
            }
        }, this))

        if (statusMsgs.length) {
            this.showStatus(statusMsgs.join(', '), true)
        }
    },

    resetErrors: function() {
        this.$el.find('.error').hide()
    },

    checkCaptcha: function(errors) {
        if (this.$el.has('input[name="captcha"]').length) {
            var badCaptcha = $.grep(errors, function(el) {
                return el[0] == 'badCaptcha'
            })
            if (badCaptcha) {
                $.request("new_captcha", {id: this.$el.attr('id')})
            }
        }
    },

    serialize: function() {
        return this.$el.serializeArray()
    },

    submit: function() {
        this.resetErrors()
        r.ui.showWorkingDeferred(this.$el, this._submit())
            .done($.proxy(this, 'handleResult'))
            .fail($.proxy(this, '_handleNetError'))
    },

    _submit: function() {},

    handleResult: function(result) {
        this.checkCaptcha(result.json.errors)
        this._handleResult(result)
    },

    _handleResult: function(result) {
        this.showErrors(result.json.errors)
    },

    _handleNetError: function(xhr) {
        this.showStatus(r.strings('an_error_occurred', {status: xhr.status}), true)
    }
})

r.ui.Bubble = Backbone.View.extend({
    showDelay: 150,
    hideDelay: 750,
    animateDuration: 150,

    initialize: function() {
        this.$parent = this.options.parent || this.$el.parent()
        if (this.options.trackHover != false) {
            this.$el.hover($.proxy(this, 'queueShow'), $.proxy(this, 'queueHide'))
            this.$parent.hover($.proxy(this, 'queueShow'), $.proxy(this, 'queueHide'))
            this.$parent.click($.proxy(this, 'queueShow'))
        }
    },

    position: function() {
        var parentPos = this.$parent.offset(),
            bodyOffset = $('body').offset(),
            offsetX, offsetY
        if (this.$el.is('.anchor-top')) {
            offsetX = this.$parent.outerWidth(true) - this.$el.outerWidth(true)
            offsetY = this.$parent.outerHeight(true) + 5
            this.$el.css({
                left: parentPos.left + offsetX,
                top: parentPos.top + offsetY - bodyOffset.top
            })
        } else if (this.$el.is('.anchor-right')) {
            offsetX = 16
            offsetY = 0
            parentPos.right = $(window).width() - parentPos.left
            this.$el.css({
                right: parentPos.right + offsetX,
                top: parentPos.top + offsetY - bodyOffset.top
            })
        } else if (this.$el.is('.anchor-right-fixed')) {
            offsetX = 32
            offsetY = 0

            parentPos.top -= $(document).scrollTop()
            parentPos.left -= $(document).scrollLeft()

            this.$el.css({
                top: r.utils.clamp(parentPos.top - offsetY, 0, $(window).height() - this.$el.outerHeight()),
                left: r.utils.clamp(parentPos.left - offsetX - this.$el.width(), 0, $(window).width())
            })
        }
    },

    show: function() {
        this.cancelTimeout()
        if (this.$el.is(':visible')) {
            return
        }

        this.trigger('show')

        $('body').append(this.$el)

        this.$el.css('visibility', 'hidden').show()
        this.render()
        this.position()
        this.$el.css({
            'opacity': 1,
            'visibility': 'visible'
        })

        var isSwitch = this.options.group && this.options.group.current && this.options.group.current != this
        if (isSwitch) {
            this.options.group.current.hideNow()
        } else {
            this._animate('show')
        }

        if (this.options.group) {
            this.options.group.current = this
        }
    },

    hideNow: function() {
        this.cancelTimeout()
        if (this.options.group && this.options.group.current == this) {
            this.options.group.current = null
        }
        this.$el.hide()
    },

    hide: function(callback) {
        if (!this.$el.is(':visible')) {
            callback && callback()
            return
        }

        this._animate('hide', $.proxy(function() {
            this.hideNow()
            callback && callback()
        }, this))
    },

    _animate: function(action, callback) {
        if (!this.animateDuration) {
            callback && callback()
            return
        }

        var animProp, animOffset
        if (this.$el.is('.anchor-top')) {
            animProp = 'top'
            animOffset = '-=5'
        } else if (this.$el.is('.anchor-right')) {
            animProp = 'right'
            animOffset = '-=5'
        } else if (this.$el.is('.anchor-right-fixed')) {
            animProp = 'right'
            animOffset = '-=5'
        }
        var curOffset = this.$el.css(animProp)

        hideProps = {'opacity': 0}
        hideProps[animProp] = animOffset
        showProps = {'opacity': 1}
        showProps[animProp] = curOffset

        var start, end
        if (action == 'show') {
            start = hideProps
            end = showProps
        } else if (action == 'hide') {
            start = showProps
            end = hideProps
        }

        this.$el
            .css(start)
            .animate(end, this.animateDuration, callback)
    },

    cancelTimeout: function() {
        if (this.timeout) {
            clearTimeout(this.timeout)
            this.timeout = null
        }
    },

    queueShow: function() {
        this.cancelTimeout()
        this.timeout = setTimeout($.proxy(this, 'show'), this.showDelay)
    },

    queueHide: function() {
        this.cancelTimeout()
        this.timeout = setTimeout($.proxy(this, 'hide'), this.hideDelay)
    }
})

r.ui.PermissionEditor = function(el) {
    r.ui.Base.call(this, el)
    var params = {}
    this.$el.find('input[type="hidden"]').each(function(idx, el) {
        params[el.name] = el.value
    })
    var permission_type = params.type
    var name = params.name
    this.form_id = permission_type + "-permissions-" + name
    this.permission_info = r.strings.permissions.info[permission_type]
    this.sorted_perm_keys = $.map(this.permission_info,
                                  function(v, k) { return k })
    this.sorted_perm_keys.sort()
    this.original_perms = this._parsePerms(params.permissions)
    this.embedded = this.$el.find("form").length == 0
    this.$menu = null
    if (this.embedded) {
        this.$permissions_field = this.$el.find('input[name="permissions"]')
        this.$menu_controller = this.$el.siblings('.permissions-edit')
    } else {
        this.$menu_controller = this.$el.closest('tr').find('.permissions-edit')
    }
    this.$menu_controller.find('a').click($.proxy(this, 'show'))
    this.updateSummary()
}
r.ui.PermissionEditor.init = function() {
    function activate(target) {
        $(target).find('.permissions').each(function(idx, el) {
            $(el).data('PermissionEditor', new r.ui.PermissionEditor(el))
        })
    }
    activate('body')
    for (var permission_type in r.strings.permissions.info) {
        $('.' + permission_type + '-table')
            .on('insert-row', 'tr', function(e) { activate(this) })
    }
}
r.ui.PermissionEditor.prototype = $.extend(new r.ui.Base(), {
    _parsePerms: function(permspec) {
        var perms = {}
        permspec.split(",").forEach(function(str) {
            perms[str.substring(1)] = str[0] == "+"
        })
        return perms.all ? {"all": true} : perms
    },

    _serializePerms: function(perms) {
        if (perms.all) {
            return "+all"
        } else {
            var parts = []
            for (var perm in perms) {
                parts.push((perms[perm] ? "+" : "-") + perm)
            }
            return parts.join(",")
        }
    },

    _getNewPerms: function() {
        if (!this.$menu) {
            return null
        }
        var perms = {}
        this.$menu.find('input[type="checkbox"]').each(function(idx, el) {
            perms[$(el).attr("name")] = $(el).prop("checked")
        })
        return perms
    },

    _makeMenuLabel: function(perm) {
        var update = $.proxy(this, "updateSummary")
        var info = this.permission_info[perm]
        var $input = $('<input type="checkbox">')
            .attr("name", perm)
            .prop("checked", this.original_perms[perm])
        var $label = $('<label>')
            .append($input)
            .click(function(e) { e.stopPropagation() })
        if (perm == "all") {
            $input.change(function() {
                var disabled = $input.is(":checked")
                $label.siblings()
                    .toggleClass("disabled", disabled)
                    .find('input[type="checkbox"]').prop("disabled", disabled)
                update()
            })
            $label.append(
                document.createTextNode(r.strings.permissions.all_msg))
        } else if (info) {
            $input.change(update)
            $label.append(document.createTextNode(info.title))
            $label.attr("title", info.description)
        }
        return $label
    },

    show: function(e) {
        close_menus(e)
        this.$menu = $('<div class="permission-selector drop-choices">')
        this.$menu.append(this._makeMenuLabel("all"))
        for (var i in this.sorted_perm_keys) {
            this.$menu.append(this._makeMenuLabel(this.sorted_perm_keys[i]))
        }

        this.$menu
            .on("close_menu", $.proxy(this, "hide"))
            .find("input").first().change().end()
        if (!this.embedded) {
            var $form = this.$el.find("form").clone()
            $form.attr("id", this.form_id)
            $form.click(function(e) { e.stopPropagation() })
            this.$menu.append('<hr>', $form)
            this.$permissions_field =
                this.$menu.find('input[name="permissions"]')
        }
        this.$menu_controller.parent().append(this.$menu)
        open_menu(this.$menu_controller[0])
        return false
    },

    hide: function() {
        if (this.$menu) {
            if (this.embedded) {
                this.original_perms = this._getNewPerms()
                this.$permissions_field
                    .val(this._serializePerms(this.original_perms))
            }
            this.$menu.remove()
            this.$menu = null
            this.updateSummary()
        }
    },

    _renderBit: function(perm) {
        var info = this.permission_info[perm]
        var text
        if (perm == "all") {
            text = r.strings.permissions.all_msg
        } else if (info) {
            text = info.title
        } else {
            text = perm
        }
        var $span = $('<span class="permission-bit"/>').text(text)
        if (info) {
            $span.attr("title", info.description)
        }
        return $span
    },

    updateSummary: function() {
        var new_perms = this._getNewPerms()
        var spans = []
        if (new_perms && new_perms.all) {
            spans.push(this._renderBit("all")
                .toggleClass("added", this.original_perms.all != true))
        } else {
            if (this.original_perms.all && !new_perms) {
                spans.push(this._renderBit("all"))
            } else if (!this.original_perms.all) {
                for (var perm in this.original_perms) {
                    if (this.original_perms[perm]) {
                        if (this.embedded && !(new_perms && !new_perms[perm])) {
                            spans.push(this._renderBit(perm))
                        }
                        if (!this.embedded) {
                            spans.push(this._renderBit(perm)
                                .toggleClass("removed",
                                             new_perms != null
                                             && !new_perms[perm]))
                        }
                    }
                }
            }
            if (new_perms) {
                for (var perm in new_perms) {
                    if (this.permission_info[perm] && new_perms[perm]
                        && !this.original_perms[perm]) {
                        spans.push(this._renderBit(perm)
                            .toggleClass("added", !this.embedded))
                    }
                }
            }
        }
        if (!spans.length) {
            spans.push($('<span class="permission-bit">')
                .text(r.strings.permissions.none_msg)
                .addClass("none"))
        }
        var $new_summary = $('<div class="permission-summary">')
        for (var i = 0; i < spans.length; i++) {
            if (i > 0) {
                $new_summary.append(", ")
            }
            $new_summary.append(spans[i])
        }
        $new_summary.toggleClass("edited", this.$menu != null)
        this.$el.find(".permission-summary").replaceWith($new_summary)

        if (new_perms && this.$permissions_field) {
            this.$permissions_field.val(this._serializePerms(new_perms))
        }
    },

    onCommit: function(perms) {
        this.$el.find('input[name="permissions"]').val(perms)
        this.original_perms = this._parsePerms(perms)
        this.hide()
    }
})

r.ui.scrollFixed = function(el) {
    this.$el = $(el)
    this.$standin = null
    this.onScroll()
    $(window).bind('scroll resize', _.bind(_.throttle(this.onScroll, 20), this))
}
r.ui.scrollFixed.prototype = {
    onScroll: function() {
        if (!this.$el.is('.scroll-fixed')) {
            var margin = this.$el.outerHeight(true) - this.$el.outerHeight(false)
            this.origTop = this.$el.offset().top - margin
        }

        var enoughSpace = this.$el.height() < $(window).height()
        if (enoughSpace && $(window).scrollTop() > this.origTop) {
            if (!this.$standin) {
                this.$standin = $('<' + this.$el.prop('nodeName') + '>')
                    .css({
                        width: this.$el.width(),
                        height: this.$el.height()
                    })
                    .attr('class', this.$el.attr('class'))
                    .addClass('scroll-fixed-standin')

                this.$el
                    .addClass('scroll-fixed')
                    .css({
                        position: 'fixed',
                        top: 0
                    })
                this.$el.before(this.$standin)
            }
        } else {
            if (this.$standin) {
                this.$el
                    .removeClass('scroll-fixed')
                    .css({
                        position: '',
                        top: ''
                    })
                this.$standin.remove()
                this.$standin = null
            }
        }
    }
}

r.ui.ConfirmButton = Backbone.View.extend({
    confirmTemplate: _.template('<span class="confirmation"><span class="prompt"><%- are_you_sure %></span><button class="yes"><%- yes %></button> / <button class="no"><%- no %></button></div>'),
    events: {
        'click': 'click'
    },

    initialize: function() {
        // wrap the specified element in a <span> and move its classes over to
        // the wrapper. this is intended for progressive enhancement of a bare
        // <button> element.
        this.$target = this.$el
        this.$target.wrap('<span>')
        this.setElement(this.$target.parent())
        this.$el
            .attr('class', this.$target.attr('class'))
            .addClass('confirm-button')
        this.$target.attr('class', null)
    },

    click: function(ev) {
        var target = $(ev.target)
        if (this.$target.is(target)) {
            this.$target.hide()
            this.$el.append(this.confirmTemplate({
                are_you_sure: r.strings('are_you_sure'),
                yes: r.strings('yes'),
                no: r.strings('no')
            }))
        } else if (target.is('.no')) {
            this.$('.confirmation').remove()
            this.$target.show()
        } else if (target.is('.yes')) {
            this.$target.trigger('confirm')
        }
    }
})
