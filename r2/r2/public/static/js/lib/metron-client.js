(function e(t,n,r){function s(o,u){if(!n[o]){if(!t[o]){var a=typeof require=="function"&&require;if(!u&&a)return a(o,!0);if(i)return i(o,!0);var f=new Error("Cannot find module '"+o+"'");throw f.code="MODULE_NOT_FOUND",f}var l=n[o]={exports:{}};t[o][0].call(l.exports,function(e){var n=t[o][1][e];return s(n?n:e)},l,l.exports,e,t,n,r)}return n[o].exports}var i=typeof require=="function"&&require;for(var o=0;o<r.length;o++)s(r[o]);return s})({1:[function(require,module,exports){
(function (global){
'use strict';

if (typeof window === 'undefined') { // commonjs
  // bypass browserify w/variable
  var ajax = './request-commonjs';

  module.exports = require(ajax);
} else if (global.$ && $.ajax) { // browser with jquery
  module.exports = $.ajax;
} else {
  // Fallback to a minimal ajax implementation.
  module.exports = function ajaxShim(url, options) {
    options = options || {};

    if (arguments.length === 1) {
      options = url || {};
      url = options.url;
    }

    options.type = options.type || 'GET';
    options.contentType = options.contentType ||
      'application/x-www-form-urlencoded; charset=UTF-8';

    var httpRequest;

    if (window.XMLHttpRequest) {
      httpRequest = new XMLHttpRequest();
    } else if (window.ActiveXObject) {
      try {
        httpRequest = new ActiveXObject('Msxml2.XMLHTTP');
      }
      catch (e) {
        try {
          httpRequest = new ActiveXObject('Microsoft.XMLHTTP');
        }
        /* jshint -W002 */
        catch (e) {}
      }
    }

    if (!httpRequest) {
      return;
    }

    httpRequest.onreadystatechange = function() {
      if (httpRequest.readyState === 4 && options.complete) {
        options.complete(httpRequest, httpRequest.statusText);
      }
    };

    httpRequest.open(options.type, url);

    for (var key in options.headers) {
      httpRequest.setRequestHeader(key, options.headers[key]);
    }

    httpRequest.setRequestHeader('Content-Type', options.contentType);

    try {
      httpRequest.send(options.data);
    } catch (e) {}

    return httpRequest;

  };

}

}).call(this,typeof global !== "undefined" ? global : typeof self !== "undefined" ? self : typeof window !== "undefined" ? window : {})

},{}],2:[function(require,module,exports){
(function (global){
'use strict';

var ajax = require('./ajax');

var Tracker = module.exports = function(options) {
  this.domain = options.domain;
};

Tracker.prototype.send = function(payload, callback, options) {
  if (!payload) {
    return;
  }

  callback = callback || function() {};
  options = options || {};

  var method = options.method || 'POST';
  var url = this.domain;
  var contentType;
  var data;

  if (method === 'GET') {
    if (typeof payload !== 'string') {
      // Serialize payload as query parameters.
      if (!global.$.param) {
        throw new Error('Using `GET` requires `$.param`');
      }

      payload = $.param(payload);
    }

    url += ('?' + payload);
  } else {
    contentType = 'application/json; charset=utf-8';
    data = JSON.stringify(payload);
  }

  var xhr = ajax({
    complete: callback,
    contentType: contentType,
    data: data,
    type: method,
    url: url,
  });

  return xhr;
};

// Export to `window`, for browser wo/browserify.
if (typeof window !== 'undefined') {
  var Metron = (window.Metron = window.Metron || {});

  Metron.Tracker = Tracker;
}

}).call(this,typeof global !== "undefined" ? global : typeof self !== "undefined" ? self : typeof window !== "undefined" ? window : {})

},{"./ajax":1}]},{},[2])
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJzb3VyY2VzIjpbIm5vZGVfbW9kdWxlcy9icm93c2VyaWZ5L25vZGVfbW9kdWxlcy9icm93c2VyLXBhY2svX3ByZWx1ZGUuanMiLCJzcmMvYWpheC5qcyIsInNyYy90cmFja2VyLmpzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiJBQUFBOztBQ0FBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7Ozs7O0FDbkVBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBO0FBQ0E7QUFDQTtBQUNBIiwiZmlsZSI6ImdlbmVyYXRlZC5qcyIsInNvdXJjZVJvb3QiOiIiLCJzb3VyY2VzQ29udGVudCI6WyIoZnVuY3Rpb24gZSh0LG4scil7ZnVuY3Rpb24gcyhvLHUpe2lmKCFuW29dKXtpZighdFtvXSl7dmFyIGE9dHlwZW9mIHJlcXVpcmU9PVwiZnVuY3Rpb25cIiYmcmVxdWlyZTtpZighdSYmYSlyZXR1cm4gYShvLCEwKTtpZihpKXJldHVybiBpKG8sITApO3ZhciBmPW5ldyBFcnJvcihcIkNhbm5vdCBmaW5kIG1vZHVsZSAnXCIrbytcIidcIik7dGhyb3cgZi5jb2RlPVwiTU9EVUxFX05PVF9GT1VORFwiLGZ9dmFyIGw9bltvXT17ZXhwb3J0czp7fX07dFtvXVswXS5jYWxsKGwuZXhwb3J0cyxmdW5jdGlvbihlKXt2YXIgbj10W29dWzFdW2VdO3JldHVybiBzKG4/bjplKX0sbCxsLmV4cG9ydHMsZSx0LG4scil9cmV0dXJuIG5bb10uZXhwb3J0c312YXIgaT10eXBlb2YgcmVxdWlyZT09XCJmdW5jdGlvblwiJiZyZXF1aXJlO2Zvcih2YXIgbz0wO288ci5sZW5ndGg7bysrKXMocltvXSk7cmV0dXJuIHN9KSIsIid1c2Ugc3RyaWN0JztcblxuaWYgKHR5cGVvZiB3aW5kb3cgPT09ICd1bmRlZmluZWQnKSB7IC8vIGNvbW1vbmpzXG4gIC8vIGJ5cGFzcyBicm93c2VyaWZ5IHcvdmFyaWFibGVcbiAgdmFyIGFqYXggPSAnLi9yZXF1ZXN0LWNvbW1vbmpzJztcblxuICBtb2R1bGUuZXhwb3J0cyA9IHJlcXVpcmUoYWpheCk7XG59IGVsc2UgaWYgKGdsb2JhbC4kICYmICQuYWpheCkgeyAvLyBicm93c2VyIHdpdGgganF1ZXJ5XG4gIG1vZHVsZS5leHBvcnRzID0gJC5hamF4O1xufSBlbHNlIHtcbiAgLy8gRmFsbGJhY2sgdG8gYSBtaW5pbWFsIGFqYXggaW1wbGVtZW50YXRpb24uXG4gIG1vZHVsZS5leHBvcnRzID0gZnVuY3Rpb24gYWpheFNoaW0odXJsLCBvcHRpb25zKSB7XG4gICAgb3B0aW9ucyA9IG9wdGlvbnMgfHwge307XG5cbiAgICBpZiAoYXJndW1lbnRzLmxlbmd0aCA9PT0gMSkge1xuICAgICAgb3B0aW9ucyA9IHVybCB8fCB7fTtcbiAgICAgIHVybCA9IG9wdGlvbnMudXJsO1xuICAgIH1cblxuICAgIG9wdGlvbnMudHlwZSA9IG9wdGlvbnMudHlwZSB8fCAnR0VUJztcbiAgICBvcHRpb25zLmNvbnRlbnRUeXBlID0gb3B0aW9ucy5jb250ZW50VHlwZSB8fFxuICAgICAgJ2FwcGxpY2F0aW9uL3gtd3d3LWZvcm0tdXJsZW5jb2RlZDsgY2hhcnNldD1VVEYtOCc7XG5cbiAgICB2YXIgaHR0cFJlcXVlc3Q7XG5cbiAgICBpZiAod2luZG93LlhNTEh0dHBSZXF1ZXN0KSB7XG4gICAgICBodHRwUmVxdWVzdCA9IG5ldyBYTUxIdHRwUmVxdWVzdCgpO1xuICAgIH0gZWxzZSBpZiAod2luZG93LkFjdGl2ZVhPYmplY3QpIHtcbiAgICAgIHRyeSB7XG4gICAgICAgIGh0dHBSZXF1ZXN0ID0gbmV3IEFjdGl2ZVhPYmplY3QoJ01zeG1sMi5YTUxIVFRQJyk7XG4gICAgICB9XG4gICAgICBjYXRjaCAoZSkge1xuICAgICAgICB0cnkge1xuICAgICAgICAgIGh0dHBSZXF1ZXN0ID0gbmV3IEFjdGl2ZVhPYmplY3QoJ01pY3Jvc29mdC5YTUxIVFRQJyk7XG4gICAgICAgIH1cbiAgICAgICAgLyoganNoaW50IC1XMDAyICovXG4gICAgICAgIGNhdGNoIChlKSB7fVxuICAgICAgfVxuICAgIH1cblxuICAgIGlmICghaHR0cFJlcXVlc3QpIHtcbiAgICAgIHJldHVybjtcbiAgICB9XG5cbiAgICBodHRwUmVxdWVzdC5vbnJlYWR5c3RhdGVjaGFuZ2UgPSBmdW5jdGlvbigpIHtcbiAgICAgIGlmIChodHRwUmVxdWVzdC5yZWFkeVN0YXRlID09PSA0ICYmIG9wdGlvbnMuY29tcGxldGUpIHtcbiAgICAgICAgb3B0aW9ucy5jb21wbGV0ZShodHRwUmVxdWVzdCwgaHR0cFJlcXVlc3Quc3RhdHVzVGV4dCk7XG4gICAgICB9XG4gICAgfTtcblxuICAgIGh0dHBSZXF1ZXN0Lm9wZW4ob3B0aW9ucy50eXBlLCB1cmwpO1xuXG4gICAgZm9yICh2YXIga2V5IGluIG9wdGlvbnMuaGVhZGVycykge1xuICAgICAgaHR0cFJlcXVlc3Quc2V0UmVxdWVzdEhlYWRlcihrZXksIG9wdGlvbnMuaGVhZGVyc1trZXldKTtcbiAgICB9XG5cbiAgICBodHRwUmVxdWVzdC5zZXRSZXF1ZXN0SGVhZGVyKCdDb250ZW50LVR5cGUnLCBvcHRpb25zLmNvbnRlbnRUeXBlKTtcblxuICAgIHRyeSB7XG4gICAgICBodHRwUmVxdWVzdC5zZW5kKG9wdGlvbnMuZGF0YSk7XG4gICAgfSBjYXRjaCAoZSkge31cblxuICAgIHJldHVybiBodHRwUmVxdWVzdDtcblxuICB9O1xuXG59XG4iLCIndXNlIHN0cmljdCc7XG5cbnZhciBhamF4ID0gcmVxdWlyZSgnLi9hamF4Jyk7XG5cbnZhciBUcmFja2VyID0gbW9kdWxlLmV4cG9ydHMgPSBmdW5jdGlvbihvcHRpb25zKSB7XG4gIHRoaXMuZG9tYWluID0gb3B0aW9ucy5kb21haW47XG59O1xuXG5UcmFja2VyLnByb3RvdHlwZS5zZW5kID0gZnVuY3Rpb24ocGF5bG9hZCwgY2FsbGJhY2ssIG9wdGlvbnMpIHtcbiAgaWYgKCFwYXlsb2FkKSB7XG4gICAgcmV0dXJuO1xuICB9XG5cbiAgY2FsbGJhY2sgPSBjYWxsYmFjayB8fCBmdW5jdGlvbigpIHt9O1xuICBvcHRpb25zID0gb3B0aW9ucyB8fCB7fTtcblxuICB2YXIgbWV0aG9kID0gb3B0aW9ucy5tZXRob2QgfHwgJ1BPU1QnO1xuICB2YXIgdXJsID0gdGhpcy5kb21haW47XG4gIHZhciBjb250ZW50VHlwZTtcbiAgdmFyIGRhdGE7XG5cbiAgaWYgKG1ldGhvZCA9PT0gJ0dFVCcpIHtcbiAgICBpZiAodHlwZW9mIHBheWxvYWQgIT09ICdzdHJpbmcnKSB7XG4gICAgICAvLyBTZXJpYWxpemUgcGF5bG9hZCBhcyBxdWVyeSBwYXJhbWV0ZXJzLlxuICAgICAgaWYgKCFnbG9iYWwuJC5wYXJhbSkge1xuICAgICAgICB0aHJvdyBuZXcgRXJyb3IoJ1VzaW5nIGBHRVRgIHJlcXVpcmVzIGAkLnBhcmFtYCcpO1xuICAgICAgfVxuXG4gICAgICBwYXlsb2FkID0gJC5wYXJhbShwYXlsb2FkKTtcbiAgICB9XG5cbiAgICB1cmwgKz0gKCc/JyArIHBheWxvYWQpO1xuICB9IGVsc2Uge1xuICAgIGNvbnRlbnRUeXBlID0gJ2FwcGxpY2F0aW9uL2pzb247IGNoYXJzZXQ9dXRmLTgnO1xuICAgIGRhdGEgPSBKU09OLnN0cmluZ2lmeShwYXlsb2FkKTtcbiAgfVxuXG4gIHZhciB4aHIgPSBhamF4KHtcbiAgICBjb21wbGV0ZTogY2FsbGJhY2ssXG4gICAgY29udGVudFR5cGU6IGNvbnRlbnRUeXBlLFxuICAgIGRhdGE6IGRhdGEsXG4gICAgdHlwZTogbWV0aG9kLFxuICAgIHVybDogdXJsLFxuICB9KTtcblxuICByZXR1cm4geGhyO1xufTtcblxuLy8gRXhwb3J0IHRvIGB3aW5kb3dgLCBmb3IgYnJvd3NlciB3by9icm93c2VyaWZ5LlxuaWYgKHR5cGVvZiB3aW5kb3cgIT09ICd1bmRlZmluZWQnKSB7XG4gIHZhciBNZXRyb24gPSAod2luZG93Lk1ldHJvbiA9IHdpbmRvdy5NZXRyb24gfHwge30pO1xuXG4gIE1ldHJvbi5UcmFja2VyID0gVHJhY2tlcjtcbn1cbiJdfQ==
