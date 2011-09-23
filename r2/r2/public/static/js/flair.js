$(function() {
    function showSaveButton(field) {
        $(field).parent().parent().addClass("edited");
        $(field).parent().parent().find(".status").html("");
    }

    function onEdit() {
        if ($(this).data("saved") != $(this).val()) {
            showSaveButton(this);
        }
    }

    function onDelete(action) {
        return post_form(this.parentNode, action);
    }

    function makeOnDelete(action) {
        return function() { return onDelete.call(this, action); };
    }

    function onFocus() {
        showSaveButton(this);
    }

    function onSubmit(action) {
        $(this).removeClass("edited");
        return post_form(this, action);
    }

    function makeOnSubmit(action) {
        return function() { return onSubmit.call(this, action); };
    }

    function toggleFlairSelector() {
        open_menu(this);
        $(this).addClass("active");
        return false;
    }

    function selectFlairInSelector(e) {
        $(".flairselector li").removeClass("selected");
        $(this).addClass("selected");
        var form = $(this).parent().parent().siblings("form")[0];
        $(form).children('input[name="flair_template_id"]').val(this.id);
        var customizer = $(form).children(".customizer");
        var input = customizer.children("input");
        input.val($.trim($(this).children(".flair").text())).select();
        input.keyup(function() {
            $(".flairselection .flair").text($(input).val());
        });
        if ($(this).hasClass("texteditable")) {
            customizer.addClass("texteditable");
            input.removeAttr("disabled");
        } else {
            customizer.removeClass("texteditable");
            input.attr("disabled", "disabled");
        }
        $(".flairselection").html($(this).first().children().clone());
        $(".flairselector button").removeAttr("disabled");
        return false;
    }

    function postFlairSelection(e) {
        $(this).parent().parent().siblings("input").val(this.id);
        post_form(this.parentNode.parentNode.parentNode, "selectflair");
        return false;
    }

    function openFlairSelector(e) {
        close_menus(e);

        var button = this;
        var selector = $(button).siblings(".flairselector")[0];

        function columnize(col) {
            var min_cols = 1;
            var max_cols = 3;
            var max_col_height = 10;
            var length = $(col).children().length;
            var num_cols =
                Math.max(
                    min_cols,
                    Math.min(max_cols, Math.ceil(length / max_col_height)));
            var height = Math.ceil(length / num_cols);
            var num_short_cols = num_cols * height - length;

            for (var i = 1; i < num_cols; i++) {
                var h = height;
                if (i <= num_short_cols) {
                    h--;
                }
                var start = length - h;
                length -= h;
                var tail = $(col).children().slice(start).remove();
                $(col).after($("<ul>").append(tail));
            }
            return num_cols * 200 + 50;
        }

        function handleResponse(r) {
            $(selector).html(r);

            var width = columnize($(".flairselector ul"));
            var left = Math.max(
                100, $(button).position().left + $(button).width() - width);

            $(selector)
                .width(width)
                .css("left", left + "px")
                .click(false)
                .find(".flairselection")
                    .click(false)
                .end()
                .find("form")
                    // don't bubble clicks in the form up to the .click(false)
                    .click(function(e) { e.stopPropagation(); })
                    .submit(postFlairSelection)
                .end()
                .find(".customizer input")
                    .attr("disabled", "disabled")
                .end()
                .find("button")
                    .attr("disabled", "disabled")
                .end()
                .find("li.selected")
                    .each(selectFlairInSelector)
                .end()
                .find("li:not(.error)")
                    .click(selectFlairInSelector)
                .end();
        }

        $(selector)
            .html('<img src="/static/throbber.gif" />')
            .addClass("active").width(18)
            .css("left",
                 ($(button).position().left + $(button).width() - 18) + "px")
            .css("top", $(button).position().top + "px");

        var name = $(selector).siblings("form").find("input").val();
        $.request("flairselector", {"name": name}, handleResponse, true,
                  "html");
        return false;
    }

    // Attach event handlers to the various flair forms that may be on page.
    $(".flairlist")
        .delegate(".flairtemplate form", "submit",
                  makeOnSubmit('flairtemplate'))
        .delegate("form.clearflairtemplates", "submit",
                  makeOnSubmit('clearflairtemplates'))
        .delegate(".flairgrant .usertable form", "submit",
                  makeOnSubmit('flair'))
        .delegate(".flaircell input", "focus", onFocus)
        .delegate(".flaircell input", "keyup", onEdit)
        .delegate(".flaircell input", "change", onEdit)
        .delegate(".flairtemplate .flairdeletebtn", "click",
                  makeOnDelete("deleteflairtemplate"))
        .delegate(".flairgrant .flairdeletebtn", "click",
                  makeOnDelete("deleteflair"));

    // Event handlers for sidebar flair prefs.
    $(".flairtoggle").submit(function() {
        return post_form(this, 'setflairenabled');
    });
    $(".flairtoggle input").change(function() { $(this).parent().submit(); });

    $(".tagline").delegate(".flairselectbtn", "click", openFlairSelector);

    $(".flairselector .dropdown").click(toggleFlairSelector);
});
