;(function(App, window, undefined) {
  var hasOwnProperty = Object.prototype.hasOwnProperty;

  App.utils = App.utils || {};

  App.utils.extend = function(obj) {
    if (typeof obj !== 'object') {
      return obj;
    }

    var source, prop;

    for (var i = 1, length = arguments.length; i < length; i++) {
      source = arguments[i];
      for (prop in source) {
      if (hasOwnProperty.call(source, prop)) {
        obj[prop] = source[prop];
      }
      }
    }

    return obj;
  };

  App.utils.find = function(array, test) {
    var found;

    for (var i = 0; l = array.length, i < l; i++) {
      var item = array[i];

      if (test(item, i, array)) {
        found = item;
        break;
      }
    }
    
    return found;
  };

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

})((window.rembeddit = window.rembeddit || {}), this);
