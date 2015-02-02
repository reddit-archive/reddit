;(function(App, window, undefined) {
  var config = window.REDDIT_EMBED_CONFIG;
  var thing = config.thing;

  App.addPostMessageOrigin(window.location.host);

  function checkHeight() {
    var height = document.body.clientHeight;

    if (App.height !== height) {
      App.height = height;

      App.postMessage(window.parent, 'resize', height, '*');
    }
  }

  setInterval(checkHeight, 100);

  App.postMessage(window.parent, 'ping', {
    config: config,
  });

})((window.rembeddit = window.rembeddit || {}), this);
