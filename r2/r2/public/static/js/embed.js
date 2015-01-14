;(function($, undefined) {
    var COMMENT_EMBED_SCRIPTS = r.config.comment_embed_scripts.map(function (src) {
      var attrs = r.config.comment_embed_scripts.length === 1 ? 'async' : '';

      return '<script ' + attrs + ' src="' + src + '"></script>';
    }).join('');
    var commentModalTemplate = _.template(
      '<div class="modal fade" tabindex="-1" role="dialog">' +
          '<div class="modal-dialog modal-dialog-lg">' +
              '<div class="modal-content">' +
                  '<div class="modal-header">' +
                      '<a href="javascript: void 0;" class="c-close c-hide-text" data-dismiss="modal">' +
                          _.escape(r._('close this window')) +
                      '</a>' +
                  '</div>' +
                  '<div class="modal-body">' +
                      '<h4  class="modal-title">' +
                        _.escape(r._('Embed preview:')) +
                      '</h4>' +
                      '<div id="embed-preview">' +
                          '<%= html %>' +
                      '</div>' +
                      '<% if (!root) { %>' +
                          '<div class="c-checkbox">' +
                              '<label class="remember">' +
                                  '<input type="checkbox" name="parent" <% if (parent) { %> checked <% } %>>' +
                                  _.escape(r._('Include parent comment.')) +
                              '</label>' +
                          '</div>' +
                      '<% } %>' +
                      '<div class="c-checkbox">' +
                          '<label>' +
                              '<input type="checkbox" name="live" <% if (!live) { %> checked <% } %> data-rerender="false">' +
                              _.escape(r._('Do not show comment if edited.')) +
                              '&nbsp;' +
                              '<a href="/help/embed#live-update">' +
                                _.escape(r._('Learn more')) +
                              '</a>' +
                          '</label>' +
                      '</div>' +
                  '</div>' +
                  '<div class="modal-footer">' +
                      '<div class="c-form-group">' +
                          '<label for="embed-code" class="modal-title">' +
                              _.escape(r._('Copy this code and paste it into your website:')) +
                          '</label>' +
                          '<textarea class="c-form-control" id="embed-code" rows="3" readonly>' +
                              '<%= html %>' +
                              '<%- scripts %>' +
                          '</textarea>' +
                      '</div>' +
                  '</div>' +
              '</div>' +
          '</div>' +
      '</div>'
    );
    var embedCodeTemplate = _.template(
      '<div class="reddit-embed" ' +
         ' data-embed-media="<%- media %>" ' +
         '<% if (parent) { %> data-embed-parent="true" <% } %>' +
         '<% if (live) { %> data-embed-live="true" <% } %>' +
         ' data-embed-created="<%- new Date().toISOString() %>">' +
        '<a href="<%- comment %>">Comment</a> from discussion <a href="<%- link %>"><%- title %></a>.' +
      '</div>'
    );

    function absolute(url) {
      if (/^https?:\/\//.test(url)) {
        return url;
      }

      return 'https://' + location.host + '/' + (url.replace(/^\//, ''));
    }

    function getEmbedOptions(data) {
      var defaults = {
        live: true,
        parent: false,
        media: location.host,
      };

      data = _.defaults({}, data, defaults);
      data.comment = absolute(data.comment);
      data.link = absolute(data.link);

      return _.extend({
        html: embedCodeTemplate(data),
        scripts: COMMENT_EMBED_SCRIPTS,
      }, data);
    }

    $('body').on('click', '.embed-comment', function(e) {
      var $el = $(e.target);
      var data = $el.data();
      var $dialog = $(commentModalTemplate(getEmbedOptions(data)));
      var $textarea = $dialog.find('textarea');
      var $preview = $dialog.find('#embed-preview');

      $dialog.on('change', '[type="checkbox"]', function(e) {
        var option = e.target.name;
        var $option = $(e.target);
        var prev = $el.data(option);

        if (prev === undefined) {
          prev = embedOptions[option]
        }

        $el.data(e.target.name, !prev);

        var data = $el.data();
        var options = getEmbedOptions(data);
        var html = options.html;
        var height = $preview.height();

        $textarea.val(html + options.scripts);

        if ($option.data('rerender') !== false) {
          $preview.height(height).html(html);

          window.rembeddit.init(function () {
            $preview.css({height: 'auto'});
          });
        }
      });

      $textarea.on('focus', function() {
        $(this).select();
      });

      $dialog.on('hidden.bs.modal', function() {
        $dialog.remove();
      });

      $dialog.on('shown.bs.modal', function() {
        window.rembeddit.init();
      });

      $dialog.modal();

    });

})(window.jQuery);
