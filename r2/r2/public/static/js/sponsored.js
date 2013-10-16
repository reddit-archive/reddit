r.sponsored = {
    init: function() {
        $("#sr-autocomplete").on("sr-changed blur", function() {
            r.sponsored.fill_campaign_editor()
        })
        this.inventory = {}
    },

    setup: function(inventory_by_sr, isEmpty) {
        this.inventory = inventory_by_sr
        if (isEmpty) {
            this.fill_campaign_editor()
        }
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

    get_booked_inventory: function($form, srname, isOverride) {
        var campaign_name = $form.find('input[name="campaign_name"]').val()
        if (!campaign_name) {
            return {}
        }

        var $campaign_row = $('.existing-campaigns .' + campaign_name)
        if (!$campaign_row.length) {
            return {}
        }

        if (!$campaign_row.data('paid')) {
            return {}
        }

        var existing_srname = $campaign_row.data("targeting")
        if (srname != existing_srname) {
            return {}
        }

        var existingOverride = $campaign_row.data("override")
        if (isOverride != existingOverride) {
            return {}
        }

        var startdate = $campaign_row.data("startdate"),
            enddate = $campaign_row.data("enddate"),
            dates = this.get_dates(startdate, enddate),
            bid = $campaign_row.data("bid"),
            cpm = $campaign_row.data("cpm"),
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

    check_inventory: function($form, isOverride) {
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
            booked = this.get_booked_inventory($form, srname, isOverride)

        // bail out in state where targeting is selected but srname
        // has not been entered yet
        if (targeted && srname == '') {
            r.sponsored.disable_form($form)
            return
        }

        $.when(r.sponsored.get_check_inventory(srname, dates)).done(
            function() {
                if (isOverride) {
                    // do a simple sum of available inventory for override
                    var available = _.reduce(_.map(dates, function(date){
                        var datestr = $.datepicker.formatDate('mm/dd/yy', date),
                            daily_booked = booked[datestr] || 0
                        return r.sponsored.inventory[srname][datestr] + daily_booked
                    }), function(memo, num){ return memo + num; }, 0)
                } else {
                    // calculate conservative inventory estimate
                    var minDaily = _.min(_.map(dates, function(date) {
                        var datestr = $.datepicker.formatDate('mm/dd/yy', date),
                            daily_booked = booked[datestr] || 0
                        return r.sponsored.inventory[srname][datestr] + daily_booked
                    }))
                    var available = minDaily * ndays
                }

                var maxbid = r.sponsored.calc_bid(available, cpm)

                if (available < requested) {
                    if (isOverride) {
                        var message = r._("We expect to only have %(available)s " + 
                                          "impressions on %(target)s from %(start)s " +
                                          "to %(end)s. We may not fully deliver."
                                      ).format({
                                          available: r.utils.prettyNumber(available),
                                          target: targeted ? srname : 'the frontpage',
                                          start: startdate,
                                          end: enddate
                                      })
                        $(".available-info").text('')
                        $(".OVERSOLD_DETAIL").text(message).show()
                    } else {
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
                                          max: maxbid
                                      })

                        $(".available-info").text('')
                        $(".OVERSOLD_DETAIL").text(message).show()
                        r.sponsored.disable_form($form)
                    }
                } else {
                    $(".available-info").text(r._("%(num)s available (maximum budget is $%(max)s)").format({num: r.utils.prettyNumber(available), max: maxbid}))
                    $(".OVERSOLD_DETAIL").hide()
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
        return parseFloat($form.find('*[name="bid"]').val()) || 0
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

    on_impression_change: function() {
        var $form = $("#campaign"),
            cpm = this.get_cpm($form),
            impressions = parseInt($form.find('*[name="impressions"]').val().replace(/,/g, "") || 0)
            bid = this.calc_bid(impressions, cpm),
            $bid = $form.find('*[name="bid"]')
        $bid.val(bid)
        $bid.trigger("change")
    },

    fill_campaign_editor: function() {
        var $form = $("#campaign"),
            bid = this.get_bid($form),
            cpm = this.get_cpm($form),
            ndays = this.get_duration($form),
            impressions = this.calc_impressions(bid, cpm),
            priority = $form.find('*[name="priority"]:checked'),
            isOverride = priority.data("override"),
            isCpm = priority.data("cpm")

        $(".duration").text(ndays + " " + ((ndays > 1) ? r._("days") : r._("day")))
        $(".price-info").text(r._("$%(cpm)s per 1,000 impressions").format({cpm: (cpm/100).toFixed(2)}))
        $form.find('*[name="impressions"]').val(r.utils.prettyNumber(impressions))
        $(".OVERSOLD").hide()

        this.enable_form($form)

        if (isCpm) {
            this.show_cpm()
            this.check_bid($form)
            this.check_inventory($form, isOverride)
        } else {
            this.hide_cpm()
        }
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

    hide_cpm: function() {
        var priceRow = $('#cpm').parent('td').parent('tr'),
            budgetRow = $('#bid').parent('td').parent('tr'),
            impressionsRow = $('#impressions').parent('td').parent('tr')
        priceRow.hide("slow")
        budgetRow.hide("slow")
        impressionsRow.hide("slow")
    },

    show_cpm: function() {
        var priceRow = $('#cpm').parent('td').parent('tr'),
            budgetRow = $('#bid').parent('td').parent('tr'),
            impressionsRow = $('#impressions').parent('td').parent('tr')
        priceRow.show("slow")
        budgetRow.show("slow")
        impressionsRow.show("slow")
    },

    targeting_on: function() {
        $('.targeting').find('*[name="sr"]').prop("disabled", "").end().slideDown();
        this.fill_campaign_editor()
    },

    targeting_off: function() {
        $('.targeting').find('*[name="sr"]').prop("disabled", "disabled").end().slideUp();
        this.fill_campaign_editor()
    },

    priority_changed: function() {
        this.fill_campaign_editor()
    },

    check_bid: function($form) {
        var bid = this.get_bid($form),
            minimum_bid = $("#bid").data("min_bid");

        $(".minimum-spend").removeClass("error");
        if (bid < minimum_bid) {
            $(".minimum-spend").addClass("error");
            this.disable_form($form)
        }
    },

    calc_impressions: function(bid, cpm_pennies) {
        return bid / cpm_pennies * 1000 * 100
    },

    calc_bid: function(impressions, cpm_pennies) {
        return (Math.floor(impressions * cpm_pennies / 1000) / 100).toFixed(2)
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
    $.update_campaign = function(campaign_name, campaign_html) {
        cancel_edit(function() {
            var $existing = $('.existing-campaigns .' + campaign_name),
                tableWasEmpty = $('.existing-campaigns table tr.campaign-row').length == 0

            if ($existing.length) {
                $existing.replaceWith(campaign_html)
                $existing.fadeIn()
            } else {
                $(campaign_html).hide()
                .insertAfter('.existing-campaigns tr:last')
                .css('display', 'table-row')
                .fadeIn()
            }

            if (tableWasEmpty) {
                $('.existing-campaigns p.error').hide()
                $('.existing-campaigns table').fadeIn()
            }
        })
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

function del_campaign($campaign_row) {
    var link_id36 = $("#campaign").find('*[name="link_id36"]').val(),
        campaign_id36 = $campaign_row.data('campaign_id36')
    $.request("delete_campaign", {"campaign_id36": campaign_id36,
                                  "link_id36": link_id36},
              null, true, "json", false);
    $campaign_row.children(":first").delete_table_row(check_number_of_campaigns);
}


function edit_campaign($campaign_row) {
    cancel_edit(function() {
        var campaign = detach_campaign_form()

        $(".existing-campaigns table")
            .insert_table_rows([{
                "id": "edit-campaign-tr",
                "css_class": "",
                "cells": [""]
            }], $campaign_row.get(0).rowIndex + 1)

        var editRow = $("#edit-campaign-tr")
        editRow.children('td:first').attr("colspan", 8).append(campaign)
        $campaign_row.fadeOut(function() {
            /* fill inputs from data in campaign row */
            _.each(['startdate', 'enddate', 'bid', 'cpm', 'campaign_id36', 'campaign_name'],
                function(input) {
                    var val = $campaign_row.data(input),
                        $input = campaign.find('*[name="' + input + '"]')
                    $input.val(val)
            })

            /* set priority */
            var priorities = campaign.find('*[name="priority"]'),
                campPriority = $campaign_row.data("priority")

            priorities.filter('*[value="' + campPriority + '"]')
                .prop("checked", "checked")

            /* check if targeting is turned on */
            var targeting = $campaign_row.data("targeting"),
                radios = campaign.find('*[name="targeting"]');
            if (targeting) {
                radios.filter('*[value="one"]')
                    .prop("checked", "checked");
                campaign.find('*[name="sr"]').val(targeting).prop("disabled", "").end()
                    .find(".targeting").show();
            } else {
                radios.filter('*[value="none"]')
                    .prop("checked", "checked");
                campaign.find('*[name="sr"]').val("").prop("disabled", "disabled").end()
                    .find(".targeting").hide();
            }

            /* attach the dates to the date widgets */
            init_startdate();
            init_enddate();

            campaign.find('button[name="save"]').show().end()
                .find('button[name="create"]').hide().end();
            r.sponsored.fill_campaign_editor();
            campaign.fadeIn();
        })
    })
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
            var base_cpm = $("#bid").data("base_cpm"),
                minBid = $("#bid").data("min_bid")

            init_startdate();
            init_enddate();
            $("#campaign")
                .find('button[name="save"]').hide().end()
                .find('button[name="create"]').show().end()
                .find('input[name="campaign_id36"]').val('').end()
                .find('input[name="campaign_name"]').val('').end()
                .find('input[name="sr"]').val('').prop("disabled", "disabled").end()
                .find('input[name="targeting"][value="none"]').prop("checked", "checked").end()
                .find('input[name="priority"][data-default="true"]').prop("checked", "checked").end()
                .find('input[name="bid"]').val(minBid * 5).end()
                .find(".targeting").hide().end()
                .find('input[name="cpm"]').val(base_cpm).end()
                .fadeIn();
            r.sponsored.fill_campaign_editor();
        });
}

function free_campaign($campaign_row) {
    var link_id36 = $("#campaign").find('*[name="link_id36"]').val(),
        campaign_id36 = $campaign_row.data('campaign_id36')
    $.request("freebie", {"campaign_id36": campaign_id36, "link_id36": link_id36},
              null, true, "json", false);
    $campaign_row.find(".free").fadeOut();
    return false; 
}

function terminate_campaign($campaign_row) {
    var link_id36 = $("#campaign").find('*[name="link_id36"]').val(),
        campaign_id36 = $campaign_row.data('campaign_id36')
    $.request("terminate_campaign", {"campaign_id36": campaign_id36,
                                     "link_id36": link_id36},
              null, true, "json", false);
}
