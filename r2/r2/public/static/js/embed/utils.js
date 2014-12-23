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

})((window.rembeddit = window.rembeddit || {}), this);
