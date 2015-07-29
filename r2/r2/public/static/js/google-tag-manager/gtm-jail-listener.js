;(function(global, r, undefined) {
  var jail = document.getElementById('jail');

  r.frames.proxy('gtm', jail.contentWindow);
})(this, this.r);
