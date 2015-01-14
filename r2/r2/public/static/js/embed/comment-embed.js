;(function(App, window, undefined) {

  var RE_ABS = /^https?:\/\//i;
  var RE_COMMENT = /\/?r\/[\w_]+\/comments\/(?:[\w_]+\/){2,}[\w_]+\/?/i;
  var PROTOCOL = location.protocol === 'file:' ? 'https:' : '';

  function isComment(anchor) {
    return RE_ABS.test(anchor.href) && RE_COMMENT.test(anchor.pathname);
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

    var query = 'embed=true' +
                '&context=' + context +
                '&depth=' + (++context) +
                '&showedits=' + data.embedLive +
                '&created=' + data.embedCreated +
                '&showmore=false';

    return PROTOCOL + (commentUrl.replace(/\/$/,'')) + '?' + query;
  }

  App.init = function(callback) {
    var embeds = document.querySelectorAll('.reddit-embed');

    [].forEach.call(embeds, function(embed) {
      var iframe = document.createElement('iframe');
      var anchors = embed.getElementsByTagName('a');
      var commentUrl = getCommentUrl(anchors, embed.dataset.embedMedia);

      if (!commentUrl) {
        return;
      }

      iframe.width = '100%';
      iframe.scrolling = 'no';
      iframe.frameBorder = 0;
      iframe.allowTransparency = true;
      iframe.style.display = 'none';
      iframe.src = getEmbedUrl(commentUrl, embed.dataset);

      App.receiveMessageOnce(iframe, 'loaded', function(e) {
        embed.parentNode.removeChild(embed);
        callback && callback(e);
      });

      var resizer = App.receiveMessage(iframe, 'resize', function(e) {
        if (!iframe.parentNode) {
          resizer.off();

          return;
        }

        iframe.height = (e.detail + 'px');
        iframe.style.display = 'block';
      });


      embed.parentNode.insertBefore(iframe, embed);
    });
  };

  App.init();

})((window.rembeddit = window.rembeddit || {}), this);
