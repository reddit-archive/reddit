$(function() {
    $(".edit-app-button").click(
        function() {
            $(this).toggleClass("collapsed");
            $(this).parent().parent().find(".edit-app").slideToggle();
        });
});
