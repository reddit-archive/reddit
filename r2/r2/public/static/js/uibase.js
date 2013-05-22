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

r.ui.collapseListingChooser = function() {
    if (store.get('ui.collapse.listingchooser') == true) {
        $('body').addClass('listing-chooser-collapsed')
    }
}

