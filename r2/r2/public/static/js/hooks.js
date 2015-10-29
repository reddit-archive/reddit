/*
  Provides a very simple hook system for one-off event hooks.

  var initHook = r.hooks.create('init');
 */

!function(r) {
  var hooks = {};

  function Hook(name) {
    this.name = name;
    this.called = false;
    this._callbacks = [];
  }

  Hook.prototype.register = function(callback) {
    if (this.called) {
      callback.call(window);
    } else {
      this._callbacks.push(callback);
    }
  };

  Hook.prototype.call = function() {
    if (this.called) {
      throw 'Hook ' + this.name + ' already called.';
    } else {
      var callbacks = this._callbacks;
      this.called = true;
      this._callbacks = null;

      for (var i = 0; i < callbacks.length; i++) {
        callbacks[i].call(window);
      }
    }
  };

  r.hooks = {
    create: function(name) {
      if (name in hooks) {
        throw 'Hook "' + name + '" already exists.';
      } else {
        var hook = new Hook(name);
        hooks[name] = hook;
        return hook;
      }
    },

    get: function(name) {
      if (name in hooks) {
        return hooks[name];
      } else {
        throw 'Hook "' + name + '" doesn\'t exist.' 
      }
    },

    call: function(name) {
      return r.hooks.get(name).call();
    },
  };
}((window.r = window.r || {}));
