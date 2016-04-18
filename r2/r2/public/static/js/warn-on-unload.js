$(function() {
  var form = $("form.warn-on-unload");

  r.warn_on_unload = function() {
    /*
     * To add a warning message to a form if the
     * user tries to leave a page where a form is in a
     * dirty state, add the following classes to your form:
     *
     * warn-on-unload - this class will prompt the user if
     * they try to leave a page with a dirty form
     *
     * redirect-form - Must use this class in conjunction with
     * the warn-on-dialog class if the form redirects after
     * a successful submission. This prevents the beforeunload
     * event listener from reattaching after a successful form
     * submission.
     */
    $(window).on('beforeunload', function (e) {

      if(!$(form).length) {
        return;
      }

      var elements = form.find("input[type=text]," +
                               "input[type=checkbox]," +
                               "input[type=url]," +
                               "textarea");
      var isDirty = false;
      elements.each(function() {

        switch(this.type) {
          case "checkbox":
            isDirty = (this.defaultChecked !== this.checked);
            break;
          case "textarea":
          case "text":
          case "url":
            isDirty = (this.defaultValue !== this.value);
            break;
          default:
            return true;
        }

        if(isDirty) {
          return false;
        }

      });

      if(isDirty) {
        return r._("You have unsaved changes!");
      }
    });
  };

  if($(form).length) {
    r.warn_on_unload();
  }
});
