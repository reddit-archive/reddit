!function(r) {
  function isPluginExpandoButton(elem) {
    // temporary fix for RES http://redd.it/392zol
    return elem.tagName === 'A';
  }

  var Expando = Backbone.View.extend({
    buttonSelector: '.expando-button',
    expandoSelector: '.expando',
    expanded: false,

    events: {
      'click .expando-button': 'toggleExpando',
    },

    constructor: function() {
      Backbone.View.prototype.constructor.apply(this, _.toArray(arguments));

      this.afterInitialize();
    },

    initialize: function() {
      this.$button = this.$el.find(this.buttonSelector);
      this.$expando = this.$el.find(this.expandoSelector);
    },

    afterInitialize: function() {
      if (this.options.expanded) {
        this.expand();
      }
    },

    toggleExpando: function(e) {
      if (isPluginExpandoButton(e.target)) { return; }

      this.expanded ? this.collapse() : this.expand();
    },

    expand: function() {
      this.$button.addClass('expanded')
                  .removeClass('collapsed');
      this.expanded = true;
      this.show();
    },

    show: function() {
      this.$expando.show();
    },

    collapse: function() {
      this.$button.addClass('collapsed')
                  .removeClass('expanded');
      this.expanded = false;
      this.hide();
    },

    hide: function() {
      this.$expando.hide();
    }
  });

  var LinkExpando = Expando.extend({
    events: _.extend({}, Expando.prototype.events, {
      'click .open-expando': 'expand',
    }),

    initialize: function() {
      Expando.prototype.initialize.call(this);

      this.cachedHTML = this.$expando.data('cachedhtml');
      this.loaded = !!this.cachedHTML;
      this.id = this.$el.thing_id();
      
      $(document).on('hide_thing_' + this.id, function() {
        this.collapse();
      }.bind(this));
    },

    show: function() {
      if (!this.loaded) {
        $.request('expando', { link_id: this.id }, function(res) {
          var expandoHTML = $.unsafe(res);
          this.cachedHTML = expandoHTML;
          this.$expando.html(expandoHTML);
          this.loaded = true;
        }.bind(this), false, 'html', true);
      } else {
        this.$expando.html(this.cachedHTML);
      }

      this.$expando.show();
    },

    hide: function() {
      this.$expando.hide().empty();
    },
  });

  var SearchResultLinkExpando = Expando.extend({
    buttonSelector: '.search-expando-button',
    expandoSelector: '.search-expando',

    events: {
      'click .search-expando-button': 'toggleExpando',
    },

    afterInitialize: function() {
      var expandoHeight = this.$expando.innerHeight();
      var contentHeight = this.$expando.find('.search-result-body').innerHeight();

      if (contentHeight <= expandoHeight) {
        this.$button.remove();
        this.$expando.removeClass('collapsed');
        this.undelegateEvents();
      } else if (this.options.expanded) {
        this.expand();
      }
    },

    show: function() {
      this.$expando.removeClass('collapsed');
    },

    hide: function() {
      this.$expando.addClass('collapsed');
    },
  });

  $(function() {
    $('.linklisting').on('click', '.expando-button', function(e) {
      if (isPluginExpandoButton(e.target)) { return; }
    
      var $thing = $(this).closest('.thing')

      if ($thing.data('expando')) {
        return;
      }

      $thing.data('expando', true);
      var view = new LinkExpando({
        el: $thing[0],
        expanded: true,
      });
    });

    var searchResultLinkThings = $('.search-expando-button').closest('.search-result-link');

    searchResultLinkThings.each(function() {
      new SearchResultLinkExpando({ el: this });
    });
  });
}(r);
