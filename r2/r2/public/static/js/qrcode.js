(function($) {
    $.fn.make_totp_qrcode = function (secret) {
        var form = $('#pref-otp'),
            newform = $('#pref-otp-qr'),
            placeholder = $('<div>'),
            uri = ('otpauth://totp/' + r.config.logged + '@' +
                   r.config.cur_domain + '?secret=' + secret)

        newform.find('#otp-secret-info').append(
            placeholder,
            $('<p class="secret">').text(secret)
        )

        placeholder.qrcode({
            width: 256,
            height: 256,
            text: uri
        })

        newform.show()
        form.hide()
    }
})(jQuery)
