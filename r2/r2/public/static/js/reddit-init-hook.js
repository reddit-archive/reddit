/*
  Init modules defined in reddit-init.js

  requires r.hooks (hooks.js)
 */
!function(r) {
  var hook = r.hooks.create('reddit-init');

  hook.register(function() {
    try {
        r.analytics.init();
        r.access.init();
    } catch (err) {
        r.sendError('Error during reddit-init.js init', err.toString());
    }
  })

  $(function() {
    hook.call();
  });
}(r);
