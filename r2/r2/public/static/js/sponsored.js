function update_box(elem) {
   $(elem).prevAll("*[type=checkbox]:first").attr('checked', true);
};

function update_bid(elem) {
    var form = $(elem).parents(".pretty-form:first");
    var bid = parseFloat(form.find("*[name=bid]").val());
    var ndays = ((Date.parse(form.find("*[name=enddate]").val()) -
             Date.parse(form.find("*[name=startdate]").val())) / (86400*1000));
    $("#bid-field span.gray").html("[Current campaign totals " + 
                                   "<b>$" + (bid/ndays).toFixed(2) +
         "</b> per day for <b>" + ndays + " day(s)</b>]");
    $("#duration span.gray")
         .html( ndays == 1 ? "(1 day)" : "(" + ndays + " days)");
 }

var dateFromInput = function(selector, offset) {
   if(selector) {
     var input = $(selector);
     if(input.length) {
        var d = new Date();
        offset = $.with_default(offset, 0);
        d.setTime(Date.parse(input.val()) + offset);
        return d;
     }
   }
};

function attach_calendar(where, min_date_src, max_date_src, callback) {
     $(where).siblings(".datepicker").mousedown(function() {
            $(this).addClass("clicked active");
         }).click(function() {
            $(this).removeClass("clicked")
               .not(".selected").siblings("input").focus().end()
               .removeClass("selected");
         }).end()
         .focus(function() {
          var target = $(this);
          var dp = $(this).siblings(".datepicker");
          if (dp.children().length == 0) {
             dp.each(function() {
               $(this).datepicker(
                  {
                      defaultDate: dateFromInput(target),
                          minDate: dateFromInput(min_date_src, 86400 * 1000),
                          maxDate: dateFromInput(max_date_src),
                          prevText: "&laquo;", nextText: "&raquo;",
                          altField: "#" + target.attr("id"),
                          onSelect: function() {
                              $(dp).addClass("selected").removeClass("clicked");
                              $(target).blur();
                              if(callback) callback(this);
                          }
                })
              })
              .addClass("drop-choices");
          };
          dp.addClass("inuse active");
     }).blur(function() {
        $(this).siblings(".datepicker").not(".clicked").removeClass("inuse");
     }).click(function() {
        $(this).siblings(".datepicker.inuse").addClass("active");
     });
}