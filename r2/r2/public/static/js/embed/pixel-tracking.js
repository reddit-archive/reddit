!function(App, window, undefined) {

  var PixelTracker = App.PixelTracker = function(options) {
    this._pixelTrackingUrl = options.url;
  };

  PixelTracker.prototype.send = function(payload, callback) {
    callback = callback || function() {};

    if (!this._pixelTrackingUrl || !payload) {
      callback();

      return;
    }

    payload.uuid = App.utils.uuid();

    var image = new Image();
    var buster = Math.round(Math.random() * 2147483647);

    image.onload = callback;
    image.src = this._pixelTrackingUrl +
                '?r=' + buster +
                '&data=' + encodeURIComponent(JSON.stringify(payload));
  };

}((window.rembeddit = window.rembeddit || {}), this);
