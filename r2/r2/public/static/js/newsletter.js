r.newsletter = {
  post: function(form) {
    var email = $('input[name="email"]', form.$el).val();
    var apiTarget = form.$el.attr('action');

    var params = form.serialize();
    params.push({name:'api_type', value:'json'});

    return r.ajax({
      url: apiTarget,
      type: 'POST',
      dataType: 'json',
      data: params,
      xhrFields: {
        withCredentials: true
      }
    });
  }
};

r.newsletter.ui = {
  init: function() {
    var newsletterBarSeen = !!store.get('newsletterbar.seen');

    if (newsletterBarSeen || $('.newsletterbar').length === 0) {
      return;
    }

    $('.newsletterbar').show();

    $('.newsletter-signup').each(function(i, el) {
      new r.newsletter.ui.NewsletterForm(el)
    })

    $('.newsletter-close').on('click', function() {
      $('.newsletterbar').addClass('c-hidden');
    });

    store.set('newsletterbar.seen', true);
  },
};

r.newsletter.ui.NewsletterForm = function() {
  r.ui.Form.apply(this, arguments)
};

r.newsletter.ui.NewsletterForm.prototype = $.extend(new r.ui.Form(), {
  showStatus: function() {
    this.$el.find('.error').css('opacity', 1)
    r.ui.Form.prototype.showStatus.apply(this, arguments)
  },
  
  _submit: function() {
    r.analytics.fireGAEvent('newsletter-form', 'submit');
    return r.newsletter.post(this);
  },

  _showSuccess: function() {
      var parentEl = this.$el.parents('.newsletterbar');
      parentEl.find('.result-message').text(r._('you\'ll get your first newsletter soon'));
      parentEl.addClass('success');
      parentEl.find('header').fadeTo(250, 1);
  },

  _handleResult: function(result) {
    if (result.json.errors.length) {
      r.ui.Form.prototype._handleResult.call(this, result);
    }

    var parentEl = this.$el.parents('.newsletterbar');
    var calloutImg = parentEl.find('.subscribe-callout img');
    var thanksImg = $('<img />').attr('src', calloutImg.data('thanks-src'))
                                .attr('alt', r._('thanks for subscribing'));

    parentEl.find('header, form').fadeTo(250, 0, function() {
      calloutImg.hide().after(thanksImg);
      if (thanksImg.get(0).complete) {
        this._showSuccess();
      } else {
        thanksImg.one("load", this._showSuccess);
      }
    }.bind(this));
  }
})
