;(function(global, r, undefined) {
  var jail = document.getElementById('jail');

  r.frames.proxy('gtm', [jail.contentWindow, window.parent]);
})(this, this.r);
