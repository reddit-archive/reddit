r.gold = {
    _googleCheckoutAnalyticsLoaded: false,

    init: function () {
        $('div.content').on(
            'click',
            'a.give-gold, .gilded-comment-icon, .gold-payment .close-button',
            $.proxy(this, '_toggleCommentGoldForm')
        )

        $('.stripe-gold').click(function(){
            $("#stripe-payment").show()
        })

        $('.stripe-submit').on('click', this.makeStripeToken)

        $('section#about-gold-partners').on('click', 'input.code', function() {
            $(this).select()
        })
    },

    _toggleCommentGoldForm: function (e) {
        var $link = $(e.target),
            $thing = $link.thing(),
            commentId = $link.thing_id(),
            formId = 'gold_form_' + commentId,
            oldForm = $('#' + formId)

        if ($thing.hasClass('user-gilded') ||
            $thing.hasClass('deleted') ||
            $thing.find('.author:first').text() == r.config.logged) {
            return false
        }

        if (oldForm.length) {
            oldForm.toggle()
            return false
        }

        if (!this._googleCheckoutAnalyticsLoaded) {
            // we're just gonna hope this loads fast enough since there's no
            // way to know if it failed and we'd rather the form is still
            // usable if things don't go well with the analytics stuff.
            $.getScript('//checkout.google.com/files/digital/ga_post.js')
            this._googleCheckoutAnalyticsLoaded = true
        }

        var form = $('.gold-form.cloneable:first').clone(),
            authorName = $link.thing().find('.entry .author:first').text(),
            message = r.strings('gold_summary_comment_gift', {recipient: authorName}),
            passthroughs = form.find('.passthrough'),
            cbBaseUrl = form.find('[name="cbbaseurl"]').val()

        form.removeClass('cloneable')
            .attr('id', formId)
            .find('p:first-child em').text(authorName).end()
            .find('button').attr('disabled', '')
        passthroughs.val('')
        $link.new_thing_child(form)
        form.show()

        // show the throbber if this takes longer than 200ms
        var workingTimer = setTimeout(function () {
            form.addClass('working')
            form.find('button').addClass('disabled')
        }, 200)

        $.request('generate_payment_blob.json', {comment: commentId}, function (token) {
            clearTimeout(workingTimer)
            form.removeClass('working')
            passthroughs.val(token)
            form.find('.stripe-gold').on('click', function() { window.open('/gold/creditgild/' + token) })
            form.find('.coinbase-gold').on('click', function() { window.open(cbBaseUrl + "?c=" + token) })
            form.find('button').removeAttr('disabled').removeClass('disabled')
        })

        return false
    },

    gildComment: function (comment_id, new_title, specified_gilding_count) {
        var comment = $('.id-' + comment_id)

        if (!comment.length) {
            console.log("couldn't gild comment " + comment_id)
            return
        }

        var tagline = comment.children('.entry').find('p.tagline'),
            icon = tagline.find('.gilded-comment-icon')

        // when a comment is gilded interactively, we need to increment the
        // gilding count displayed by the UI. however, when gildings are
        // instantiated from a cached comment page via thingupdater, we can't
        // simply increment the gilding count because we do not know if the
        // cached comment page already includes the gilding in its count. To
        // resolve this ambiguity, thingupdater will provide the correct
        // gilding count as specified_gilding_count when calling this function.
        var gilding_count
        if (specified_gilding_count != null) {
            gilding_count = specified_gilding_count
        } else {
            gilding_count = icon.data('count') || 0
            gilding_count++
        }

        comment.addClass('gilded user-gilded')
        if (!icon.length) {
            icon = $('<span>')
                        .addClass('gilded-comment-icon')
            tagline.append(icon)
        }
        icon
            .attr('title', new_title)
            .data('count', gilding_count)
        if (gilding_count > 1) {
            icon.text('x' + gilding_count)
        }

        comment.children('.entry').find('.give-gold').parent().remove()
    },

    makeStripeToken: function () {
        var form = $('#stripe-payment'),
            publicKey = form.find('[name="stripePublicKey"]').val(),
            submit = form.find('.stripe-submit'),
            status = form.find('.status'),
            token = form.find('[name="stripeToken"]'),
            cardName = form.find('.card-name').val(),
            cardNumber = form.find('.card-number').val(),
            cardCvc = form.find('.card-cvc').val(),
            expiryMonth = form.find('.card-expiry-month').val(),
            expiryYear = form.find('.card-expiry-year').val(),
            cardAddress1 = form.find('.card-address_line1').val(),
            cardAddress2 = form.find('.card-address_line2').val(),
            cardCity = form.find('.card-address_city').val(),
            cardState = form.find('.card-address_state').val(),
            cardCountry = form.find('.card-address_country').val(),
            cardZip = form.find('.card-address_zip').val()

        var stripeResponseHandler = function(status, response) {
            if (response.error) {
                submit.removeAttr('disabled')
                status.html(response.error.message)
            } else {
                token.val(response.id)
                post_form(form, 'stripecharge/gold')
            }
        }

        Stripe.setPublishableKey(publicKey)

        if (!cardName) {
            status.text(r.strings('missing_credit_name'))
        } else if (!(Stripe.validateCardNumber(cardNumber))) {
            status.text(r.strings('bad_credit_number'))
        } else if (!Stripe.validateExpiry(expiryMonth, expiryYear)) {
            status.text(r.strings('bad_credit_expiry'))
        } else if (!Stripe.validateCVC(cardCvc)) {
            status.text(r.strings('bad_credit_cvc'))
        } else if (!cardAddress1) {
            status.text(r.strings('missing_credit_address'))
        } else if (!cardCity) {
            status.text(r.strings('missing_credit_city'))
        } else if (!cardState) {
            status.text(r.strings('missing_credit_state'))
        } else if (!cardCountry) {
            status.text(r.strings('missing_credit_country'))
        } else if (!cardZip) {
            status.text(r.strings('missing_credit_zip'))
        } else {

            status.text('')
            submit.attr('disabled', 'disabled')
            Stripe.createToken({
                    name: cardName,
                    number: cardNumber,
                    cvc: cardCvc,
                    exp_month: expiryMonth,
                    exp_year: expiryYear,
                    address_line1: cardAddress1,
                    address_line2: cardAddress2,
                    address_city: cardCity,
                    address_state: cardState,
                    address_country: cardCountry,
                    address_zip: cardZip
                }, stripeResponseHandler
            )
        }
        return false
    },
    
    claim_gold_partner_deal_code: function (elem, name) {
        $.ajax({
                  type: 'POST',
                  dataType: 'json',
                  url: '/api/claim_gold_partner_deal_code.json',
                  data:  {'deal': name, 'uh': r.config.modhash},
                  success: function(data) {
                      if ('error' in data) {
                          var $newelem = $('<span class="error">').text(data['explanation'])
                          $(elem).replaceWith($newelem)
                      } else {
                          var $newelem = $('<input type="text" class="code" readonly="readonly">').attr('value', data['code'])
                          $(elem).replaceWith($newelem)
                          $newelem.select()
                      }
                  }
                })
    }
};

(function($) {
    $.gild_comment = function (comment_id, new_title) {
        r.gold.gildComment(comment_id, new_title)
        $('#gold_form_' + comment_id).fadeOut(400)
    }
})(jQuery)
