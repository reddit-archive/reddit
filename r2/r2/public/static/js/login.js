r.login = {
    post: function(form, action) {
        if (r.config.cnameframe && !r.config.https_endpoint) {
            form.$el.unbind()
            form.$el.submit()
            return
        }

        var username = $('input[name="user"]', form.$el).val(),
            endpoint = r.config.https_endpoint || ('http://'+r.config.ajax_domain),
            apiTarget = endpoint+'/api/'+action+'/'+username

        if (r.config.currentOrigin == endpoint || $.support.cors) {
            var params = form.serialize()
            params.push({name:'api_type', value:'json'})
            return $.ajax({
                url: apiTarget,
                type: 'POST',
                dataType: 'json',
                data: params,
                xhrFields: {
                    withCredentials: true
                }
            })
        } else {
            var iframe = $('<iframe>'),
                postForm = form.$el.clone(true),
                frameName = ('resp'+Math.random()).replace('.', '')

            iframe
                .css('display', 'none')
                .attr('name', frameName)
                .appendTo('body')

            iframe[0].contentWindow.name = frameName

            postForm
                .unbind()
                .css('display', 'none')
                .attr('action', apiTarget)
                .attr('target', frameName)
                .appendTo('body')
            
            $('<input>')
                .attr({
                    type: 'hidden',
                    name: 'api_type',
                    value: 'json'
                })
                .appendTo(postForm)

            $('<input>')
                .attr({
                    type: 'hidden',
                    name: 'hoist',
                    value: r.login.hoist.type
                })
                .appendTo(postForm)

            var deferred = r.login.hoist.watch(action)
            if (!r.config.debug) {
                deferred.done(function() {
                    iframe.remove()
                    postForm.remove()
                })
            }

            postForm.submit()
            return deferred
        }
    }
}

r.login.hoist = {
    type: 'cookie',
    watch: function(name) {
        var cookieName = 'hoist_'+name,
            deferred = new $.Deferred

        var interval = setInterval(function() {
            data = $.cookie(cookieName)
            if (data) {
                try {
                    data = JSON.parse(data)
                } catch(e) {
                    data = null
                }
                $.cookie(cookieName, null, {domain:r.config.cur_domain, path:'/'})
                clearInterval(interval)
                deferred.resolve(data)
            }
        }, 100)

        return deferred
    }
}

r.login.ui = {
    init: function() {
        if (!r.config.logged) {
            $('.content form.login-form, .side form.login-form').each(function(i, el) {
                new r.ui.LoginForm(el)
            })

            $('.content form.register-form').each(function(i, el) {
                new r.ui.RegisterForm(el)
            })

            this.popup = new r.ui.LoginPopup($('.login-popup')[0])

            $(document).delegate('.login-required', 'click', $.proxy(this, 'loginRequiredAction'))
        }
    },

    loginRequiredAction: function(e) {
        if (r.config.logged) {
            return true
        } else {
            var el = $(e.target),
                href = el.attr('href'),
                dest
            if (href && href != '#' && !/\/login\/?$/.test(href)) {
                // User clicked on a link that requires login to continue
                dest = href
            } else {
                // User clicked on a thing button that requires login
                var thing = el.thing()
                if (thing.length) {
                    dest = thing.find('.comments').attr('href')
                }
            }

            this.popup.showLogin(true, dest && $.proxy(function() {
                this.popup.loginForm.$el.addClass('working')
                window.location = dest
            }, this))

            return false
        }
    }
}

r.ui.LoginForm = function() {
    r.ui.Form.apply(this, arguments)
}
r.ui.LoginForm.prototype = $.extend(new r.ui.Form(), {
    showErrors: function(errors) {
        r.ui.Form.prototype.showErrors.call(this, errors)
        if (errors.length) {
            this.$el.find('.recover-password')
                .addClass('attention')
        }
    },

    showStatus: function() {
        this.$el.find('.error').css('opacity', 1)
        r.ui.Form.prototype.showStatus.apply(this, arguments)
    },
    
    resetErrors: function() {
        if (this.$el.hasClass('login-form-side')) {
            // Dim the error in place so the form doesn't change size.
            var errorEl = this.$el.find('.error')
            if (errorEl.is(':visible')) {
                errorEl.fadeTo(100, .35)
            }
        } else {
            r.ui.Form.prototype.resetErrors.apply(this, arguments)
        }
    },

    _submit: function() {
        return r.login.post(this, 'login')
    },

    _handleResult: function(result) {
        if (!result.json.errors.length) {
            // Success. Load the destination page with the new session cookie.
            if (this.successCallback) {
                this.successCallback(result)
            } else {
                this.$el.addClass('working')
                var base = r.config.extension ? '/.'+r.config.extension : '/',
                    defaultDest = /\/login\/?$/.test($.url().attr('path')) ? base : window.location,
                    destParam = this.$el.find('input[name="dest"]').val()
                window.location = destParam || defaultDest
            }
        } else {
            r.ui.Form.prototype._handleResult.call(this, result)
        }
    },

    _handleNetError: function(xhr) {
        r.ui.Form.prototype._handleNetError.apply(this, arguments)
        if (xhr.status == 0 && r.config.currentOrigin != r.config.https_endpoint) {
            $('<p>').append(
                $('<a>')
                    .text(r.strings('login_fallback_msg'))
                    .attr('href', r.config.https_endpoint + '/login')
            ).appendTo(this.$el.find('.status'))
        }
    },

    focus: function() {
        this.$el.find('input[name="user"]').focus()
    }
})


r.ui.RegisterForm = function() {
    r.ui.Form.apply(this, arguments)
    this.checkUsernameDebounced = _.debounce($.proxy(this, 'checkUsername'), 500)
    this.$user = this.$el.find('[name="user"]')
    this.$user.on('keyup', $.proxy(this, 'usernameChanged'))
    this.$submit = this.$el.find('.submit button')
}
r.ui.RegisterForm.prototype = $.extend(new r.ui.Form(), {
    usernameChanged: function() {
        var name = this.$user.val()
        if (name == this._priorName) {
            return
        } else {
            this._priorName = name
        }

        this.$el.find('.error.field-user').hide()
        this.$submit.attr('disabled', false)
        this.checkUsernameDebounced(name)
        this.$el.toggleClass('name-checking', !!name)
    },

    checkUsername: function(name) {
        if (name) {
            $.ajax({
                url: '/api/username_available.json',
                data: {user: name},
                success: $.proxy(this, 'displayUsernameStatus'),
                complete: $.proxy(function() { this.$el.removeClass('name-checking') }, this)
            })
        } else {
            this.$el.removeClass('name-available name-taken')
        }
    },

    displayUsernameStatus: function(result) {
        if (result.json && result.json.errors) {
            this.showErrors(result.json.errors)
            this.$submit.attr('disabled', true)
        } else {
            this.$el
                .removeClass('name-available name-taken')
                .addClass(result ? 'name-available' : 'name-taken')
            this.$submit.attr('disabled', result == false)
        }
    },

    _submit: function() {
        return r.login.post(this, 'register')
    },

    _handleResult: r.ui.LoginForm.prototype._handleResult,
    focus: r.ui.LoginForm.prototype.focus
})

r.ui.LoginPopup = function(el) {
    r.ui.Base.call(this, el)
    this.loginForm = new r.ui.LoginForm(this.$el.find('form.login-form:first'))
    this.registerForm = new r.ui.RegisterForm(this.$el.find('form.register-form:first'))
}
r.ui.LoginPopup.prototype = $.extend(new r.ui.Base(), {
    show: function(notice, callback) {
        this.loginForm.successCallback = callback
        this.registerForm.successCallback = callback
        $.request("new_captcha", {id: this.$el.attr('id')})
        this.$el
            .find(".cover-msg").toggle(!!notice).end()
            .find('.popup').css('top', $(document).scrollTop()).end()
            .show()
    },

    showLogin: function() {
        this.show.apply(this, arguments)
        this.loginForm.focus()
    },

    showRegister: function() {
        this.show.apply(this, arguments)
        this.registerForm.focus()
    }
})
