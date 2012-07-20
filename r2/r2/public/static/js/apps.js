$(function() {
    $("#developed-apps")
        .delegate(".edit-app-button", "click",
                  function() {
                      $(this).toggleClass("collapsed").closest(".developed-app")
                          .removeClass('collapsed')
                          .find(".app-developers").remove().end()
                          .find(".edit-app")
                            .slideToggle().removeClass('collapsed').end();
                  })
        .delegate(".edit-app-icon-button", "click",
                  function() {
                      $(this).toggleClass("collapsed")
                          .closest(".developed-app")
                              .find(".ajax-upload-form").show();
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
