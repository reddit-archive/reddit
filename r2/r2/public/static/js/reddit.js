function open_menu(menu) {
    $(menu).siblings(".drop-choices").not(".inuse")
        .css("top", menu.offsetHeight + 'px')
                .each(function(){
                        $(this).css("left", $(menu).position().left + "px")
                            .css("top", ($(menu).height()+
                                         $(menu).position().top) + "px");
                    })
        .addClass("active inuse");
};

function close_menus(event) {
    $(".drop-choices.inuse").not(".active")
        .removeClass("inuse");
    $(".drop-choices.active").removeClass("active");

    /* hide the search expando if the user clicks elsewhere on the page */ 
    if ($(event.target).closest("#search").length == 0) {
        $("#moresearchinfo").slideUp();

        if ($("#searchexpando").length == 1) {
            $("#searchexpando").slideUp(function() {
                $("#search_showmore").parent().show();
            });
        } else {
            $("#search_showmore").parent().show();
        }
    }
};

function hover_open_menu(menu) { };

function update_user(form) {
  try {
    var user = $(form).find('input[name="user"]').val();
    form.action += "/" + user;
  } catch (e) {
    // ignore
  }

  return true;
}

function post_user(form, where) {
  var user = $(form).find('input[name="user"]').val();

  if (user == null) {
    return post_form (form, where);
  } else {
    return post_form (form, where + '/' + user);
  }
}

function post_form(form, where, statusfunc, nametransformfunc, block) {
    try {
        if(statusfunc == null)
            statusfunc = function(x) { 
                return reddit.status_msg.submitting; 
            };
        /* set the submitted state */
        $(form).find(".error").not(".status").hide();
        $(form).find(".status").html(statusfunc(form)).show();
        return simple_post_form(form, where, {}, block);
    } catch(e) {
        return false;
    }
};

function get_form_fields(form, fields, filter_func) {
    fields = fields || {};
    if (!filter_func)
        filter_func = function(x) { return true; };
    /* consolidate the form's inputs for submission */
    $(form).find("select, input, textarea").not(".gray, :disabled").each(function() {
            var type = $(this).attr("type");
            if (filter_func(this) && 
                ( (type != "radio" && type != "checkbox") || 
                  $(this).is(":checked")) )
                fields[$(this).attr("name")] = $(this).val();
        });
    if (fields.id == null) {
        fields.id = $(form).attr("id") ? ("#" + $(form).attr("id")) : "";
    }
    return fields;
};

function form_error(form) {
    return function(r) {
        $(form).find(".status")
            .html("an error occurred while posting " + 
                  "(status: " + r.status + ")").end();
    }
}

function simple_post_form(form, where, fields, block) {
    $.request(where, get_form_fields(form, fields), null, block, 
              "json", false, form_error(form));
    return false;
};

function post_pseudo_form(form, where, block) {
    var filter_func = function(x) {
        var parent = $(x).parents("form:first");
        return (parent.length == 0 || parent.get(0) == $(form).get(0))
    };
    $(form).find(".error").not(".status").hide();
    $(form).find(".status").html(reddit.status_msg.submitting).show();
    $.request(where, get_form_fields(form, {}, filter_func), null, block,
              "json", false, form_error(form));
    return false;
}

function emptyInput(elem, msg) {
    if (! $(elem).val() || $(elem).val() == msg ) 
        $(elem).addClass("gray").val(msg).attr("rows", 3);
    else
        $(elem).focus(function(){});
};


function showlang() {
    $(".lang-popup:first").show();
    return false;
};

function showcover(warning, reason) {
    $.request("new_captcha");
    if (warning) 
        $("#cover_disclaim, #cover_msg").show();
    else
        $("#cover_disclaim, #cover_msg").hide();
    $(".login-popup:first").show()
        .find('form input[name="reason"]').val(reason || "");
    return false;
};

function hidecover(where) {
    $(where).parents(".cover-overlay").hide();
    return false;
};

/* table handling */

function deleteRow(elem) {
    $(elem).delete_table_row();
};



/* general things */

function change_state(elem, op, callback, keep) {
    var form = $(elem).parents("form");
    /* look to see if the form has an id specified */
    var id = form.find('input[name="id"]');
    if (id.length) 
        id = id.val();
    else /* fallback on the parent thing */
        id = $(elem).thing_id();

    simple_post_form(form, op, {id: id});
    /* call the callback first before we mangle anything */
    if (callback) {
        callback(form.length ? form : elem, op);
    }
    if(!$.defined(keep)) {
        form.html(form.find('[name="executed"]').val());
    }
    return false;
};

function unread_thing(elem) {
    var t = $(elem);
    if (!t.hasClass("thing")) {
        t = t.thing();
    }
    $(t).addClass("new unread");
}

function read_thing(elem) {
    var t = $(elem);
    if (!t.hasClass("thing")) {
        t = t.thing();
    }
    if($(t).hasClass("new")) {
        $(t).removeClass("new");
    } else {
        $(t).removeClass("unread");
    }
    $.request("read_message", {"id": $(t).thing_id()});
}

function save_thing(elem) {
    $(elem).thing().addClass("saved");
}

function unsave_thing(elem) {
    $(elem).thing().removeClass("saved");
}

function click_thing(elem) {
    var t = $(elem);
    if (!t.hasClass("thing")) {
        t = t.thing();
    }
    if (t.hasClass("message") && t.hasClass("recipient")) {
        if (t.hasClass("unread")) {
            t.removeClass("unread");
        } else if ( t.hasClass("new")) {
            read_thing(elem);
        }
    }
}

function hide_thing(elem) {
    $(elem).thing().fadeOut(function(elem) { 
            $(this).toggleClass("hidden") });
};

function toggle_label (elem, callback, cancelback) {
  $(elem).parent().find(".option").toggle();
  $(elem)[0].onclick = function() {
    return(toggle_label(elem, cancelback, callback));
  }
  if (callback) callback(elem);
}

function toggle(elem, callback, cancelback) {
    var self = $(elem).parent().andSelf().filter(".option");
    var sibling = self.removeClass("active")
        .siblings().addClass("active").get(0); 

    /*
    var self = $(elem).siblings().andSelf();
    var sibling = self.filter(":hidden").debug();
    self = self.filter(":visible").removeClass("active");
    sibling = sibling.addClass("active").get(0);
    */

    if(cancelback && !sibling.onclick) {
        sibling.onclick = function() {
            return toggle(sibling, cancelback, callback);
        }
    }
    if(callback) callback(elem);
    return false;
};

function cancelToggleForm(elem, form_class, button_class, on_hide) {
    /* if there is a toggle button that triggered this, toggle it if
     * it is not already active.*/
    if(button_class && $(elem).filter("button").length) {
        var sel = $(elem).thing().find(button_class)
            .children(":visible").filter(":first");
        toggle(sel);
    }
    $(elem).thing().find(form_class)
        .each(function() {
                if(on_hide) on_hide($(this));
                $(this).hide().remove();
            });
    return false;
};

/* organic listing */

function get_organic(elem, next) {
    var listing = $(elem).parents(".organic-listing");
    var thing = listing.find(".thing:visible");
    if(listing.find(":animated").length) 
        return false;
    
    /* note we are looking for .thing.link while empty entries (if the
     * loader isn't working) will be .thing.stub -> no visual
     * glitches */
    var next_thing;
    if (next) {
        next_thing = thing.nextAll(".thing:not(.stub)").filter(":first");
        if (next_thing.length == 0)
            next_thing = thing.siblings(".thing:not(.stub)").filter(":first");
    }
    else {
        next_thing = thing.prevAll(".thing:not(.stub)").filter(":first");
        if (next_thing.length == 0)
            next_thing = thing.siblings(".thing:not(.stub)").filter(":last");
    }    
    thing.fadeOut('fast', function() {
            if(next_thing.length)
                next_thing.fadeIn('fast', function() {

                        /* make sure the next n are loaded */
                        var n = 5;
                        var t = thing;
                        var to_fetch = [];
                        for(var i = 0; i < 2*n; i++) {
                            t = (next) ? t.nextAll(".thing:first") : 
                                t.prevAll(".thing:first"); 
                            if(t.length == 0) 
                                t = t.end().parent()
                                    .children( (next) ? ".thing:first" : 
                                               ".thing:last");
                            if(t.filter(".stub").length)
                                to_fetch.push(t.thing_id());
                            if(i >= n && to_fetch.length == 0)
                                break;
                        }
                        if(to_fetch.length) {
                            $.request("fetch_links",  
                                      {links: to_fetch.join(','),
                                              listing: listing.attr("id")}); 
                        }
                    })
                    });
};

/* links */

function linkstatus(form) {
    return reddit.status_msg.submitting;
};


function subscribe(reddit_name) {
    return function() { 
        if (!reddit.logged)  {
            showcover();
        } else {
            $.things(reddit_name).find(".entry").addClass("likes");
            $.request("subscribe", {sr: reddit_name, action: "sub"});
        }
    };
};

function unsubscribe(reddit_name) {
    return function() { 
        if (!reddit.logged)  {
            showcover();
        } else {
            $.things(reddit_name).find(".entry").removeClass("likes");
            $.request("subscribe", {sr: reddit_name, action: "unsub"});
        }
    };
};

function friend(user_name, container_name, type) {
    return function() {
        if (!reddit.logged)  {
            showcover();
        }
        else {
            encoded = encodeURIComponent(reddit.referer);
            $.request("friend?note=" + encoded,
                      {name: user_name, container: container_name, type: type});
        }
    }
};

function unfriend(user_name, container_name, type) {
    return function() {
        $.request("unfriend",
                  {name: user_name, container: container_name, type: type});
    }
};

function share(elem) {
    $.request("new_captcha");
    $(elem).new_thing_child($(".sharelink:first").clone(true)
                            .attr("id", "sharelink_" + $(elem).thing_id()),
                             false);
    $.request("new_captcha");
};

function cancelShare(elem) {
    return cancelToggleForm(elem, ".sharelink", ".share-button");
};

function reject_promo(elem) {
    $(elem).thing().find(".rejection-form").show().find("textare").focus();
}

function cancel_reject_promo(elem) {  
    $(elem).thing().find(".rejection-form").hide();
}

function complete_reject_promo(elem) {
    $(elem).thing().removeClass("accepted").addClass("rejected")
        .find(".reject_promo").remove();
}

/* Comment generation */
function helpon(elem) {
    $(elem).parents(".usertext-edit:first").children(".markhelp:first").show();
};
function helpoff(elem) {
    $(elem).parents(".usertext-edit:first").children(".markhelp:first").hide();
};

function show_all_messages(elem) {
    var m = $(elem).parents(".message");
    var ids = [];
    m.find(".entry .collapsed").hide().end()
        .find(".noncollapsed, .midcol:first").filter(":hidden")
        .each(function() { 
                var t = $(this).show().thing_id(); 
                if(ids.indexOf(t) == -1) {
                    ids.push(t);
                }
            });
    if(ids.length) {
        $.request("uncollapse_message", {"id": ids.join(',')});
    }
    return false; 
}

function hide_all_messages(elem) {
    var m = $(elem).parents(".message");
    var ids = [];
    m.find(".entry .collapsed").show().end()
        .find(".noncollapsed, .midcol:first").filter(":visible")
        .each(function() { 
                var t = $(this).hide().thing_id(); 
                if(ids.indexOf(t) == -1) {
                    ids.push(t);
                }
            });
    if(ids.length) {
        $.request("collapse_message", {"id": ids.join(',')});
    }
    return false; 
}

function hidecomment(elem) {
    var t = $(elem).thing();
    t.hide()
        .find(".noncollapsed:first, .midcol:first").hide().end()
        .show().find(".entry:first .collapsed").show();
    if(t.hasClass("message")) {
        $.request("collapse_message", {"id": $(t).thing_id()});
    } else {
        t.find(".child:first").hide();
    }
    return false;
};

function showcomment(elem) {
    var t = $(elem).thing();
    t.find(".entry:first .collapsed").hide().end()
        .find(".noncollapsed:first, .midcol:first").show().end()
        .show();
    if(t.hasClass("message")) {
        $.request("uncollapse_message", {"id": $(t).thing_id()});
    } else {
        t.find(".child:first").show();
    }
    return false;
};

function morechildren(form, link_id, children, depth, pv_hex) {
    $(form).html(reddit.status_msg.loading)
        .css("color", "red");
    var id = $(form).parents(".thing.morechildren:first").thing_id();
    $.request('morechildren', {link_id: link_id,
              children: children, depth: depth, id: id, pv_hex: pv_hex});
    return false;
};

function moremessages(elem) {
    $(elem).html(reddit.status_msg.loading).css("color", "red");
    $.request("moremessages", {parent_id: $(elem).thing_id()});
    return false;
}

/* stylesheet and CSS stuff */

function add_thing_to_cookie(thing, cookie_name) {
    var id = $(thing).thing_id();

    if(id && id.length) {
        return add_thing_id_to_cookie(id, cookie_name);
    }
}

function add_thing_id_to_cookie(id, cookie_name) {
    var cookie = $.cookie_read(cookie_name);
    if(!cookie.data) {
        cookie.data = "";
    }

    /* avoid adding consecutive duplicates */
    if(cookie.data.substring(0, id.length) == id) {
        return;
    }

    cookie.data = id + ',' + cookie.data;

    if(cookie.data.length > 1000) {
        var fullnames = cookie.data.split(',');
        fullnames = $.uniq(fullnames, 20);
        cookie.data = fullnames.join(',');
    }

    $.cookie_write(cookie);
};

function clicked_items() {
    var cookie = $.cookie_read('recentclicks2');
    if(cookie && cookie.data) {
        var fullnames = cookie.data.split(",");
        /* don't return empty ones */
        for(var i=fullnames.length-1; i >= 0; i--) {
            if(!fullnames[i] || !fullnames[i].length) {
                fullnames.splice(i,1);
            }
        }
        return fullnames;
    } else {
        return [];
    }
}

function clear_clicked_items() {
    var cookie = $.cookie_read('recentclicks2');
    cookie.data = '';
    $.cookie_write(cookie);
    $('.gadget').remove();
}

function updateEventHandlers(thing) {
    /* this function serves as a default callback every time a new
     * Thing is inserted into the DOM.  It serves to rewrite a Thing's
     * event handlers depending on context (as in the case of an
     * organic listing) and to set the click behavior on links. */
    thing = $(thing);
    var listing = thing.parent();

    /* click on a title.. */
    $(thing).filter(".link")
        .find("a.title, a.comments").mousedown(function() {
            /* mark as clicked */
            $(this).addClass("click");
            /* set the click cookie. */
            add_thing_to_cookie(this, "recentclicks2");
            /* remember this as the last thing clicked */
            var wasorganic = $(this).parents('.organic-listing').length > 0;
            last_click(thing, wasorganic);
        });

    if (listing.filter(".organic-listing").length) {
        thing.find(".hide-button a, .del-button a.yes, .report-button a.yes")
            .each(function() { $(this).get(0).onclick = null });
        thing.find(".hide-button a")
           .click(function() {
                   var a = $(this).get(0);
                   change_state(a, 'hide', 
                                function() { get_organic(a, 1); });
                });
        thing.find(".del-button a.yes")
            .click(function() {
                    var a = $(this).get(0);
                    change_state(a, 'del', function() { get_organic(a, 1); });
                });
        thing.find(".report-button a.yes")
            .click(function() {
                    var a = $(this).get(0);
                    change_state(a, 'report', 
                                 function() { get_organic(a, 1); });
                    }); 

        /*thing.find(".arrow.down")
            .one("click", function() {
                    var a = $(this).get(0);
                    get_organic($(this).get(0), 1);
                    }); */
    }
};

function last_click(thing, organic) {
  /* called with zero arguments, marks the last-clicked item on this
     page (to which the user probably clicked the 'back' button in
     their browser). Otherwise sets the last-clicked item to the
     arguments passed */
  var cookie = "last_thing";
  if(thing) {
    var data = {href: window.location.href, 
                what: $(thing).thing_id(),
                organic: organic};
    $.cookie_write({name: cookie, data: data});
  } else {
    var current = $.cookie_read(cookie).data;
    if(current && current.href == window.location.href) {
      /* if they got there organically, make sure that it's in the
         organic box */
      var olisting = $('.organic-listing');
      if(current.organic && olisting.length == 1) {
        if(olisting.find('.thing:visible').thing_id() == current.what) {
          /* if it's available in the organic box, *and* it's the one
             that's already shown, do nothing */

        } else {
          var thing = olisting.things(current.what);

          if(thing.length > 0 && !thing.hasClass('stub')) {
            /* if it's available in the organic box and not a stub,
               switch index to it */
            olisting.find('.thing:visible').hide();
            thing.show();
          } else {
              /* either it's available in the organic box, but the
                 data there is a stub, or it's not available at
                 all. either way, we need a server round-trip */

              /* remove the stub if it's there */
              thing.remove();

              /* add a new stub */
              olisting.find('.thing:visible')
                  .before('<div class="thing id-'+current.what+' stub" style="display: none"></div');
              
              /* and ask the server to fill it in */
              $.request('fetch_links',
                        {links: current.what,
                                show: current.what,
                                listing: olisting.attr('id')});
          }
        }
      }
      
      /* mark it in the list */
      $.things(current.what).addClass("last-clicked");

      /* and wipe the cookie */
      $.cookie_write({name: cookie, data: ""});
    }
  }
};

function login(elem) {
    if(cnameframe)
        return true;

    return post_user(this, "login");
};

function register(elem) {
    if(cnameframe)
        return true;
    return post_user(this, "register");
};

/***submit stuff***/
function fetch_title() {
    var url_field = $("#url-field");
    var error = url_field.find(".NO_URL");
    var status = url_field.find(".title-status");
    var url = $("#url").val();
    if (url) {
        status.show().text(reddit.status_msg.loading);
        error.hide();
        $.request("fetch_title", {url: url});
    }
    else {
        status.hide();
        error.show().text("a url is required");
    }
}

/**** sr completing ****/
function sr_cache() {
    if (!$.defined(reddit.sr_cache)) {
        reddit.sr_cache = new Array();
    }
    return reddit.sr_cache;
}

function highlight_reddit(item) {
    $("#sr-drop-down").children('.sr-selected').removeClass('sr-selected');
    if (item) {
        $(item).addClass('sr-selected');
    }
}

function update_dropdown(sr_names) {
    var drop_down = $("#sr-drop-down");
    if (!sr_names.length) {
        drop_down.hide();
        return;
    }

    var first_row = drop_down.children(":first");
    first_row.removeClass('sr-selected');
    drop_down.children().remove();

    $.each(sr_names, function(i) {
            if (i > 10) return;
            var name = sr_names[i];
            var new_row = first_row.clone();
            new_row.text(name);
            drop_down.append(new_row);
        });


    var height = $("#sr-autocomplete").outerHeight();
    drop_down.css('top', height);
    drop_down.show();
}

function sr_search(query) {
    query = query.toLowerCase();
    var cache = sr_cache();
    if (!cache[query]) {
        $.request('search_reddit_names', {query: query},
                  function (r) {
                      cache[query] = r['names'];
                      update_dropdown(r['names']);
                  });
    }
    else {
        update_dropdown(cache[query]);
    }
}

function sr_name_up(e) {
    var new_sr_name = $("#sr-autocomplete").val();
    var old_sr_name = window.old_sr_name || '';
    window.old_sr_name = new_sr_name;

    if (new_sr_name == '') {
        hide_sr_name_list();
    }
    else if (e.keyCode == 38 || e.keyCode == 40 || e.keyCode == 9) {
    }
    else if (e.keyCode == 27 && reddit.orig_sr) {
        $("#sr-autocomplete").val(reddit.orig_sr);
        hide_sr_name_list();
    }
    else if (new_sr_name != old_sr_name) {
        reddit.orig_sr = new_sr_name;
        sr_search($("#sr-autocomplete").val());
    }
}

function sr_name_down(e) {
    var input = $("#sr-autocomplete");
    
    if (e.keyCode == 38 || e.keyCode == 40) {
        var dir = e.keyCode == 38 && 'up' || 'down';

        var cur_row = $("#sr-drop-down .sr-selected:first");
        var first_row = $("#sr-drop-down .sr-name-row:first");
        var last_row = $("#sr-drop-down .sr-name-row:last");

        var new_row = null;
        if (dir == 'down') {
            if (!cur_row.length) new_row = first_row;
            else if (cur_row.get(0) == last_row.get(0)) new_row = null;
            else new_row = cur_row.next(':first');
        }
        else {
            if (!cur_row.length) new_row = last_row;
            else if (cur_row.get(0) == first_row.get(0)) new_row = null;
            else new_row = cur_row.prev(':first');
        }
        highlight_reddit(new_row);
        if (new_row) {
            input.val($.trim(new_row.text()));
        }
        else {
            input.val(reddit.orig_sr);
        }
        return false;
    }
    else if (e.keyCode == 13) {
        hide_sr_name_list();
        input.parents("form").submit();
        return false;
    }   
}

function hide_sr_name_list(e) {
    $("#sr-drop-down").hide();
}

function sr_dropdown_mdown(row) {
    reddit.sr_mouse_row = row; //global
    return false;
}

function sr_dropdown_mup(row) {
    if (reddit.sr_mouse_row == row) {
        var name = $(row).text();
        $("#sr-autocomplete").val(name);
        $("#sr-drop-down").hide();
    }
}

function set_sr_name(link) {
    var name = $(link).text();
    $("#sr-autocomplete").trigger('focus').val(name);
}

/*** tabbed pane stuff ***/
function select_form_tab(elem, to_show, to_hide) {
    //change the menu    
    var link_parent = $(elem).parent();
    link_parent
        .addClass('selected')
        .siblings().removeClass('selected');
    
    //swap content and enable/disable form elements
    var content = link_parent.parent('ul').next('.formtabs-content');
    content.find(to_show)
        .show()
        .find(":input").removeAttr("disabled").end();
    content.find(to_hide)
        .hide()
        .find(":input").attr("disabled", true);
}

/**** expando stuff ********/
function expando_cache() {
    if (!$.defined(reddit.thing_child_cache)) {
        reddit.thing_child_cache = new Array();
    }
    return reddit.thing_child_cache;
}

function expando_child(elem) {
    var child_cache = expando_cache();
    var thing = $(elem).thing();

    //swap button
    var button = thing.find(".expando-button");
    button
        .addClass("expanded")
        .removeClass("collapsed")
        .get(0).onclick = function() {unexpando_child(elem)};

    //load content
    var expando = thing.find(".expando");
    var key = thing.thing_id() + "_cache";
    if (!child_cache[key]) {
        $.request("expando",
                  {"link_id":thing.thing_id()},
                  function(r) {
                      child_cache[key] = r;
                      expando.html($.unsafe(r));
                  },
                  false, "html");
    }
    else {
        expando.html($.unsafe(child_cache[key]));
    }
    expando.show();
    return false;
}

function unexpando_child(elem) {
    var thing = $(elem).thing();
    var button = thing.find(".expando-button");
    button
        .addClass("collapsed")
        .removeClass("expanded")
        .get(0).onclick = function() {expando_child(elem)};

    thing.find(".expando").hide().empty();
}

/******* editting comments *********/
function show_edit_usertext(form) {
    var edit = form.find(".usertext-edit");
    var body = form.find(".usertext-body");
    var textarea = edit.find('div > textarea');

    //max of the height of the content or the min values from the css.
    var body_width = Math.max(body.children(".md").width(), 500);
    var body_height = Math.max(body.children(".md").height(), 100);

    //we need to show the textbox first so it has dimensions
    body.hide();
    edit.show();

    //restore original (?) css width/height. I can't explain why, but
    //this is important.
    textarea.css('width', '');
    textarea.css('height', '');

    //if there would be scroll bars, expand the textarea to the size
    //of the rendered body text
    if (textarea.get(0).scrollHeight > textarea.height()) {
        var new_width = Math.max(body_width - 5, textarea.width());
        textarea.width(new_width);
        edit.width(new_width);

        var new_height = Math.max(body_height, textarea.height());
        textarea.height(new_height);
    }

    form
        .find(".cancel, .save").show().end()
        .find(".help-toggle").show().end();

    textarea.focus();
}

function hide_edit_usertext(form) {
    form
        .find(".usertext-edit").hide().end()
        .find(".usertext-body").show().end()
        .find(".cancel, .save").hide().end()
        .find(".help-toggle").hide().end()
        .find(".markhelp").hide().end()
}

function comment_reply_for_elem(elem) {
    elem = $(elem);
    var thing = elem.thing();
    var thing_id = elem.thing_id();
    //try to find a previous form
    var form = thing.find(".child .usertext:first");
    if (!form.length || form.parent().thing_id() != thing.thing_id()) {
        form = $(".usertext.cloneable:first").clone(true);
        elem.new_thing_child(form);
        form.prop("thing_id").value = thing_id;
        form.attr("id", "commentreply_" + thing_id);
        form.find(".error").hide();
    }
    return form;
}

function edit_usertext(elem) {
    var t = $(elem).thing();
    t.find(".edit-usertext:first").parent("li").andSelf().hide();
    show_edit_usertext(t.find(".usertext:first"));
}

function cancel_usertext(elem) {
    var t = $(elem).thing().debug();
    t.find(".edit-usertext:first").parent("li").andSelf().show(); 
    hide_edit_usertext(t.find(".usertext:first"));
}

function save_usertext(elem) {
    var t = $(elem).thing();
    t.find(".edit-usertext:first").parent("li").andSelf().show(); 
}

function reply(elem) {
    var form = comment_reply_for_elem(elem);
    //show the right buttons
    show_edit_usertext(form);
    //re-show the whole form if required
    form.show();
    //update the cancel button to call the toggle button's click
    form.find(".cancel").get(0).onclick = function() {form.hide()};
    return false; 
}

function toggle_distinguish_span(elem) {
  var form = $(elem).parents("form")[0];
  $(form).children().toggle();
}

function set_distinguish(elem, value) {
  change_state(elem, "distinguish/" + value);
  $(elem).children().toggle();
}

function populate_click_gadget() {
    /* if we can find the click-gadget, populate it */
    if($('.click-gadget').length) {
        var clicked = clicked_items();

        if(clicked && clicked.length) {
            clicked = $.uniq(clicked, 5);
            clicked.sort();

            $.request('gadget/click/' + clicked.join(','), undefined, undefined,
                      undefined, "json", true);
        }
    }
}

var toolbar_p = function(expanded_size, collapsed_size) {
    /* namespace for functions related to the reddit toolbar frame */

    this.toggle_linktitle = function(s) {
        $('.title, .submit, .url, .linkicon').toggle();
        if($(s).is('.pushed-button')) {
            $(s).parents('.middle-side').removeClass('clickable');
        } else {
            $(s).parents('.middle-side').addClass('clickable');
            $('.url').children('form').children('input').focus().select();
        }
        return this.toggle_pushed(s);
    };

    this.toggle_pushed = function(s) {
        s = $(s);
        if(s.is('.pushed-button')) {
            s.removeClass('pushed-button').addClass('popped-button');
        } else {
            s.removeClass('popped-button').addClass('pushed-button');
        }
        return false;
    };

    this.push_button = function(s) {
        $(s).removeClass("popped-button").addClass("pushed-button");
    };

    this.pop_button = function(s) {
        $(s).removeClass("pushed-button").addClass("popped-button");
    };
    
    this.serendipity = function() {
        this.push_button('.serendipity');
        return true;
    };
    
    this.show_panel = function() {
        parent.inner_toolbar.document.body.cols = expanded_size;
    };
        
    this.hide_panel = function() {
        parent.inner_toolbar.document.body.cols = collapsed_size;
    };
        
    this.resize_toolbar = function() {
        var height = $("body").height();
        parent.document.body.rows = height + "px, 100%";
    };
        
    this.login_msg = function() {
        $(".toolbar-status-bar").show();
        $(".login-arrow").show();
        this.resize_toolbar();
        return false;
    };
        
    this.top_window = function() {
        var w = window;
        while(w != w.parent) {
            w = w.parent;
        }
        return w.parent;
    };
        
    var pop_obj = null;
    this.panel_loadurl = function(url) {
        try {
            var cur = window.parent.inner_toolbar.reddit_panel.location;
            if (cur == url) {
                return false;
            } else {
                if (pop_obj != null) {
                    this.pop_button(pop_obj);
                    pop_obj = null;
                }
                return true;
            }
        } catch (e) {
            return true;
        }
    };
        
    var comments_on = 0;
    this.comments_pushed = function(ctl) {
        comments_on = ! comments_on;
        
        if (comments_on) {
            this.push_button(ctl);
            this.show_panel();
        } else {
            this.pop_button(ctl);
            this.hide_panel();
        }
    };
    
    this.gourl = function(form, base_url) {
        var url = $(form).find('input[type="text"]').val();
        var newurl = base_url + escape(url);
        
        this.top_window().location.href = newurl;
        
        return false;
    };

    this.pref_commentspanel_hide = function() {
        $.request('tb_commentspanel_hide');
    };
    this.pref_commentspanel_show = function() {
        $.request('tb_commentspanel_show');
    };
};

function clear_all_langs(elem) {
    $(elem).parents("td").find('input[type="checkbox"]').prop("checked", false);
}

function check_some_langs(elem) {
    $(elem).parents("td").find("#some-langs").prop("checked", true);
}

function fetch_parent(elem, parent_permalink, parent_id) {
    $(elem).css("color", "red").html(reddit.status_msg.loading);
    var thing = $(elem).thing();
    var parentdiv = thing.find(".uncollapsed .parent");
    if (parentdiv.length == 0) {
        var parent = '';
        $.getJSON(parent_permalink, function(response) {
                $.each(response, function() {
                        if (this && this.data.children) {
                            $.each(this.data.children, function() {
                                    if(this.data.name == parent_id) {
                                        parent= this.data.body_html; 
                                    }
                                });
                        }
                    });
                if(parent) {
                    /* make a parent div for the contents of the fetch */
                    thing.find(".noncollapsed .md")
                        .before('<div class="parent rounded">' +
                                $.unsafe(parent) +
                                '</div>'); 
                }
                $(elem).parent("li").andSelf().remove();
            });
    }
    return false;
}

function big_mod_action(elem, dir) {
   if ( ! elem.hasClass("pressed")) {
      elem.addClass("pressed");

      var thing_id = elem.thing_id();

      d = {
         id: thing_id
      };

      if (dir == -1) {
        $.request("remove", d, null, true);
        elem.siblings(".removed").show();
        elem.siblings(".approved").hide();
      } else if (dir == 1) {
        $.request("approve", d, null, true);
        elem.siblings(".removed").hide();
        elem.siblings(".approved").show();
      }
   }
   elem.siblings(".pretty-button").removeClass("pressed");
   return false;
}

function juryvote(elem, dir) {
   var thing_id = elem.thing_id();

   if (elem.hasClass("pressed")) {
      dir = 0;
   }

   elem.toggleClass("pressed");
   elem.siblings(".pretty-button").removeClass("pressed");

   d = {
         id: thing_id,
         dir: dir
       };
   $.request("juryvote", d, null, true);
   elem.siblings(".thanks-for-voting").show();
   return false;
}

/* The ready method */
$(function() {
        $("body").click(close_menus);

        /* set function to be called on thing creation/replacement,
         * and call it on all things currently rendered in the
         * page. */
        $("body").set_thing_init(updateEventHandlers);

        /* Fall back to the old ".gray" system if placeholder isn't supported
         * by this browser */
        if (!('placeholder' in document.createElement('input'))) {
            $("textarea[placeholder], input[placeholder]")
                .addClass("gray")
                .each(function() {
                    var element = $(this);
                    var placeholder_text = element.attr('placeholder');
                    if (element.val() == "") {
                        element.val(placeholder_text);
                    }
                });
        }

        /* Set up gray inputs and textareas to clear on focus */
        $("textarea.gray, input.gray")
            .focus( function() {
                    $(this).attr("rows", 7)
                        .filter(".gray").removeClass("gray").val("")
                        });
        /* set cookies to be from this user if there is one */
        if (reddit.logged) {
            $.cookie_name_prefix(reddit.logged);
        }
        else {
            //populate_click_gadget();
        }
        /* set up the cookie domain */
        $.default_cookie_domain(reddit.cur_domain.split(':')[0]);
        
        /* visually mark the last-clicked entry */
        last_click();

        /* search form help expando */
        /* TODO: use focusin and focusout in jQuery 1.4 */
        $('#search input[name="q"]').focus(function () {
            $("#searchexpando").slideDown();
        });

        $("#search_showmore").click(function(event) {
            $("#search_showmore").parent().hide();
            $("#moresearchinfo").slideDown();
            event.preventDefault();
        });

        $("#moresearchinfo")
            .prepend('<a href="#" id="search_hidemore">[-]</a>')

        $("#search_hidemore").click(function(event) {
            $("#search_showmore").parent().show();
            $("#moresearchinfo").slideUp();
            event.preventDefault();
        });
        
        /* Select shortlink text on click */
        $("#shortlink-text").click(function() {
            $(this).select();
        });
    });

function show_friend(account_fullname) {
    var label = '<a class="friend" title="friend" href="/prefs/friends">F</a>';
    var ua = $(".author.id-" + account_fullname).addClass("friend")
        .next(".userattrs").each(function() {
                if (!$(this).html()) {
                    $(this).html(" [" + label + "]");
                } else if ($(this).find(".friend").length == 0) {
                    $(this).find("a:first").debug().before(label+',');
                }
            });
}

function show_unfriend(account_fullname) {
    var ua = $(".author.id-" + account_fullname).removeClass("friend")
        .next(".userattrs");
    ua.each(function() {
            $(this).find("a.friend").remove();
            if ($(this).find("a").length == 0) {
                $(this).html("");
            }
        });
}

function search_feedback(elem, approval) {
  f = $("form#search");
  var q    = f.find('input[name="q"]').val();
  var sort = f.find('input[name="sort"]').val();
  var t    = f.find('input[name="t"]').val();
  var d = {
    q: q,
    sort: sort,
    t: t,
    approval: approval
  };
  $.request("searchfeedback", d, null, true);
  elem.siblings(".pretty-button").removeClass("pressed");
  elem.siblings(".thanks").show();
  elem.addClass("pressed");
  return false;
}

function highlight_new_comments(period) {
  var i;
  for (i = 0 ; i <= 9; i++) {
    items = $(".comment-period-" + i);
    if (period >= 0 && i >= period) {
      items.addClass("new-comment");
    } else {
      items.removeClass("new-comment");
    }
  }
}

function save_href(link) {
  if (!link.attr("srcurl")){
    link.attr("srcurl", link.attr("href"));
  }
  return link;
}

function pure_domain(url) {
    var domain = url.match(/:\/\/([^/]+)/)
    if (domain) {
        domain = domain[1].replace(/^www\./, '');
    }
    return domain;
}

function parse_domain(url) {
    var domain = pure_domain(url);
    if (!domain) {
        /* Internal link? Get the SR name, if there is one */
        var reddit = url.match(/\/r\/([^/]+)/)
        if (reddit) {
            domain = "self." + reddit[1].toLowerCase();
        }
    }
    return domain;
}
