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

  function createPayloadFactory(location) {
    return function payloadFactory(type, action, payload) {
      var now = new Date();
      var data = {
        type: type,
        action: action,
        timestamp: now.getTime(),
        utcOffset: now.getTimezoneOffset() / -60,
        userAgent: navigator.userAgent,
        logged: !!config.logged,
        created: config.created,
        id: thing.id,
        subredditId: thing.sr_id,
        subredditName: thing.sr_name,
        showedits: config.showedits,
        edited: thing.edited,
        deleted: thing.deleted,
        hostUrl: location.href,
      };

      for (var name in payload) {
        data[name] = payload[name];
      }

      return {embed: data};
    };
  }

  setInterval(checkHeight, 100);



  App.receiveMessage('pong', function(e) {
    var type = e.detail.type;
    var options = e.detail.options;
    var location = e.detail.location;
    var createPayload = createPayloadFactory(location);

    if (options.track === false) {
      return;
    }

    var tracker = new Metron.Tracker({
      domain: config.stats_domain,
    });

    tracker.send(createPayload(type, 'view'));

    function trackLink(e) {
      e.preventDefault();

      var el = this;
      var payload = {
        redirectUrl: el.href,
        redirectType: el.getAttribute('data-redirect-type'),
        redirectDest: el.host,
        redirectId: el.getAttribute('data-redirect-thing'),
      };

      tracker.send(createPayload(type, 'click', payload), function() {
        window.top.location.href = el.href;
      });
    }

    var trackLinks = document.getElementsByTagName('a');

    for (var i = 0, l = trackLinks.length; i < l; i++) {
      var link = trackLinks[i];

      if (link.getAttribute('data-redirect-type')) {
        trackLinks[i].addEventListener('click', trackLink, false);
      }
    }

  });

  App.postMessage(window.parent, 'ping', {
    config: config,
  });

})((window.rembeddit = window.rembeddit || {}), this);
