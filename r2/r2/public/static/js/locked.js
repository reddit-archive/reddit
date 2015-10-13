/*
  If the current post is locked, show a modal on restricted actions.

  requires r.config (base.js)
  requires r.ui.Popup (popup.js)
*/
!function(r) {
  // initialized early so click handlers can be bound on declaration
  r.locked = {};

  _.extend(r.locked, {
    init: function() {
      $('body').on('click', '.locked-error', this._handleClick);
    },

    getPopup: function() {
      // gets the cached popup instance if available, otherwise creates it.
      if (this._popup) { return this._popup; }

      var content = $('#locked-popup').html();
      var popup = new r.ui.Popup({
        size: 'large',
        content: content,
        className: 'locked-error-modal',
      });

      popup.$.on('click', '.interstitial .c-btn', this._handleModalClick);
      this._popup = popup;
      return popup;
    },

    _handleClick: function onClick(e) {
      this.getPopup()
        .show();
      return false;
    }.bind(r.locked),

    _handleModalClick: function onClick(e) {
      this.getPopup()
        .hide();
      return false;
    }.bind(r.locked),
  });
}(r);
