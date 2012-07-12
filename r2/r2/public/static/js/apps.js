$(function() {
    $(".edit-app-button").click(
        function() {
            $(this).toggleClass("collapsed");
            $(this).parent().parent().find(".edit-app").slideToggle();
        });
});

function app_revoked(elem, op) {
    $(elem).closest(".authorized-app").fadeOut();
}

function app_deleted(elem, op) {
    $(elem).closest(".developed-app").fadeOut();
}
