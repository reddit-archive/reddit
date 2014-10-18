;(function($) {
  'use strict';

  var TOOLTIP_TEMPLATE = '<div class="c-tooltip" role="tooltip"><div class="tooltip-arrow"></div><div class="tooltip-inner"></div></div>';
  var GROUP_CLASS = 'c-form-group';
  var CONTROL_CLASS = 'c-form-control';
  var CONTROL_SELECTOR = '.' + CONTROL_CLASS;
  var ERROR_FEEDBACK_CLASS = 'c-form-control-feedback-error';
  var ERROR_FEEDBACK_SELECTOR = '.' + ERROR_FEEDBACK_CLASS;
  var FEEDBACK_CLASS = 'c-has-feedback';
  var STATE_CLASSES = {
    loading: 'c-has-throbber',
    success: 'c-has-success',
    error:  'c-has-error',
  };

  function rightPosition($el) {
    var offset = $el.offset();

    return $el.outerWidth() + (offset ? offset.left : 0);
  }

  function getClassNames() {
    var classNames = STATE_CLASSES;

    if (arguments.length) {
      classNames = _.pick(classNames, _.toArray(arguments));
    }

    return _.values(classNames).concat(FEEDBACK_CLASS).join(' ');
  }

  function hasTooltip($el) {
    return !!$el.data('bs.tooltip');
  }

  var Stateify = function(element, options) {
    this.initialize(element, options);
  };

  _.extend(Stateify.prototype, {

    _currentState: null,

    initialize: function(element, options) {
      this.$el = $(element).closest('.' + GROUP_CLASS);

      return this;
    },

    getCurrentState: function() {
      return this._currentState;
    },

    set: function(state /*, args.. */) {
      if (this._currentState !== state) {
        this.clear();

        this._currentState = state;
        this.$el.addClass(getClassNames(state));
      }

      if (state === 'error') {
        this.showError.apply(this, _.toArray(arguments).slice(1));
      }

      return this;
    },

    showError: function(errorMessage) {
      var $control = this.$el.find(CONTROL_SELECTOR);
      var $feedback = this.$el.find(ERROR_FEEDBACK_SELECTOR);

      if (errorMessage) {
        // Message already set.
        if (errorMessage === $feedback.attr('data-original-title')) {
          return;
        }

        $feedback.attr('title', errorMessage);

        // If a tooltip is already attached just change the title
        if (hasTooltip($feedback)) {
          $feedback.tooltip('fixTitle');

          if ($control.is(':focus')) {
            $feedback.tooltip('show');
          }

          return;
        }
      }

      $feedback
        .tooltip({
          template: TOOLTIP_TEMPLATE,
          placement: 'right',
          trigger: 'manual',
        });

      if ($control.is(':focus') || $control.parents('form').find('[type="submit"]:focus').length) {
        $feedback.tooltip('show');

        // check that tooltip position isn't outside the viewport.
        var $viewport = $('body');
        var tip = $feedback.data('bs.tooltip');
        var $tip = tip.$tip;

        if ($viewport.length && rightPosition($viewport) < rightPosition($tip)) {
          tip.options.placement = 'top-right';

          $feedback.tooltip('show');
        }
      }

      $control
        .on('focus.c.stateify', function() {
          $control.parents('form')
            .find(ERROR_FEEDBACK_SELECTOR)
              .not($feedback)
                .tooltip('hide');

          var tooltip = $feedback.data('bs.tooltip');

          // Cancel hide after fade out.
          if (tooltip) {
            tooltip.tip().off('bsTransitionEnd');
          }

          $feedback.tooltip('show');
        })
        .on('blur.c.stateify', function() {
          $feedback.tooltip('hide');
        });

      $feedback
        .on('mouseenter.c.stateify', function() {
          if (!$control.is(':focus')) {
            $feedback.tooltip('show');
          }
        })
        .on('mouseleave.c.stateify', function() {
          if (!$control.is(':focus')) {
            $feedback.tooltip('hide');
          }
        });
    },

    clear: function() {
      var $feedback = this.$el.find(ERROR_FEEDBACK_SELECTOR);
      var $control = this.$el.find(CONTROL_SELECTOR);

      $feedback
          .tooltip('destroy')
          .removeAttr('data-original-title') // Destroy should do this but doesn't.
          .off('mouseenter.c.stateify mouseleave.c.stateify');

      $control.off('focus.c.stateify blur.c.stateify');

      this.$el.removeClass(getClassNames());

      this._currentState = null;

      return this;
    },

  });

  $.fn.stateify = function(option /* ,args... */) {
    var args = _.toArray(arguments).slice(1);

    if (option && /^get/.test(option)) {
      var data = this.data('c.stateify');

      return data && data[option].apply(data, args);
    }

    return this.each(function() {
      var $el = $(this);
      var data = $el.data('c.stateify');
      var options = typeof option === 'object' && option;

      if (!data) {
        data = new Stateify(this, options);
        $el.data('c.stateify', data);
      }

      if (typeof option === 'string') {
        data[option].apply(data, args);
      }
    });
  };

}(window.jQuery));
