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

    function onSubmit() {
        $(this).removeClass("edited");
        return post_form(this, "flair");
    }

    /* Attach event handlers to the various flair forms that may be on page. */
    $(".flairrow form").submit(onSubmit);
    $(".flaircell input").focus(onFocus);
    $(".flaircell input").keyup(onEdit);

    $(".flairtoggle").submit(function() {
            return post_form(this, 'setflairenabled');
        });
    $(".flairtoggle input").change(function() { $(this).parent().submit(); });
});
