/* The reddit extension for jquery.  This file is intended to store
 * "utils" type function declarations and to add functionality to "$"
 * or "jquery" lookups. See 
 *   http://docs.jquery.com/Plugins/Authoring 
 * for the plug-in spec.
*/

(function($) {

/* utility functions */

$.log = function(message) {
    if (window.console) {
        if (window.console.debug)
            window.console.debug(message);
        else if (window.console.log)
            window.console.log(message);
    }
    else
        alert(message);
};

$.debug = function(message) {
    if ($.with_default(reddit.debug, false)) {
        return $.log(message);
    }
}
$.fn.debug = function() { 
    $.debug($(this));
    return $(this);
}

$.redirect = function(dest) {
    window.location = dest;
};

$.fn.redirect = function(dest) {
    /* for forms which are "posting" by ajax leading to a redirect */
    $(this).filter("form").find(".status").show().html("redirecting...");
    var target = $(this).attr('target');
    if(target == "_top") {
      var w = window;
      while(w != w.parent) {
        w = w.parent;
      }
      w.location = dest;
    } else {
      $.redirect(dest);
    }
    /* this should never happen, but for the sake of internal consistency */
    return $(this)
}

$.refresh = function() {
    window.location.reload(true);
};

$.defined = function(value) {
    return (typeof(value) != "undefined");
};

$.with_default = function(value, alt) {
    return $.defined(value) ? value : alt;
};

$.websafe = function(text) {
    if(typeof(text) == "string") {
        text = text.replace(/&/g, "&amp;")
            .replace(/"/g, '&quot;') /* " */
            .replace(/>/g, "&gt;").replace(/</g, "&lt;")
    }
    return (text || "");
};

$.unsafe = function(text) {
    /* inverts websafe filtering of reddit app. */
    if(typeof(text) == "string") {
        text = text.replace(/&quot;/g, '"')
            .replace(/&gt;/g, ">").replace(/&lt;/g, "<")
            .replace(/&amp;/g, "&");
    }
    return (text || "");
};

$.uniq = function(list, max) {
    /* $.unique only works on arrays of DOM elements */
    var ret = [];
    var seen = {};
    var num = max ? max : list.length;
    for(var i = 0; i < list.length && ret.length < num; i++) {
        if(!seen[list[i]]) {
            seen[list[i]] = true;
            ret.push(list[i]);
        }
    }
    return ret;
};

/* upgrade show and hide to trigger onshow/onhide events when fired. */
(function(show, hide) {
    $.fn.show = function(speed, callback) {
        $(this).trigger("onshow");
        return show.call(this, speed, callback);
    }
    $.fn.hide = function(speed, callback) {
        $(this).trigger("onhide");
        return hide.call(this, speed, callback);
    }
})($.fn.show, $.fn.hide);

/* customized requests (formerly redditRequest) */

var _ajax_locks = {};
function acquire_ajax_lock(op) {
    if(_ajax_locks[op]) {
        return false;
    }
    _ajax_locks[op] = true;
    return true;
};

function release_ajax_lock(op) {
    delete _ajax_locks[op];
};

function handleResponse(action) {
    return function(r) {
        if(r.jquery) {
            var objs = {};
            objs[0] = jQuery;
            $.map(r.jquery, function(q) {
                    var old_i = q[0], new_i = q[1], op = q[2], args = q[3];
                    if (typeof(args) == "string") {
                      args = $.unsafe(args);
                    } else { // assume array
                      for(var i = 0; args.length && i < args.length; i++)
                        args[i] = $.unsafe(args[i]);
                    }
                    if (op == "call") 
                        objs[new_i] = objs[old_i].apply(objs[old_i]._obj, args);
                    else if (op == "attr") {
                        objs[new_i] = objs[old_i][args];
                        if(objs[new_i])
                            objs[new_i]._obj = objs[old_i];
                        else {
                            $.debug("unrecognized");
                        }
                    } else if (op == "refresh") {
                        $.refresh();
                    } else {
                        $.debug("unrecognized");
                    }
                });
        }
    };
};

var api_loc = '/api/';
$.request = function(op, parameters, worker_in, block, type, 
                     get_only, errorhandler) {
    /* 
       Uniquitous reddit AJAX poster.  Automatically addes
       handleResponse(action) worker to deal with the API result.  The
       current subreddit (reddit.post_site), the user's modhash
       (reddit.modhash) and whether or not we are in a frame
       (reddit.cnameframe) are also automatically sent across.
     */
    var action = op;
    var worker = worker_in;

    if (rate_limit(op) || (window != window.top && !reddit.cnameframe && !reddit.external_frame))
        return;

    /* we have a lock if we are not blocking or if we have gotten a lock */
    var have_lock = !$.with_default(block, false) || acquire_ajax_lock(action);

    parameters = $.with_default(parameters, {});
    worker_in  = $.with_default(worker_in, handleResponse(action));
    type  = $.with_default(type, "json");
    if (typeof(worker_in) != 'function')
        worker_in  = handleResponse(action);
    var worker = function(r) {
        release_ajax_lock(action);
        return worker_in(r);
    };
    /* do the same for the error handler, and make sure to release the lock*/
    errorhandler_in = $.with_default(errorhandler, function() { });
    errorhandler = function(r) {
        release_ajax_lock(action);
        return errorhandler_in(r);
    };



    get_only = $.with_default(get_only, false);

    /* set the subreddit name if there is one */
    if (reddit.post_site) 
        parameters.r = reddit.post_site;

    /* flag whether or not we are on a cname */
    if (reddit.cnameframe) 
        parameters.cnameframe = 1;

    /* add the modhash if the user is logged in */
    if (reddit.logged) 
        parameters.uh = reddit.modhash;

    parameters.renderstyle = reddit.renderstyle;

    if(have_lock) {
        op = api_loc + op;
        /*if( document.location.host == reddit.ajax_domain ) 
            /* normal AJAX post */

        $.ajax({ type: (get_only) ? "GET" : "POST",
                    url: op, 
                    data: parameters, 
                    success: worker,
                    error: errorhandler,
                    dataType: type});
        /*else { /* cross domain it is... * /
            op = "http://" + reddit.ajax_domain + op + "?callback=?";
            $.getJSON(op, parameters, worker);
            } */
    }
};

var up_cls = "up";
var upmod_cls = "upmod";
var down_cls = "down";
var downmod_cls = "downmod";

rate_limit = function() {
    /* default rate-limit duration (in milliseconds) */
    var default_rate_limit = 333;
    /* rate limit on a per-action basis (also in ms, 0 = don't rate limit) */
    var rate_limits = {"vote": 333, "comment": 5000,
                       "ignore": 0, "ban": 0, "unban": 0,
                       "assignad": 0 };
    var last_dates = {};

    /* paranoia: copy global functions used to avoid tampering.  */
    var defined = $.defined;
    var with_default = $.with_default;
    var _Date = Date;

    return function(action) {
        var now = new _Date();
        var last_date = last_dates[action];
        var allowed_interval = with_default(rate_limits[action], 
                                            default_rate_limit);
        last_dates[action] = now;
        /* true = being rate limited */
        return (defined(last_date) && now - last_date < allowed_interval)
    };
}()


$.fn.vote = function(vh, callback, event, ui_only) {
    /* for vote to work, $(this) should be the clicked arrow */
    if (!reddit.logged) {
        showcover(true, 'vote_' + $(this).thing_id());
    }
    else if($(this).hasClass("arrow")) {
        var dir = ( $(this).hasClass(up_cls) ? 1 :
                    ( $(this).hasClass(down_cls) ? -1 : 0) );
        var things = $(this).all_things_by_id();
        /* find all arrows of things on the page */
        var arrows = things.children().not(".child").find('.arrow');

        /* set the new arrow states */
        var u_before = (dir == 1) ? up_cls : upmod_cls;
        var u_after  = (dir == 1) ? upmod_cls : up_cls;
        arrows.filter("."+u_before).removeClass(u_before).addClass(u_after);

        var d_before = (dir == -1) ? down_cls : downmod_cls;
        var d_after  = (dir == -1) ? downmod_cls : down_cls;
        arrows.filter("."+d_before).removeClass(d_before).addClass(d_after);

        /* let the user vote only if they are logged in */
        if(reddit.logged) {
            things.each(function() {
                    var entry =  $(this).find(".entry:first, .midcol:first");
                    if(dir > 0)
                        entry.addClass('likes')
                            .removeClass('dislikes unvoted');
                    else if(dir < 0)
                        entry.addClass('dislikes')
                            .removeClass('likes unvoted');
                    else
                        entry.addClass('unvoted')
                            .removeClass('likes dislikes');
                });
            if(!$.defined(ui_only)) {
                var thing_id = things.filter(":first").thing_id();
                /* IE6 hack */
                vh += event ? "" : ("-" + thing_id); 
                $.request("vote", {id: thing_id, dir : dir, vh : vh});
            }
        }
        /* execute any callbacks passed in.  */
        if(callback) 
            callback(things, dir);
    }
    if(event) {
        event.stopPropagation();
    }
};

$.fn.show_unvotable_message = function() {
  $(this).thing().find(".entry:first .unvotable-message").css("display", "inline-block");
};

$.fn.thing = function() {
    /* Returns the first thing that is a parent of the current element */
    return this.parents(".thing:first");
};

$.fn.all_things_by_id = function() {
    /* Returns the set of things that have the same ID as the current
     * element's thing (we make no guarantee about uniqueness of
     * things across multiple listings on the same page) */
    return this.thing().add( $.things(this.thing_id()) );
};

$.fn.thing_id = function(class_filter) {
    class_filter = $.with_default(class_filter, "thing");
    /* Returns the (reddit) ID of the current element's thing */
    var t = (this.hasClass("thing")) ? this : this.thing();
    if(class_filter != "thing") {
        t = t.find("." + class_filter + ":first");
    }
    if(t.length) {
        var id = $.grep(t.get(0).className.match(/\S+/g),
                        function(i) { return i.match(/^id-/); }); 
        return (id.length) ? id[0].slice(3, id[0].length) : "";
    }
    return "";
};

$.things = function() {
    /* 
     * accepts a list of thing_ids as the first argument and returns a
     * jquery object consisting of the union of all things on the page
     * that represent those things.
     */
    var sel = $.map(arguments, function(x) { return ".thing.id-" + x; })
       .join(", ");
    return $(sel);
};

$.fn.same_author = function() {
    var aid = $(this).thing_id("author");
    var ids = [];
    $(".author.id-" + aid).each(function() {
            ids.push(".thing.id-" + $(this).thing_id());
        });
    return $(ids.join(", "));
};

$.fn.things = function() {
    /* 
     * try to find all things that occur below a given selector, like:
     * $('.organic-listing').things('t3_12345')
     */
    var sel = $.map(arguments, function(x) { return ".thing.id-" + x; })
       .join(", ");
    return this.find(sel);
};

$.listing = function(name) {
    /* 
     * Given an element name (a sitetable ID or a thing ID, with
     * optional siteTable_ at the front), return or generate a listing
     * with the proper id for that name. 
     *
     * In the case of a thing ID, this siteTable will be the listing
     * in the child div of that thing's container.
     * 
     * In the case of a general ID, it will be the listing of that
     * name already present in the DOM.
     *
     * On failure, will return a JQuery object of zero length.
     */
    name = name || "";
    var sitetable = "siteTable";
    /* we'll add the hash specifier in later */
    if (name.slice(0, 1) == "#" || name.slice(0, 1) == ".")
        name = name.slice(1, name.length);

    /* lname should be the name of the actual listing (will always
     * start with sitetable) while name should be the element it is
     * named for (strip off sitetable if present) */
    var lname = name;
    if(name.slice(0, sitetable.length) != sitetable) 
        lname = sitetable + ( (name) ? ("_" + name): "");
    else 
        name = name.slice(sitetable.length + 1, name.length);

    var listing = $("#" + lname).filter(":first");
    /* did the $ lookup match anything? */
    if (listing.length == 0) {
        listing = $.things(name).find(".child")
            .append(document.createElement('div'))
            .children(":last")
            .addClass("sitetable")
            .attr("id", lname);
    }
    return listing;
};


var thing_init_func = function() { };
$.fn.set_thing_init = function(func) {
    thing_init_func = func;
    $(this).find(".thing:not(.stub)").each(function() { func(this) });
};


$.fn.new_thing_child = function(what, use_listing) {
    var id = this.thing_id();
    var where = (use_listing) ? $.listing(id) :
        this.thing().find(".child:first");
    
    var new_form;
    if (typeof(what) == "string") 
        new_form = where.prepend(what).children(":first");
    else 
        new_form = what.hide()
            .prependTo(where)
            .show()
            .find('input[name="parent"]').val(id).end();
    
    return (new_form).randomize_ids();
};

$.fn.randomize_ids = function() {
    var new_id = (Math.random() + "").split('.')[1]
    $(this).find("*[id]").each(function() {
            $(this).attr('id', $(this).attr("id") + new_id);
        }).end()
    .find("label").each(function() {
            $(this).attr('for', $(this).attr("for") + new_id);
        });
    return $(this);
}

$.fn.replace_things = function(things, keep_children, reveal, stubs) {
    /* Given the api-html structured things, insert them into the DOM
     * in such a way as to remove any elements with the same thing_id.
     * "keep_children" is a boolean to determine whether or not any
     * existing child divs should be retained on the new thing (in the
     * case of a comment tree, flags whether or not the new thing has
     * the thread present) while "reveal" determines whether or not to
     * animate the transition from old to new. */
    var midcol = $(".midcol:visible:first").css("width");
    var numcol = $(".rank:visible:first").css("width");
    var self = this;
    return $.map(things, function(thing) {
            var data = thing.data;
            var existing = $(self).things(data.id);
            if(stubs) 
                existing = existing.filter(".stub");
            if(existing.length == 0) {
                var parent = $.things(data.parent);
                if (parent.length) {
                    existing = $("<div></div>");
                    parent.find(".child:first").append(existing);
                }
            }
            existing.after($.unsafe(data.content));
            var new_thing = existing.next();
            if($.defined(midcol)) {
                new_thing.find(".midcol").css("width", midcol).end()
                    .find(".rank").css("width", midcol);
            }
            if(keep_children) {
                /* show the new thing */
                new_thing.show()
                    /* but hide its new content */
                    .children(".midcol, .entry").hide().end()
                    .children(".child:first")
                    /* slop over the children */ 
                    .html(existing.children(".child:first")
                          .remove().html())
                    .end();
                /* hide the old entry and show the new one */
                if(reveal) {
                    existing.hide();
                    new_thing.children(".midcol, .entry").show();
                }
                new_thing.find(".rank:first")
                    .html(existing.find(".rank:first").html());
            }

            /* hide and remove old. add in new */
            if(reveal) {
                existing.hide();
                if(keep_children) 
                    new_thing.children(".midcol, .entry")
                        .show();
                else 
                    new_thing.show();
                existing.remove();
            }
            else { 
                new_thing.hide();
                existing.remove();
             }

            /* lastly, set the event handlers for these new things */
            thing_init_func(new_thing);
            return new_thing;
        });
    
};


$.insert_things = function(things, append) {
    /* Insert new things into a listing.*/
    return $.map(things, function(thing) {
            var data = thing.data;
            var midcol = $(".midcol:visible:first").css("width");
            var numcol = $(".rank:visible:first").css("width");
            var s = $.listing(data.parent);
            if(append)
                s = s.append($.unsafe(data.content)).children(".thing:last");
            else
                s = s.prepend($.unsafe(data.content)).children(".thing:first");
            s.find(".midcol").css("width", midcol);
            s.find(".rank").css("width", numcol);
            thing_init_func(s.hide().show());
            return s;
        });
};

$.fn.delete_table_row = function(callback) {
    var tr = this.parents("tr:first").get(0);
    var table = this.parents("table").get(0);
    if(tr) {
        $(tr).fadeOut(function() {
                table.deleteRow(tr.rowIndex);
                if(callback) {
                    callback();
                }
            });
    } else if (callback) {
        callback();
    }
};

$.fn.insert_table_rows = function(rows, index) {
    /* find the subset of the current selection that is a table, or
     * the first parent of the current selection that is a table.*/
    var tables = ((this.is("table")) ? this.filter("table") : 
                  this.parents("table:first"));
    
    $.map(tables.get(), 
          function(table) {
              $.map(rows, function(thing) {
                      var i = index;
                      if(i < 0) 
                          i = Math.max(table.rows.length + i + 1, 0);
                      i = Math.min(i, table.rows.length);
                      /* create a new row and set its id and class*/
                      var row = table.insertRow(i);
                      $(row).hide().attr("id", thing.id)
                          .addClass(thing.css_class);
                      /* insert cells */
                      $.map(thing.cells, function(cell) {
                              $(row.insertCell(row.cells.length))
                                  .html($.unsafe(cell));
                          });
                      /* reveal! */
                      $(row).fadeIn();
                  });
          });
    return this;
};


$.fn.captcha = function(iden) {
    /*  */
    var c = this.find(".capimage");
    if(iden) {
        c.attr("src", "http://" + reddit.ajax_domain 
               + "/captcha/" + iden + ".png")
            .parents("form").find('input[name="iden"]').val(iden);
    }
    return c;
};
   

/* Textarea handlers */
$.fn.insertAtCursor = function(value) {
    /* "this" refers to current jquery selection and may contain many
     * non-textarea elements, so filter out and apply to each */
    return $(this).filter("textarea").each(function() {
            /* this should be rebound to one of the elements in the orig list.*/
            var textbox = $(this).get(0);
            var orig_pos = textbox.scrollTop;
        
            if (document.selection) { /* IE */
                textbox.focus();
                var sel = document.selection.createRange();
                sel.text = value;
            }
            else if (textbox.selectionStart) {
                var prev_start = textbox.selectionStart;
                textbox.value = 
                    textbox.value.substring(0, textbox.selectionStart) + 
                    value + 
                    textbox.value.substring(textbox.selectionEnd, 
                                            textbox.value.length);
                prev_start += value.length;
                textbox.setSelectionRange(prev_start, prev_start);
            } else {
                textbox.value += value;
            }
        
            if(textbox.scrollHeight) {
                textbox.scrollTop = orig_pos;
            }
        
            $(this).focus();
        })
    .end();
};

$.fn.select_line = function(lineNo) {
    return $(this).filter("textarea").each(function() {
            var newline = '\n', newline_length = 1, caret_pos = 0;
            if ( $.browser.msie ) { /* IE hack */
                newline = '\r';
                newline_length = 0;
                caret_pos = 1;
            }
            
            var lines = $(this).val().split(newline);
            
            for(var x=0; x<lineNo-1; x++) 
                caret_pos += lines[x].length + newline_length;

            var end_pos = caret_pos;
            if (lineNo <= lines.length) 
                end_pos += lines[lineNo-1].length + newline_length;
            
            $(this).focus();
            if(this.createTextRange) {   /* IE */
                var start = this.createTextRange();
                start.move('character', caret_pos);
                var end = this.createTextRange();
                end.move('character', end_pos);
                start.setEndPoint("StartToEnd", end);
                start.select();
            } else if (this.selectionStart) {
                this.setSelectionRange(caret_pos, end_pos);
            }
            if(this.scrollHeight) {
                var avgLineHight = this.scrollHeight / lines.length;
                this.scrollTop = (lineNo-2) * avgLineHight;
            }
        });
};


$.apply_stylesheet = function(cssText) {
    
    var sheet_title = $("head").children("link[title], style[title]")
        .filter(":first").attr("title") || "preferred stylesheet";

    if(document.styleSheets[0].cssText) {
        /* of course IE has to do this differently from everyone else. */
        var sheets = document.styleSheets;
        for(var x=0; x < sheets.length; x++) 
            if(sheets[x].title == sheet_title) {
                sheets[x].cssText = cssText;
                break;
            }
    } else {
        /* for everyone else, we walk <head> for the <link> or <style>
         * that has the old stylesheet, and delete it. Then we add a
         * <style> with the new one */
        $("head").children('*[title="' + sheet_title + '"]').remove();
        $("head").append("<style type='text/css' media='screen' title='" + 
                         sheet_title + "'>" + cssText + "</style>");
  }
    
};

$.rehighlight_new_comments = function() {
  checked = $(".comment-visits-box input:checked");
  if (checked.length > 0) {
    var v = checked[0].value;
    highlight_new_comments(v);
  }
}

/* namespace globals for cookies -- default prefix and domain */
var default_cookie_domain
$.default_cookie_domain = function(domain) {
    if (domain) {
        default_cookie_domain = domain
    }
}

var cookie_name_prefix = "_"
$.cookie_name_prefix = function(name) {
    if (name) {
        cookie_name_prefix = name + "_"
    }
}

/* old reddit-specific cookie functions */
$.cookie_write = function(c) {
    if (c.name) {
        var options = {}
        options.expires = c.expires
        options.domain = c.domain || default_cookie_domain
        options.path = c.path || '/'

        var key = cookie_name_prefix + c.name,
            value = c.data

        if (value === null || value == '') {
            value = null
        } else if (typeof(value) != 'string') {
            value = JSON.stringify(value)
        }

        $.cookie(key, value, options)
    }
}

$.cookie_read = function(name, prefix) {
    var prefixedName = (prefix || cookie_name_prefix) + name,
        data = $.cookie(prefixedName)

    try {
        data = JSON.parse(data)
    } catch(e) {}

    return {name: name, data: data}
}

})(jQuery);
