$(function() {
    $(".edit-app-button").click(
        function() {
            var app = $(this).closest(".developed-app");
            $(this).toggleClass("collapsed");
            app.find(".app-developers").remove();
            app.find(".edit-app").slideToggle();
        });
    $("#create-app-button").click(
        function() {
            $(this).hide();
            $("#create-app").fadeIn();
        });
});

function app_revoked(elem, op) {
    $(elem).closest(".authorized-app").fadeOut();
}

function app_deleted(elem, op) {
    $(elem).closest(".developed-app").fadeOut();
}
