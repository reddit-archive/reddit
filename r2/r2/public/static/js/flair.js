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

    function postFlairSelection(e) {
        $(this).parent().parent().siblings("input").val(this.id);
        post_form(this.parentNode.parentNode.parentNode, "selectflair");
        return false;
    }

    function openFlairSelector() {
        var button = this;

        function columnize(col) {
            var max_col_height = 10;
            var length = $(col).children().length;
            var num_cols = Math.ceil(length / max_col_height);
            var height = Math.ceil(length / num_cols);
            var num_short_cols = num_cols * height - length;

            for (var i = 1; i < num_cols; i++) {
                var h = height;
                if (i <= num_short_cols) {
                    h--;
                }
                var start = length - h;
                length -= h;
                var tail = $(col).children().slice(start).detach();
                $(col).after($("<ul>").append(tail));
            }
            return num_cols * 200;
        }

        function handleResponse(r) {
            $(".flairselector").html(r);

            var width = columnize($(".flairselector ul"));

            $(".flairselector").width(width)
                .css("left",
                     ($(button).position().left + $(button).width() - width)
                     + "px");
            $(".flairselector li:not(.error)").click(postFlairSelection);
        }

        $(".flairselector").html('<img src="/static/throbber.gif" />');
        $(".flairselector").addClass("active").width(18)
            .css("left",
                 ($(button).position().left + $(button).width() - 18) + "px")
            .css("top", $(button).position().top + "px");
        $.request("flairselector", {}, handleResponse, true, "html");
        return false;
    }

    // Attach event handlers to the various flair forms that may be on page.
    $(".flairlist").delegate(".flairtemplate form", "submit",
                             makeOnSubmit('flairtemplate'));
    $(".flairlist").delegate("form.flair-entry", "submit",
                             makeOnSubmit('flair'));
    $(".flairlist").delegate(".flaircell input", "focus", onFocus);
    $(".flairlist").delegate(".flaircell input", "keyup", onEdit);
    $(".flairlist").delegate(".flaircell input", "change", onEdit);

    // Event handlers for sidebar flair prefs.
    $(".flairtoggle").submit(function() {
        return post_form(this, 'setflairenabled');
    });
    $(".flairtoggle input").change(function() { $(this).parent().submit(); });

    $(".flairselectbtn").click(openFlairSelector);

    $(".flairselector .dropdown").click(toggleFlairSelector);
});
