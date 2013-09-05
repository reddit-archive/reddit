r.sponsored = {
    init: function() {
        $("#sr-autocomplete").on("sr-changed blur", function() {
            r.sponsored.fill_campaign_editor()
        })

        this.inventory = {}
    },

    setup: function(inventory_by_sr) {
        this.inventory = inventory_by_sr
    },

    get_dates: function(startdate, enddate) {
        var start = $.datepicker.parseDate('mm/dd/yy', startdate),
            end = $.datepicker.parseDate('mm/dd/yy', enddate),
            ndays = (end - start) / (1000 * 60 * 60 * 24),
            dates = []

        for (var i=0; i < ndays; i++) {
            var d = new Date(start.getTime())
            d.setDate(start.getDate() + i)
            dates.push(d)
        }
        return dates
    },

    get_check_inventory: function(srname, dates) {
        var fetch = _.some(dates, function(date) {
            var datestr = $.datepicker.formatDate('mm/dd/yy', date)
            if (!(this.inventory[srname] && this.inventory[srname][datestr])) {
                r.debug('need to fetch ' + datestr + ' for ' + srname)
                return true
            }
        }, this)

        if (fetch) {
            dates.sort(function(d1,d2){return d1 - d2})
            var end = new Date(dates[dates.length-1].getTime())
            end.setDate(end.getDate() + 5)

            return $.ajax({
                type: 'GET',
                url: '/api/check_inventory.json',
                data: {
                    sr: srname,
                    startdate: $.datepicker.formatDate('mm/dd/yy', dates[0]),
                    enddate: $.datepicker.formatDate('mm/dd/yy', end)
                },
                success: function(data) {
                    if (!r.sponsored.inventory[srname]) {
                        r.sponsored.inventory[srname] = {}
                    }

                    for (var datestr in data.inventory) {
                        if (!r.sponsored.inventory[srname][datestr]) {
                            r.sponsored.inventory[srname][datestr] = data.inventory[datestr]
                        }
                    }
                }
            })
        } else {
            return true
        }
    },

    get_booked_inventory: function($form, srname) {
        var campaign_id36 = $form.find('input[name="campaign_id36"]').val(),
            campaign_row = $('.existing-campaigns .campaign-row input[name="campaign_id36"]')
                                .filter('*[value="' + campaign_id36 + '"]')
                                .parents("tr")

        if (!campaign_row.length) {
            return {}
        }

        var existing_srname = campaign_row.find('*[name="targeting"]').val()
        if (srname != existing_srname) {
            return {}
        }

        var startdate = campaign_row.find('*[name="startdate"]').val(),
            enddate = campaign_row.find('*[name="enddate"]').val(),
            dates = this.get_dates(startdate, enddate),
            bid = campaign_row.find('*[name="bid"]').val(),
            cpm = campaign_row.find('*[name="cpm"]').val(),
            ndays = this.duration_from_dates(startdate, enddate),
            impressions = this.calc_impressions(bid, cpm),
            daily = Math.floor(impressions / ndays),
            booked = {}

        _.each(dates, function(date) {
            var datestr = $.datepicker.formatDate('mm/dd/yy', date)
            booked[datestr] = daily
        })
        return booked

    },

    check_inventory: function($form) {
        var bid = this.get_bid($form),
            cpm = this.get_cpm($form),
            requested = this.calc_impressions(bid, cpm),
            startdate = $form.find('*[name="startdate"]').val(),
            enddate = $form.find('*[name="enddate"]').val(),
            ndays = this.get_duration($form),
            daily_request = Math.floor(requested / ndays),
            targeted = $form.find('#targeting').is(':checked'),
            target = $form.find('*[name="sr"]').val(),
            srname = targeted ? target : '',
            dates = r.sponsored.get_dates(startdate, enddate),
            booked = this.get_booked_inventory($form, srname)

        // bail out in state where targeting is selected but srname
        // has not been entered yet
        if (targeted && srname == '') {
            r.sponsored.disable_form($form)
            return
        }

        $.when(r.sponsored.get_check_inventory(srname, dates)).done(
            function() {
                var minDaily = _.min(_.map(dates, function(date) {
                    var datestr = $.datepicker.formatDate('mm/dd/yy', date),
                        daily_booked = booked[datestr] || 0
                    return r.sponsored.inventory[srname][datestr] + daily_booked
                }))

                var available = minDaily * ndays

                if (available < requested) {
                    var message = r._("We have insufficient inventory to fulfill" +
                                      " your requested budget, target, and dates." +
                                      " Only %(available)s impressions available" +
                                      " on %(target)s from %(start)s to %(end)s. " +
                                      "Maximum budget is $%(max)s."
                                  ).format({
                                      available: r.utils.prettyNumber(available),
                                      target: targeted ? srname : 'the frontpage',
                                      start: startdate,
                                      end: enddate,
                                      max: r.sponsored.calc_bid(available, cpm)
                                  })

                    $(".available-info").text('')
                    $(".OVERSOLD_DETAIL").text(message).show()
                    r.sponsored.disable_form($form)
                } else {
                    $(".available-info").text(r._("(%(num)s available)").format({num: r.utils.prettyNumber(available)}))
                    $(".OVERSOLD_DETAIL").hide()
                    r.sponsored.enable_form($form)
                }
            }
        )
    },

    duration_from_dates: function(start, end) {
        return Math.round((Date.parse(end) - Date.parse(start)) / (86400*1000))
    },

    get_duration: function($form) {
        var start = $form.find('*[name="startdate"]').val(),
            end = $form.find('*[name="enddate"]').val()

        return this.duration_from_dates(start, end)
    },

    get_bid: function($form) {
        return parseFloat($form.find('*[name="bid"]').val())
    },

    get_cpm: function($form) {
        return parseInt($form.find('*[name="cpm"]').val())
    },

    on_date_change: function() {
        this.fill_campaign_editor()
    },

    on_bid_change: function() {
        this.fill_campaign_editor()
    },

    fill_campaign_editor: function() {
        var $form = $("#campaign"),
            bid = this.get_bid($form),
            cpm = this.get_cpm($form),
            ndays = this.get_duration($form),
            impressions = this.calc_impressions(bid, cpm);

        $(".duration").text(ndays + " " + ((ndays > 1) ? r._("days") : r._("day")))
        $(".impression-info").text(r._("%(num)s impressions").format({num: r.utils.prettyNumber(impressions)}))
        $(".price-info").text(r._("$%(cpm)s per 1,000 impressions").format({cpm: (cpm/100).toFixed(2)}))

        this.check_bid($form)
        this.check_inventory($form)
    },

    disable_form: function($form) {
        $form.find('button[name="create"], button[name="save"]')
            .prop("disabled", "disabled")
            .addClass("disabled");
    },

    enable_form: function($form) {
        $form.find('button[name="create"], button[name="save"]')
            .removeProp("disabled")
            .removeClass("disabled");
    },

    targeting_on: function() {
        $('.targeting').find('*[name="sr"]').prop("disabled", "").end().slideDown();
        this.fill_campaign_editor()
    },

    targeting_off: function() {
        $('.targeting').find('*[name="sr"]').prop("disabled", "disabled").end().slideUp();
        this.fill_campaign_editor()
    },

    check_bid: function($form) {
        var bid = this.get_bid($form),
            minimum_bid = $("#bid").data("min_bid");

        $(".minimum-spend").removeClass("error");
        if (bid < minimum_bid) {
            $(".minimum-spend").addClass("error");
            this.disable_form($form)
        } else {
            this.enable_form($form)
        }
    },

    calc_impressions: function(bid, cpm_pennies) {
        return bid / cpm_pennies * 1000 * 100
    },

    calc_bid: function(impressions, cpm_pennies) {
        return impressions * cpm_pennies / 1000 / 100
    }
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

function attach_calendar(where, min_date_src, max_date_src, callback, min_date_offset) {
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
                          minDate: dateFromInput(min_date_src, min_date_offset),
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

function check_enddate(startdate, enddate) {
  var startdate = $(startdate)
  var enddate = $(enddate);
  if(dateFromInput(startdate) >= dateFromInput(enddate)) {
    var newd = new Date();
    newd.setTime(startdate.datepicker('getDate').getTime() + 86400*1000);
    enddate.val((newd.getMonth()+1) + "/" +
      newd.getDate() + "/" + newd.getFullYear());
  }
  $("#datepicker-" + enddate.attr("id")).datepicker("destroy");
}


(function($) {

function get_flag_class(flags) {
    var css_class = "campaign-row";
    if(flags.free) {
        css_class += " free";
    }
    if(flags.live) {
        css_class += " live";
    }
    if(flags.complete) {
        css_class += " complete";
    }
    else if (flags.paid) {
            css_class += " paid";
    }
    if (flags.sponsor) {
        css_class += " sponsor";
    }
    if (flags.refund) {
        css_class += " refund";
    }
    return css_class
}

$.new_campaign = function(campaign_id36, start_date, end_date, duration,
                          bid, spent, cpm, targeting, flags) {
    cancel_edit(function() {
      var data =('<input type="hidden" name="startdate" value="' + 
                 start_date +'"/>' + 
                 '<input type="hidden" name="enddate" value="' + 
                 end_date + '"/>' + 
                 '<input type="hidden" name="bid" value="' + bid + '"/>' +
                 '<input type="hidden" name="cpm" value="' + cpm + '"/>' +
                 '<input type="hidden" name="targeting" value="' + 
                 (targeting || '') + '"/>' +
                 '<input type="hidden" name="campaign_id36" value="' + campaign_id36 + '"/>');
      if (flags && flags.pay_url) {
          data += ("<input type='hidden' name='pay_url' value='" + 
                   flags.pay_url + "'/>");
      }
      if (flags && flags.view_live_url) {
          data += ("<input type='hidden' name='view_live_url' value='" + 
                   flags.view_live_url + "'/>");
      }
      if (flags && flags.refund_url) {
          data += ("<input type='hidden' name='refund_url' value='" + 
                   flags.refund_url + "'/>");
      }
      var row = [start_date, end_date, duration, "$" + bid, "$" + spent, targeting, data];
      $(".existing-campaigns .error").hide();
      var css_class = get_flag_class(flags);
      $(".existing-campaigns table").show()
      .insert_table_rows([{"id": "", "css_class": css_class, 
                           "cells": row}], -1);
      check_number_of_campaigns();
      $.set_up_campaigns()
        });
   return $;
};

$.update_campaign = function(campaign_id36, start_date, end_date,
                             duration, bid, spent, cpm, targeting, flags) {
    cancel_edit(function() {
            $('.existing-campaigns input[name="campaign_id36"]')
                .filter('*[value="' + (campaign_id36 || '0') + '"]')
                .parents("tr").removeClass()
            .addClass(get_flag_class(flags))
                .children(":first").html(start_date)
                .next().html(end_date)
                .next().html(duration)
                .next().html("$" + bid).removeClass()
                .next().html("$" + spent)
                .next().html(targeting)
                .next()
                .find('*[name="startdate"]').val(start_date).end()
                .find('*[name="enddate"]').val(end_date).end()
                .find('*[name="targeting"]').val(targeting).end()
                .find('*[name="bid"]').val(bid).end()
                .find('*[name="cpm"]').val(cpm).end()
                .find("button, span").remove();
            $.set_up_campaigns();
        });
};

$.set_up_campaigns = function() {
    var edit = "<button>edit</button>";
    var del = "<button>delete</button>";
    var pay = "<button>pay</button>";
    var free = "<button>free</button>";
    var repay = "<button>change</button>";
    var view = "<button>view live</button>";
    var refund = "<button>refund</button>";
    $(".existing-campaigns tr").each(function() {
            var tr = $(this);
            var td = $(this).find("td:last");
            var bid_td = $(this).find("td:first").next().next().next()
                .addClass("bid");
            if(td.length && ! td.children("button, span").length ) {
                if(tr.hasClass("live")) {
                    $(td).append($(view).addClass("view fancybutton")
                            .click(function() { view_campaign(tr) }));
                }

                if (tr.hasClass('refund')) {
                    $(bid_td).append($(refund).addClass("refund fancybutton")
                            .click(function() { refund_campaign(tr) }));
                }

                /* once paid, we shouldn't muck around with the campaign */
                if(!tr.hasClass("complete") && !tr.hasClass("live")) {
                    if (tr.hasClass("sponsor") && !tr.hasClass("free")) {
                        $(bid_td).append($(free).addClass("free")
                                     .click(function() { free_campaign(tr) }))
                    }
                    else if (!tr.hasClass("paid")) {
                        $(bid_td).prepend($(pay).addClass("pay fancybutton")
                                     .click(function() { pay_campaign(tr) }));
                    } else if (tr.hasClass("free")) {
                        $(bid_td).addClass("free paid")
                            .prepend("<span class='info'>freebie</span>");
                    } else {
                        (bid_td).addClass("paid")
                            .prepend($(repay).addClass("pay fancybutton")
                                     .click(function() { pay_campaign(tr) }));
                    }
                    var e = $(edit).addClass("edit fancybutton")
                        .click(function() { edit_campaign(tr); });
                    var d = $(del).addClass("d fancybutton")
                        .click(function() { del_campaign(tr); });
                    $(td).append(e).append(d);
                } else {
                    if (tr.hasClass("complete")) {
                      $(td).append("<span class='info'>complete</span>");
                    }
                    $(bid_td).addClass("paid")
                    /* sponsors can always edit */
                    if (tr.hasClass("sponsor")) {
                        var e = $(edit).addClass("edit fancybutton")
                            .click(function() { edit_campaign(tr); });
                        $(td).append(e);
                    }
                }
            }
        });
    return $;

}

}(jQuery));

function detach_campaign_form() {
    /* remove datepicker from fields */
    $("#campaign").find(".datepicker").each(function() {
            $(this).datepicker("destroy").siblings().unbind();
        });

    /* detach and return */
    var campaign = $("#campaign").detach();
    return campaign;
}

function cancel_edit(callback) {
    if($("#campaign").parents('tr:first').length) {
        var tr = $("#campaign").parents("tr:first").prev();
        /* copy the campaign element */
        /* delete the original */
        $("#campaign").fadeOut(function() {
                $(this).parent('tr').prev().fadeIn();
                var td = $(this).parent();
                var campaign = detach_campaign_form();
                td.delete_table_row(function() {
                        tr.fadeIn(function() {
                                $(".existing-campaigns").before(campaign);
                                campaign.hide();
                                if(callback) { callback(); }
                            });
                    });
            });
    } else {
        if ($("#campaign:visible").length) {
            $("#campaign").fadeOut(function() {
                    if(callback) { 
                        callback();
                    }});
        }
        else if (callback) {
            callback();
        }
    }
}

function del_campaign(elem) {
    var campaign_id36 = $(elem).find('*[name="campaign_id36"]').val();
    var link_id = $("#campaign").find('*[name="link_id"]').val();
    $.request("delete_campaign", {"campaign_id36": campaign_id36,
                                  "link_id": link_id},
              null, true, "json", false);
    $(elem).children(":first").delete_table_row(check_number_of_campaigns);
}


function edit_campaign(elem) {
    /* find the table row in question */
    var tr = $(elem).get(0);

    if ($("#campaign").parents('tr:first').get(0) != tr) {

        cancel_edit(function() {

            /* copy the campaign element */
            var campaign = detach_campaign_form();

            $(".existing-campaigns table")
                .insert_table_rows([{"id": "edit-campaign-tr",
                                "css_class": "", "cells": [""]}], 
                    tr.rowIndex + 1);
            $("#edit-campaign-tr").children('td:first')
                .attr("colspan", 8).append(campaign).end()
                .prev().fadeOut(function() { 
                        var data_tr = $(this);
                        var c = $("#campaign");
                        $.map(['startdate', 'enddate', 'bid', 'cpm', 'campaign_id36'],
                              function(i) {
                                  i = '*[name="' + i + '"]';
                                  c.find(i).val(data_tr.find(i).val());
                              });
                        /* check if targeting is turned on */
                        var targeting = data_tr
                            .find('*[name="targeting"]').val();
                        var radios=c.find('*[name="targeting"]');
                        if (targeting) {
                            radios.filter('*[value="one"]')
                                .prop("checked", "checked");
                            c.find('*[name="sr"]').val(targeting).prop("disabled", "").end()
                                .find(".targeting").show();
                        }
                        else {
                            radios.filter('*[value="none"]')
                                .prop("checked", "checked");
                            c.find('*[name="sr"]').val("").prop("disabled", "disabled").end()
                                .find(".targeting").hide();
                        }
                        /* attach the dates to the date widgets */
                        init_startdate();
                        init_enddate();
                        c.find('button[name="save"]').show().end()
                            .find('button[name="create"]').hide().end();
                        r.sponsored.fill_campaign_editor();
                        c.fadeIn();
                    } );
            }
            );
    }
}

function check_number_of_campaigns(){
    if ($(".campaign-row").length >= $(".existing-campaigns").data("max-campaigns")){
      $(".error.TOO_MANY_CAMPAIGNS").fadeIn();
      $("button.new-campaign").attr("disabled", "disabled");
      return true;
    } else {
      $(".error.TOO_MANY_CAMPAIGNS").fadeOut();
      $("button.new-campaign").removeAttr("disabled");
      return false;
    }
}

function create_campaign() {
    if (check_number_of_campaigns()){
        return;
    }
    cancel_edit(function() {;
            var base_cpm = $("#bid").data("base_cpm")
            init_startdate();
            init_enddate();
            $("#campaign")
                .find('button[name="edit"]').hide().end()
                .find('button[name="create"]').show().end()
                .find('input[name="campaign_id36"]').val('').end()
                .find('input[name="sr"]').val('').prop("disabled", "disabled").end()
                .find('input[name="targeting"][value="none"]').prop("checked", "checked").end()
                .find(".targeting").hide().end()
                .find('input[name="cpm"]').val(base_cpm).end()
                .fadeIn();
            r.sponsored.fill_campaign_editor();
        });
}

function free_campaign(elem) {
    var campaign_id36 = $(elem).find('*[name="campaign_id36"]').val();
    var link_id = $("#campaign").find('*[name="link_id"]').val();
    $.request("freebie", {"campaign_id36": campaign_id36, "link_id": link_id},
              null, true, "json", false);
    $(elem).find(".free").fadeOut();
    return false; 
}

function pay_campaign(elem) {
    $.redirect($(elem).find('input[name="pay_url"]').val());
}

function view_campaign(elem) {
    $.redirect($(elem).find('input[name="view_live_url"]').val());
}

function refund_campaign(elem) {
    $.redirect($(elem).find('input[name="refund_url"]').val());
}
