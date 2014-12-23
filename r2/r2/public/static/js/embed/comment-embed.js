;(function(App, window, undefined) {

  var RE_COMMENT = /(?:https?\:)?(\/\/(?:www\.)?reddit\.(?:com|local)(?:\:\d+)?\/r\/[\w_]+\/comments\/(?:[\w_]+\/){2,}[\w_]+\/?)/i;
  var PROTOCOL = location.protocol === 'file:' ? 'https:' : '';

  function isComment(url) {
    return typeof url === 'string' && RE_COMMENT.test(url);
  }

  function getCommentPathname(anchor) {
    return isComment(anchor) && anchor.pathname.replace(/^\//, '');
  }

  function getCommentUrl(links, host) {
    var pathname;

    for (var i = 0, l = links.length; i < l; i++) {
      if ((pathname = getCommentPathname(links[i]))) {
        break;
      }
    }

    return '//' + host + '/' + pathname;
  }

  function getEmbedUrl(commentUrl, data) {
    var context = 0;

    if (data.embedParent === 'true') {
      context++;
    }

    var query = 'context=' + context +
                '&depth=' + (++context) +
                '&showedits=' + data.embedLive +
                '&created=' + data.embedCreated +
                '&showmore=false';

    return PROTOCOL + (commentUrl.replace(/\/$/,'')) + '.iframe?' + query;
  }

  App.init = function(callback) {
    var embeds = document.querySelectorAll('.reddit-embed');

    [].forEach.call(embeds, function(embed) {
      var iframe = document.createElement('iframe');
      var anchors = embed.getElementsByTagName('a');
      var commentUrl = getCommentUrl(anchors, embed.dataset.embedMedia);
      var loaded = false;

      if (!commentUrl) {
        return;
      }

      iframe.width = '100%';
      iframe.scrolling = 'no';
      iframe.frameBorder = 0;
      iframe.allowTransparency = true;
      iframe.style.display = 'none';
      iframe.src = getEmbedUrl(commentUrl, embed.dataset);

      App.receiveMessage('resize', function(e) {
        iframe.height = (e.detail + 'px');
        iframe.style.display = 'block';

        if (!loaded) {
          loaded = true;

          callback && callback(e);
        }
      });

      embed.parentNode.replaceChild(iframe, embed);
    });
  };

  App.init();

})((window.rembeddit = window.rembeddit || {}), this);
