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

function close_menus() {
    $(".drop-choices.inuse").not(".active")
        .removeClass("inuse");
    $(".drop-choices.active").removeClass("active");
};

function hover_open_menu(menu) { };

function update_user(form) {
  try {
    var user = $(form).find("input[name=user]").val();
    form.action += "/" + user;
  } catch (e) {
    // ignore
  }

  return true;
}

function post_user(form, where) {
  var user = $(form).find("input[name=user]").val();

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

function get_form_fields(form, fields) {
    fields = fields || {};
    /* consolidate the form's inputs for submission */
    $(form).find("select, input, textarea").not(".gray").each(function() {
            if (($(this).attr("type") != "radio" &&
                 $(this).attr("type") != "checkbox") ||
                $(this).attr("checked"))
                fields[$(this).attr("name")] = $(this).attr("value");
        });
    if (fields.id == null) {
        fields.id = $(form).attr("id") ? ("#" + $(form).attr("id")) : "";
    }
    return fields;
};

function simple_post_form(form, where, fields, block) {
    $.request(where, get_form_fields(form, fields), null, block);
    return false;
};


function emptyInput(elem, msg) {
    if (! $(elem).attr("value") || $(elem).attr("value") == msg ) 
        $(elem).addClass("gray").attr("value", msg).attr("rows", 3);
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
        .find("form input[name=reason]").attr("value", (reason || ""));
    
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

function change_state(elem, op, callback) {
    var form = $(elem).parents("form");
    /* look to see if the form has an id specified */
    var id = form.find("input[name=id]");
    if (id.length) 
        id = id.attr("value");
    else /* fallback on the parent thing */
        id = $(elem).thing_id();

    simple_post_form(form, op, {id: id});
    /* call the callback first before we mangle anything */
    if (callback) callback(form, op);
    form.html(form.attr("executed").value);
    return false;
};

function save_thing(elem) {
    $(elem).thing().addClass("saved");
}

function unsave_thing(elem) {
    $(elem).thing().removeClass("saved");
}

function hide_thing(elem) {
    var thing = $(elem).thing();
    thing.hide();
    if(thing.hasClass("hidden"))
        thing.removeClass("hidden");
    else
        thing.addClass("hidden");
};

function toggle_label (elem, callback, cancelback) {
  $(elem).parent().find(".option").toggle();
  $(elem).onclick = function() {
    return(toggle_label(elem, cancelback, callback));
  }
  if (callback) callback(elem);
}

function toggle(elem, callback, cancelback) {
    var self = $(elem).parent().andSelf().filter(".option");
    var sibling = self.removeClass("active")
        .siblings().addClass("active").get(0);
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
    var title = $(form).find("#title").attr("value");
    if(title) 
        return reddit.status_msg.submitting;
    return reddit.status_msg.fetching;
};


function subscribe(reddit_name) {
    return function() { 
        $.request("subscribe", {sr: reddit_name, action: "sub"});
    };
};

function unsubscribe(reddit_name) {
    return function() { 
        $.request("subscribe", {sr: reddit_name, action: "unsub"});
    };
};

function friend(user_name, container_name, type) {
    return function() {
        $.request("friend", 
                  {name: user_name, container: container_name, type: type});
    }
};

function unfriend(user_name, container_name, type) {
    return function() {
        $.request("unfriend", 
                  {name: user_name, container: container_name, type: type});
    }
};

function show_media(obj) {
    obj = $.unsafe(obj);
    return function(elem) {
        var where = $(elem).thing().find(".embededmedia");
        if (where.length) 
            where.show().html(obj);
        else
            $(elem).new_thing_child('<div class="embededmedia">' + obj + '</div>');
    }
};

function cancelMedia(elem) {
    return cancelToggleForm(elem, ".embededmedia", ".media-button");
};

function share(elem) {
    $(elem).new_thing_child($(".sharelink:first").clone(true)
                            .attr("id", "sharelink_" + $(elem).thing_id()),
                             false);
};

function cancelShare(elem) {
    return cancelToggleForm(elem, ".sharelink", ".share-button");
};


/* Comment generation */
function helpon(elem) {
    $(elem).parents("form:first").children(".markhelp:first").show();
};
function helpoff(elem) {
    $(elem).parents("form:first").children(".markhelp:first").hide();
};


function chkcomment(form) {
    var entry = $(form).find("textarea");
    if( entry.hasClass("gray") || !entry.attr("value") ) {
        return false;
    } else if(form.replace.value) 
        return post_form(form, 'editcomment', null, null, true);
    else 
        return post_form(form, 'comment', null, null, true);
};

function comment_edit(elem) {
    return $(".commentreply:first").clone(true)
        .find("button[name=cancel]").show().end()
        .attr("id", "commentreply_" + $(elem).thing_id());
};

function reply(elem) {
    $(elem).new_thing_child(comment_edit(elem))
          .find('textarea:first').focus();
};

function editcomment(elem) {
    var comment = $(elem).thing();
    var thing_name = comment.thing_id();
    var edit = comment_edit(elem);
    var content = comment.find(".edit-body:first").html();
    content = decodeURIComponent(content.replace(/\+/g, " "));
    edit.prependTo(comment)
        .hide()
        .find("button[name=comment]").hide().end()
        .find("button[name=edit]").show().end()
        .find("textarea")
        .attr("value", content)
        .removeClass("gray")
    edit.attr("parent").value = thing_name;
    edit.attr("replace").value = 1;
    
    comment.children(".midcol, .entry").hide();
    edit.find("textarea:first").focus();
    edit.show();
};


function hidecomment(elem) {
    $(elem).thing().hide()
        .find(".noncollapsed:first, .midcol:first, .child:first").hide().end()
        .show().find(".entry:first .collapsed").show();
    return false;
};

function showcomment(elem) {
    var comment = $(elem).thing();
    comment.find(".entry:first .collapsed").hide().end()
        .find(".noncollapsed:first, .midcol:first, .child:first").show().end()
        .show();
    return false;
};

function cancelReply(elem) {
    var on_hide = function(form) {
        $.things($(form).attr("parent").value)
        .children(".midcol, .entry").show();
    };
    return cancelToggleForm(elem, ".commentreply", ".reply-button", on_hide);
};


function morechildren(form, link_id, children, depth) {
    $(form).html(reddit.status_msg.loading)
        .css("color", "red");
    var id = $(form).parents(".thing.morechildren:first").thing_id();
    $.request('morechildren', {link_id: link_id,
                children: children, depth: depth, id: id});
    return false;
};

/* stylesheet and CSS stuff */

function update_reddit_count(site) {
    if (!site || !reddit.logged) return;
    
    var decay_factor = .9; //precentage to keep
    var decay_period = 86400; //num of seconds between updates
    var num_recent = 10; //num of recent reddits to report
    var num_count = 100; //num of reddits to actually count
    
    var date_key = '_date';
    var cur_date = new Date();
    var count_cookie = 'reddit_counts';
    var recent_cookie = 'recent_reddits';
    var reddit_counts = $.cookie_read(count_cookie).data;
    
    //init the reddit_counts dict
    if (!$.defined(reddit_counts) ) {
        reddit_counts = {};
        reddit_counts[date_key] = cur_date.toString();
    }
    var last_reset = new Date(reddit_counts[date_key]);
    var decay = cur_date - last_reset > decay_period * 1000;

    //incrmenet the count on the current reddit
    reddit_counts[site] = $.with_default(reddit_counts[site], 0) + 1;

    //collect the reddit names (for sorting) and decay the view counts
    //if necessary
    var names = [];
    $.each(reddit_counts, function(sr_name, value) {
            if(sr_name != date_key) {
                if (decay && sr_name != site) {
                    //compute the new count val
                    var val = Math.floor(decay_factor * reddit_counts[sr_name]);
                    if (val > 0) 
                        reddit_counts[sr_name] = val;
                    else 
                        delete reddit_counts[sr_name];
                }
                if (reddit_counts[sr_name]) 
                    names.push(sr_name);
            }
        });

    //sort the names by the view counts
    names.sort(function(n1, n2) {
            return reddit_counts[n2] - reddit_counts[n1];
        });

    //update the last decay date
    if (decay) reddit_counts[date_key] = cur_date.toString();

    //build the list of names to report as "recent"
    var recent_reddits = "";
    for (var i = 0; i < names.length; i++) {
        var sr_name = names[i];
        if (i < num_recent) {
            recent_reddits += names[i] + ',';
        } else if (i >= num_count && sr_name != site) {
            delete reddit_counts[sr_name];
        }
    }

    //set the two cookies: one for the counts, one for the final
    //recent list
    $.cookie_write({name: count_cookie, data: reddit_counts});
    if (recent_reddits) 
        $.cookie_write({name: recent_cookie, data: recent_reddits});
};


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

    $(thing).filter(".promotedlink").bind("onshow", function() {
            var id = $(this).thing_id();
            if($.inArray(id, reddit.tofetch) != -1) {
                $.request("onload", {ids: reddit.tofetch.join(",")});
                reddit.tofetch = [];
            }
            var tracker = reddit.trackers[id]; 
            if($.defined(tracker)) {
                $(this).find("a.title").attr("href", tracker.click).end()
                    .find("img.promote-pixel")
                    .attr("src", tracker.show);
                delete reddit.trackers[id];
            }
        })
        /* pre-trigger new event if already shown */
        .filter(":visible").trigger("onshow");

    /* click on a title.. */
    $(thing).filter(".link, .linkcompressed")
        .find("a.title, a.comments").mousedown(function() {
            /* the site is either stored in the sr dict, or we are on
             * an sr and it is the current one */
            var sr = reddit.sr[$(this).thing_id()] || reddit.cur_site;
            update_reddit_count(sr);
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
                        {links: [current.what],
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

function populate_click_gadget() {
    /* if we can find the click-gadget, populate it */
    if($('.click-gadget').length) {
        var clicked = clicked_items();

        if(clicked && clicked.length) {
            clicked = $.uniq(clicked, 5);
            clicked.sort();

            $.request('gadget/click/' + clicked.join(','), undefined, undefined, undefined, true);
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
        var url = $(form).find('input[type=text]').attr('value');
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

/* The ready method */
$(function() {
        /* set function to be called on thing creation/replacement,
         * and call it on all things currently rendered in the
         * page. */
        $("body").set_thing_init(updateEventHandlers);
        
        /* Set up gray inputs and textareas to clear on focus */
        $("textarea.gray, input.gray")
            .focus( function() {
                    $(this).attr("rows", 7)
                        .filter(".gray").removeClass("gray").attr("value", "")
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
        
        /* Count the rendering of this reddit */
        if(reddit.cur_site)  
           update_reddit_count(reddit.cur_site);

        /* visually mark the last-clicked entry */
        last_click();


    });

