/*
  If the current user is 'in timeout', show a modal on restricted actions.

  requires r.config (base.js)
  requires r.ui.Popup (popup.js)
 */
!function(r) {
  // initialized early so click handlers can be bound on declaration
  r.timeouts = {};

  _.extend(r.timeouts, {
    init: function() {
      if (!r.config.user_in_timeout) { return; }
      
      $('body').on('click', '.access-required', this._handleClick);
      $('.access-required').removeAttr('onclick');
      $('body.comments-page').on('focus', '.usertext.cloneable textarea', this._handleClick);
      $('body.comments-page').on('submit', 'form.usertext.cloneable', this._handleClick);
      $('body.comments-page form.usertext.cloneable').removeAttr('onsubmit');
    },

    getPopup: function() {
      // gets the cached popup instance if available, otherwise creates it.
      if (this._popup) { return this._popup; }

      var content = $('#access-popup').html();
      var popup = new r.ui.Popup({
          size: 'large',
          content: content,
          className: 'access-denied-modal',
      });

      popup.$.on('click', '.interstitial .c-btn', this._handleModalClick);
      this._popup = popup;
      return popup;
    },

    _handleClick: function onClick(e) {
      this.getPopup()
          .show();
      return false;
    }.bind(r.timeouts),

    _handleModalClick: function onClick(e) {
      this.getPopup()
          .hide();
      return false;
    }.bind(r.timeouts),

    isLinkRestricted: function(el) {
      return $(el).hasClass('access-required') && r.config.user_in_timeout;
    },
  });
}(r);
