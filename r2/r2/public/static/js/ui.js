r.ui = {}

r.ui.Base = function(el) {
    this.$el = $(el)
}

r.ui.collapsibleSideBox = function(id) {
    var $el = $('#'+id)
    return new r.ui.Collapse($el.find('.title'), $el.find('.content'), id)
}

r.ui.Collapse = function(el, target, key) {
    r.ui.Base.call(this, el)
    this.target = target
    this.key = 'ui.collapse.' + key
    this.isCollapsed = store.get(this.key) == true
    this.$el.click($.proxy(this, 'toggle', null, false))
    this.toggle(this.isCollapsed, true)
}
r.ui.Collapse.prototype = {
    animDuration: 200,

    toggle: function(collapsed, immediate) {
        if (collapsed == null) {
            collapsed = !this.isCollapsed
        }

        var duration = immediate ? 0 : this.animDuration
        if (collapsed) {
            $(this.target).slideUp(duration)
        } else {
            $(this.target).slideDown(duration)
        }

        this.isCollapsed = collapsed
        store.set(this.key, collapsed)
        this.update()
    },

    update: function() {
        this.$el.find('.collapse-button').text(this.isCollapsed ? '+' : '-')
    }
}

r.ui.Form = function(el) {
    r.ui.Base.call(this, el)
    this.$el.submit($.proxy(function(e) {
        e.preventDefault()
        this.submit(e)
    }, this))
}
r.ui.Form.prototype = $.extend(new r.ui.Base(), {
    workingDelay: 200,

    setWorking: function(isWorking) {
        // Delay the initial throbber display to prevent flashes for fast
        // operations
        if (isWorking) {
            if (!this.$el.hasClass('working') && !this._workingTimer) {
                this._workingTimer = setTimeout($.proxy(function() {
                    this.$el.addClass('working')
                }, this), this.workingDelay)
            }
        } else {
            if (this._workingTimer) {
                clearTimeout(this._workingTimer)
                delete this._workingTimer
            }
            this.$el.removeClass('working')
        }
    },

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
        this.setWorking(true)
        this._submit()
    },

    _submit: function() {},

    handleResult: function(result, err, xhr) {
        if (result) {
            this.checkCaptcha(result.json.errors)
            this._handleResult(result)
        } else {
            this.setWorking(false)
            this._handleNetError(result, err, xhr)
        }
    },

    _handleResult: function(result) {
        this.showErrors(result.json.errors)
        this.setWorking(false)
    },

    _handleNetError: function(result, err, xhr) {
        this.showStatus(r.strings.an_error_occurred + ' (' + xhr.status + ')', true)
    }
})

r.ui.HelpBubble = function(el) {
    r.ui.Base.call(this, el)
    this.$el.hover($.proxy(this, 'queueShow'), $.proxy(this, 'queueHide'))
    this.$parent = this.$el.parent()
    this.$parent.hover($.proxy(this, 'queueShow'), $.proxy(this, 'queueHide'))
    this.$parent.click($.proxy(this, 'queueShow'))
}
r.ui.HelpBubble.init = function() {
    $('.help-bubble').each(function(idx, el) {
        $(el).data('HelpBubble', new r.ui.HelpBubble(el))
    })
}
r.ui.HelpBubble.prototype = $.extend(new r.ui.Base(), {
    showDelay: 150,
    hideDelay: 750,

    show: function() {
        this.cancelTimeout()

        $('body').append(this.$el)

        var parentPos = this.$parent.offset()
        this.$el
            .show()
            .offset({
                left: parentPos.left + this.$parent.outerWidth(true) - this.$el.outerWidth(true),
                top: parentPos.top + this.$parent.outerHeight(true) + 5
            })
    },

    hide: function(callback) {
        this.$el.fadeOut(150, $.proxy(function() {
            this.$el.hide()
            this.$parent.append(this.$el)
            if (callback) {
                callback()
            }
        }, this))
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
