/*This hides the url bar on mobile*/
(function($) {
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
    };
    $.fn.show_toolbar = function() {
        var tb = this;
        tool_cover(function() { $(tb).hide(); });
        $(this).show();
    };
    $.fn.hide_toolbar = function() {
        $("#toolcover").click();
    };
    $.unsafe_orig = $.unsafe;
    $.unsafe = function(text) {
        /* inverts websafe filtering of reddit app. */
        text = $.unsafe_orig(text);
        if(typeof(text) == "string") {
            /* space compress the result */
            text = text.replace(/[\s]+/g, " ")
                .replace(/> +/g, ">")
                .replace(/ +</g, "<");
        }
        return (text || "");
    }
})(jQuery);

$(function() {
    if($(window).scrollTop() == 0) {
        $(window).scrollTop(1);
    };
    /* Top menu dropdown*/
    $('#topmenu_toggle').click ( function() {
        $(this).toggleClass("active");
        $('#top_menu').toggle();
        return false;
    });
    $('.expando-button').live('click', function() {
        $(this).toggleClass("expanded");
        $(this).thing().find(".expando").toggle();
        return false;
    });
    $('.help-toggle').live('click', function() {
        $(this).toggleClass("expanded");
        $(this).parent().siblings(".markhelp-parent").toggle();
        return false;
    });
   /*Options dropdown for each comment */
   $('.thing_options_link').live('click', function() {
       $(this).toggleClass("active");
       $(this).siblings(".thing_options_popup_container")
           .toggleClass("hidden");
       $(this).siblings(".thing_options_popup_container")
           .find(".thing_suboption_popup_container").addClass("hidden");
       return false;
   });
   /*Sub-menus. This can be replicated infinitely.*/
   $('.thing_suboption_link').live('click', function() {
       $(this).prev(".thing_suboption_popup_container").toggleClass("hidden");
       return false;
   });
   /*Collapse menu on click of .option_close*/
   $('.thing_option_close').live('click', function() {
       $(this).parents(".thing_options_popup_container,.thing_suboption_popup_container").addClass("hidden");
       return false;
   });
   /*Added expansion to text-area (like facebook/Buzz/Twitter)*/
   /*$('.usertext textarea').autoResize({
           animate: false,
               extraSpace : 20
               });*/

   $(".options_triangle .button").live("click", function(evt) {
       $(this).parents(".options_triangle").hide_toolbar();
   });
   $('.triangle_link').live('click', function(evt) {
       $(this).siblings(".options_triangle_parent")
           .children(".options_triangle").show_toolbar();
       return false;
   });
   /* the iphone doesn't play nice with live() unless there is already a registered click function.  That's sad */
   $(".thing").click(function() {});

   $(".link").live("click", function(evt) {
       if(evt && evt.target && $(evt.target).hasClass("thing")) {
           $(this).find(".triangle_link").click();
           return false;
       }
   });
    $(".comment > .entry, .message > .entry").live("click", function(evt) {
        var foo = (evt) ? $(evt.target) : null;
        var thing = $(this).parent();
        if(thing.hasClass("active")) {
            thing.removeClass("active");
            return false;
        } 
        /* collapsed messages/comments should uncolapse */
        else if(thing.hasClass("collapsed")) {
            thing.removeClass("collapsed");
            return false;
        } 
        /* unread messages should be marked read */
        else if(thing.hasClass("unread") || thing.hasClass("new")) {
            read_thing(thing);
            return false;
        }
        /* otherwise, fire a menu */
        else if(foo &&
                foo.filter("a").length == 0 && 
                !foo.hasClass("arrow") && 
                !foo.hasClass("button") && 
                foo.filter("textarea").length == 0) {
            thing.find(".triangle_link:first").click();
            return false;
        }
       });
   /*Finally*/
    $('a[href=#]').live('click', function() { return false; } );
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
        .find("form input[name=reason]").val(reason || "");
    return false;
}

function hidecover(where) {
    $(where).parents(".cover-overlay").fadeOut();
    return false;
};

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
    if (path[path.length-1].indexOf('/') == -1) {
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
            $(".thing").click(function() {});
            /* remove the loading image */
            $("#siteTable").next(".loading").remove();
            if (res && res.data.length == 0) {
                $(window).unbind("scroll");
            }
        });
}

function toggle_collapse(elem) {
    $(elem).thing().addClass("collapsed").addClass("active")
        .find('.thing_option_close:first').click();
    return false; 
}

