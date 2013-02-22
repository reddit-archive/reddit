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

r.ui.init = function() {
    r.ui.HelpBubble.init()
    r.ui.PermissionEditor.init()
}
