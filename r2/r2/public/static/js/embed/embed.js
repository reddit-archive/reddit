;(function(App, window, undefined) {

  App.addPostMessageOrigin(window.location.host);

  function checkHeight() {
    var height = document.body.clientHeight;

    if (App.height !== height) {
      App.height = height;

      App.postMessage(window.parent, 'resize', height, '*');
    }
  }

  setInterval(checkHeight, 100);

  App.postMessage(window.parent, 'loaded');

})((window.rembeddit = window.rembeddit || {}), this);
