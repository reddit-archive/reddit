$(function() {
  function toggleReportForm() {
    var $reportForm = $(this).closest('.reportform');
    $reportForm.toggleClass('active');
    return false
  }

  function toggleOther() {
    var $reportForm = $(this).closest('.reportform');
    var $submit = $reportForm.find('[type="submit"]');
    var $reason = $reportForm.find('[name=reason]:checked');
    var $other = $reportForm.find('[name="other_reason"]');
    var isOther = $reason.val() === 'other';

    $submit.removeAttr('disabled');

    if (isOther) {
      $other.removeAttr('disabled').focus();
    } else {
      $other.attr('disabled', 'disabled');
    }
    return false
  }

  function getReportAttrs($el) {
    return {thing: $el.thing_id()}
  }

  function openReportForm(e) {
    if (r.access.isLinkRestricted(e.target)) {
      return false;
    }

    var $flatList = $(this).closest('.flat-list');
    var $reportForm = $flatList.siblings('.reportform').eq(0);
    $reportForm.toggleClass('active');

    if (!$reportForm.hasClass('active')) {
      return;
    }

    function handleResponse(r) {
      $reportForm.html(r);
      var $form = $reportForm.children("form");
      $form.css( "display", "block");
    }

    $reportForm.html('<img class="flairthrobber" />')
    var $imgChild = $reportForm.children("img");
    $imgChild.attr('src', r.utils.staticURL('throbber.gif'));

    var attrs = getReportAttrs($(this))
    $.request("report_form",  attrs, handleResponse, true, "html", true);
    return false;
  }

  $("div.content").on("click", ".tagline .reportbtn, .thing .reportbtn", openReportForm);
  $("div.content").on("click", ".btn.report-cancel", toggleReportForm);
  $("div.content").on("change", "input[name='reason']", toggleOther);
});
