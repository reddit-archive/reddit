r.report = {
  "init": function() {
    $('div.content').on(
      'click',
      '.report-thing, button.cancel-report-thing',
      $.proxy(this, 'toggleReportForm')
    );

    $('div.content').on(
      'submit',
      'form.report-form',
      $.proxy(this, 'submitReport')
    );

    $('div.content').on(
      'change',
      '.report-form input[type="radio"]',
      $.proxy(this, 'enableReportForm')
    );

    $('div.content').on(
      'click',
      '.reported-stamp.has-reasons',
      $.proxy(function(event) {
        $(event.target).parent().find('.report-reasons').toggle()
      }, this)
    );
  },

  toggleReportForm: function(event) {
    var element = event.target;
    var $thing = $(element).thing();
    var $thingForm = $thing.find("> .entry .report-form");

    event.stopPropagation();
    event.preventDefault();

    if ($thingForm.length > 0) {
      if ($thingForm.is(":visible")) {
        $thingForm.hide();
      } else {
        $thingForm.show();
      }
    } else {
      var $form = $(".report-form.clonable");
      var $clonedForm = $form.clone();
      var $insertionPoint = $thing.find("> .entry .buttons");
      var thingFullname = $thing.thing_id();

      $clonedForm.removeClass("clonable");
      $clonedForm.attr("id", "report-thing-" + thingFullname);
      $clonedForm.find("input[name='thing_id']").val(thingFullname);
      $clonedForm.insertAfter($insertionPoint);
      $clonedForm.show();
    }
  },

  submitReport: function(event) {
    var $reportForm = $(event.target).thing().find(".report-form")
    return post_pseudo_form($reportForm, "report");
  },

  enableReportForm: function(event) {
    var $thing = $(event.target).thing();
    var $reportForm = $thing.find("> .entry .report-form");
    var $submitButton = $reportForm.find('button.submit-report');
    var $enabledRadio = $reportForm.find('input[type="radio"]:checked');
    var isOther = $enabledRadio.val() == 'other';
    var $otherInput = $reportForm.find('input[name="other_reason"]');

    event.stopPropagation();
    event.preventDefault();

    $submitButton.removeAttr("disabled");

    if (isOther) {
      $otherInput.removeAttr("disabled").focus();
    } else {
      $otherInput.attr("disabled", "disabled");
    }

    return false;
  }
}

$(function() {
  r.report.init();
});
