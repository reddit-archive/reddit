/*
  Init modules defined in reddit-init.js

  requires r.hooks (hooks.js)
 */
!function(r) {
  r.hooks.get('reddit-init').register(function() {
    try {
        r.analytics.init();
        r.events.init();
        r.access.init();
    } catch (err) {
        r.sendError('Error during reddit-init.js init', err.toString());
    }
  })

  $(function() {
    r.hooks.get('reddit-init').call();
  });
}(r);
