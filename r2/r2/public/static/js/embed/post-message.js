;(function(App, window, undefined) {
  var WILDCARD = '*';
  var ALLOW_WILDCARD = '.*';
  var RE_WILDCARD = /\*/;

  var allowedOrigins = [ALLOW_WILDCARD];
  var re_postMessageAllowedOrigin = compileOriginRegExp(allowedOrigins);

  function receiveMessage(e) {
    if (!re_postMessageAllowedOrigin.test(e.origin) && e.origin !== 'null') {
      return;
    }

    try {
      var message = JSON.parse(e.data);
      var customEvent = new CustomEvent(message.type, {detail: message.data});

      customEvent.source = e.source;

      window.dispatchEvent(customEvent);
    } catch (x) {}
  }

  function compileOriginRegExp(origins) {
    return new RegExp('^http(s)?:\\/\\/' + origins.join('|'), 'i');
  }

  function isWildcard(origin) {
    return RE_WILDCARD.test(origin);
  }

  App.utils.extend(App, {

    postMessage: function(target, type, data, options) {
      type += '.postMessage';

      var defaults = {
        targetOrigin: WILDCARD,
        delay: 100
      };

      options = App.utils.extend({}, defaults, options);

      target.postMessage(JSON.stringify({type: type, data: data}), options.targetOrigin);
    },

    receiveMessage: function(source, type, callback, context) {
      if (typeof source === 'string') {
        context = callback;
        callback = type;
        type = source;
        source = null;
      }

      type += '.postMessage';
      context = context || this;

      var scoped = function(e) {
        if (source &&
            source !== e.source &&
            source.contentWindow !== e.source) {
          return;
        }

        callback.apply(context, arguments);
      }

      window.addEventListener(type, scoped);

      return {
        off: function () { window.removeEventListener(type, scoped); }
      };
    },

    receiveMessageOnce: function(source, type, callback, context) {
      var listener = App.receiveMessage(source, type, function() {
        callback && callback.apply(this, arguments);

        listener.off();
      }, context);

      return listener;
    },

    addPostMessageOrigin: function(origin) {
      if (isWildcard(origin)) {
        allowedOrigins = [ALLOW_WILDCARD];
      } else if (allowedOrigins.indexOf(origin) === -1) {
        App.removePostMessageOrigin(ALLOW_WILDCARD);

        allowedOrigins.push(origin);

        re_postMessageAllowedOrigin = compileOriginRegExp(allowedOrigins);
      }
    },

    removePostMessageOrigin: function(origin) {
      var index = allowedOrigins.indexOf(origin);

      if (index !== -1) {
        allowedOrigins.splice(index, 1);

        re_postMessageAllowedOrigin = compileOriginRegExp(allowedOrigins);
      }
    }

  });

  window.addEventListener('message', receiveMessage, false);

})((window.rembeddit = window.rembeddit || {}), this);
