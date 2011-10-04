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

    // Attach event handlers to the various flair forms that may be on page.
    $(".flairlist").delegate(".flairtemplate form", "submit",
                             makeOnSubmit('flairtemplate'));
    $(".flairlist").delegate("form.flair-entry", "submit",
                             makeOnSubmit('flair'));
    $(".flairlist").delegate(".flaircell input", "focus", onFocus);
    $(".flairlist").delegate(".flaircell input", "keyup", onEdit);

    // Event handlers for sidebar flair prefs.
    $(".flairtoggle").submit(function() {
        return post_form(this, 'setflairenabled');
    });
    $(".flairtoggle input").change(function() { $(this).parent().submit(); });
});
