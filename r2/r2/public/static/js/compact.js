/*This hides the url bar on mobile*/
(function($) {
    /*
    Creates an element on the body that works to create a modal box
    The callback function runs when the cover is clicked
    Use it, for example, to hide your modal box.

    It is kind of tricky to use on mobile platforms, subject to many odd bugs, likely caused by the way mobile platforms handle z-index
    */
    function tool_cover(callback) {
        var toolcover = $("#toolcover");
        if (toolcover.length == 0) {
            $("body").prepend("<div class='cover' id='toolcover'></div>");
            toolcover = $("#toolcover");
        }
        toolcover.css("height", $(document).height())
                .show().one("click", function() {
                    $(this).hide();
                    if (callback) callback();
                    return false;
                });
    }

    ;
    $.fn.show_toolbar = function() {
        var tb = this;
        $(this).show();
    };
    $.unsafe_orig = $.unsafe;
    $.unsafe = function(text) {
        /* inverts websafe filtering of reddit app. */
        text = $.unsafe_orig(text);
        if (typeof(text) == "string") {
            /* space compress the result */
            text = text.replace(/[\s]+/g, " ")
                    .replace(/> +/g, ">")
                    .replace(/ +</g, "<");
        }
        return (text || "");
    }
})(jQuery);

$(function() {
    if ($(window).scrollTop() == 0) {
        $(window).scrollTop(1);
    }
    ;
    /* Top menu dropdown*/
    $('#topmenu_toggle').click(function() {
        $(this).toggleClass("active");
        $('#top_menu').toggle();
        return false;
    });
    //Self text expando
    $('.expando-button').live('click', function() {
        $(this).toggleClass("expanded");
        $(this).thing().find(".expando").toggle();
        return false;
    });
    //Help expando
    $('.help-toggle').live('click', function() {
        $(this).toggleClass("expanded");
        $(this).parent().parent().siblings(".markhelp-parent").toggle();
        return false;
    });

    //Options expando
    $('.options_link').live('click', function(evt) {

        if (! $(this).siblings(".options_expando").hasClass('expanded')) {
            $('.options_expando.expanded').each(function() { //Collapse any other open ones
                $(this).removeClass('expanded');
            });
            $('.options_link.active').each(function() {
               $(this).removeClass('active');
            });
            $(this).siblings(".options_expando").addClass('expanded'); //Expand this one
            $(this).addClass('active');
        } else {
             $(this).siblings(".options_expando").removeClass('expanded'); //Just collapse this one
             $(this).removeClass('active');
        }
        return false;
    });
    //Save button state transition
    $(".save-button").live("click", function() {
        $(this).toggle();
        $(this).siblings(".unsave-button").toggle();
    });
    $(".unsave-button").live("click", function() {
        $(this).toggle();
        $(this).siblings(".save-button").toggle();
    });
    //Hide options when we collapse
    $('.options_expando .collapse-button').live("click", function() {
        $(this).parent().removeClass('expanded');
        $(this).parent().parent().parent().addClass("collapsed");
        $(this).parent().siblings('.options_link').removeClass("active");
    });
    //Collapse when we click reply, or edit
    $('.reply-button, .edit-button').live("click", function() {
        $(this).parent().siblings('.options-link').click();
    });
    /* the iphone doesn't play nice with live() unless there is already a registered click function.  That's sad */
    $(".thing").click(function() {
    });

    $(".link").live("click", function(evt) {
        if (evt && evt.target && $(evt.target).hasClass("thing")) {
            $(this).find(".options_link").click();
            return false;
        }
    });
    //Comment options
    $(".comment.collapsed").live("click", function(e) {
        $(this).removeClass("collapsed");
    });
    $(".message.unread").live("click", function(e) {
        var thing = $(this)
        read_thing(thing);
        return false;
    });
    /*Finally*/
    $('a[href=#]').live('click', function() {
        return false;
    });
});

$(function() {
    var eut = edit_usertext;
    edit_user_text = function(what) {
        $(what).parent().parent().toggleClass('hidden');
        return eut(what);
    };

});

function showcover() {
    $.request("new_captcha");
    $(".login-popup:first").fadeIn()
            .find(".popup").css("top", $(window).scrollTop() + 75).end()
            .find(".cover").css("height", $(document).height()).end()
    return false;
}

function hidecover(where) {
    $(where).parents(".cover-overlay").fadeOut();
    return false;
}

function show_edit_usertext(form) {
    var edit = form.find(".usertext-edit");
    var body = form.find(".usertext-body");
    var textarea = edit.find('div > textarea');
    //we need to show the textbox first so it has dimensions
    body.hide();
    edit.show();

    form
            .find(".cancel, .save").show().end()
            .find(".help-toggle").show().end();

    textarea.focus();
}

function fetch_more() {
    $("#siteTable").after($("<div class='loading'><img src='/static/reddit_loading.png'/></div>"));


    var o = document.location;
    var path = o.pathname.split(".");
    if (path[path.length - 1].indexOf('/') == -1) {
        path = path.slice(0, -1).join('.');
    } else {
        path = o.pathname;
    }
    var apath = o.protocol + "//" + o.host + path + ".json-compact" + o.search;
    var last = $("#siteTable").find(".thing:last");
    apath += ((document.location.search) ? "&" : "?") +
            "after=" + last.thing_id();

    if (last.find(".rank").length)
        "&count=" + parseInt(last.find(".rank").html())

    $.getJSON(apath, function(res) {
        $.insert_things(res.data, true);
        $(".thing").click(function() {
        });
        /* remove the loading image */
        $("#siteTable").next(".loading").remove();
        if (res && res.data.length == 0) {
            $(window).unbind("scroll");
        }
    });
}
