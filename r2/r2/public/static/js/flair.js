$(function() {
    function onedit() {
        if ($(this).data("saved") != $(this).val()) {
            $(this).parent().parent().addClass("edited");
            $(this).parent().parent().find(".status").html("");
        }
    }

    /* Attach event handlers to the various flair forms that may be on page. */
    $(".flairrow form").submit(function() { return post_form(this, 'flair'); });
    $(".flaircell input").focus(onedit);
    $(".flaircell input").keyup(onedit);
    $(".flairrow button").click(function() {
            $(this).parent().removeClass("edited");
        });
    $(".flairtoggle").submit(function() {
            return post_form(this, 'setflairenabled');
        });
    $(".flairtoggle input").change(function() { $(this).parent().submit(); });
});
