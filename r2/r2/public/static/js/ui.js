r.ui = {}

r.ui.Base = function(el) {
    this.$el = $(el)
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
            this.showStatus('an error occurred (' + xhr.status + ')', true)
        }
    },

    _handleResult: function(result) {
        this.showErrors(result.json.errors)
        this.setWorking(false)
    }
})
