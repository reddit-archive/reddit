;(function(App, window, undefined) {
  var hasOwnProperty = Object.prototype.hasOwnProperty;

  App.utils = App.utils || {};

  // http://stackoverflow.com/a/8809472/704286
  App.utils.uuid = function() {
    var d = new Date().getTime();
    var uuid = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        var r = (d + Math.random() * 16) % 16 | 0;

        d = Math.floor(d / 16);

        return (c == 'x' ? r : (r & 0x3 | 0x8)).toString(16);
    });

    return uuid;
  };

  // Given an object, serialize it into a set of urlencoded query parameters
  App.utils.serialize = function(obj) {
    var params = [];

    for (var p in obj) {
      if (obj.hasOwnProperty(p)) {
        params.push(encodeURIComponent(p) + '=' + encodeURIComponent(obj[p]));
      }
    }

    return params.join('&');
  }

})((window.rembeddit = window.rembeddit || {}), this);
