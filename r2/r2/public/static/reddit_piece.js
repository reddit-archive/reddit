var style = 'reddit';
var cur_menu = null; //track the current open menu
var have_open = false;

function open_menu(menu) {
    var child = menu.nextSibling;
    if (child.className.indexOf("drop-choices") == -1) return;

    show(child);
    child.style.top = (menu.offsetTop + menu.offsetHeight) + 'px';
    child.style.left = menu.offsetLeft + 'px';

    menu.onclick = null;
    cur_menu = menu;
    have_open = true;
}

function close_menus() {
    uls = document.getElementsByTagName('DIV');
    for (var i=0; i<uls.length; i++) {
        var ul = uls[i];
        var menu = ul.previousSibling;
        if (menu != cur_menu && ul.className.indexOf('drop-choices') > -1) {
            hide(ul);
            menu.onclick = function() {
                return open_menu(this);
            }
        }
    }
    
    /* because body and the menu both fire the click event, cur_menu
       is only true for an instant when opening a menu */
    if (!cur_menu) {
        have_open = false;
    }
    cur_menu = null;
}

function hover_open_menu(menu) {
    if (have_open) {
        open_menu(menu);
        close_menus();
    }
}

var global_cookies_allowed = true;

function init() {
    /* temp strip off port for the ajax domain (which will need it to
     * make a request) */
    var i = ajax_domain.indexOf(':');
    var a = (i < 0) ? ajax_domain : ajax_domain.slice(0, i);
    /* permanently strip it off for the cur_domain which only sets cookies */
    i = cur_domain.indexOf(':');
    cur_domain = (i < 0) ? cur_domain : cur_domain.slice(0, i);

    if(cur_domain != a) {
        global_cookies_allowed = false;
    }
    else if(cnameframe && !logged) {
        var m = Math.random() + '';
        createCookie('test', m);
        global_cookies_allowed = (readCookie('test') == m);
    }
    if (global_cookies_allowed) {
        updateClicks();
        /*updateMods();*/
    }
    stc = $("siteTable_comments");
    /* onload populates reddit_link_info, so checking its contents
     * ensures it doesn't get called on reload/refresh */
    if ( reddit_thing_info.fetch && reddit_thing_info.fetch.length != 0 )
        redditRequest("onload", {ids: reddit_thing_info.fetch.join(",")}, 
                      handleOnLoad);
    update_reddit_count();
}

function handleOnLoad(r) {
    r = parse_response(r);
    
    var f = reddit_thing_info.fetch;

    reddit_thing_info = (r && r.response) ? r.response.object : {};

    for (var i = 0; i < f.length; i++) {
        var l = new Link(f[i]);
        if (l.row && l.row.style.display != "none")
            l.show();
    }
    reddit_thing_info.fetch = [];
}

function deletetoggle(link, type) {
    var parent = link.parentNode;
    var form = parent.parentNode;
    link.blur();

    var q = document.createElement('span');
    q.className = 'question';
    q.innerHTML = form.question.value;

    var yes = document.createElement('a');
    yes.className = "yes";
    yes.innerHTML = form.yes.value;
    yes.href='javascript:void(0)';

    var slash = document.createTextNode('/');

    var no = document.createElement('a');
    no.className = "no";
    no.innerHTML = form.no.value;
    no.href='javascript:void(0)';

    var oldtext = parent.innerHTML;
    no.onclick = function() {
        return untoggle(false, parent, oldtext, type)};

    yes.onclick = function() {
        return untoggle(true, parent, oldtext, type)};

    q.appendChild(yes);
    q.appendChild(slash);
    q.appendChild(no);
    
    parent.innerHTML = '';
    parent.appendChild(q);
    
    return false;
}


function untoggle(execute, parent, oldtext, type) {
    if(execute) {
        var form = parent.parentNode;
        var uh = modhash; //global
        parent.innerHTML = form.executed.value || oldtext;

        if(type == 'del') {
            post_form(form, type, function() {return ""});
        }
        else if (typeof(type) == "string") {
            post_form(form, type, function() {return ""});
        }
        else if (typeof(type) == "function") {
            type(form.id.value, uh);
        }
    } 
    else {
        parent.innerHTML = oldtext;
    }
    return false;
}



function chklogin(form) {
    if(global_cookies_allowed) {
        var op = field(form.op);
        var status = $("status_" + op);
        if (status) {
            status.innerHTML = _global_submitting_tag;
        };
        if (op == 'login' || op == 'login-main') {
            post_form(form, 'login');
        }
        else {
            post_form(form, 'register');
        }
        return false;
    }
    return true;
}

function toggle(a_tag, op) {
    var form = a_tag.parentNode;
    post_form(form, op, function() {return ''});
    var action = form.action.value;
    var toggled = form.toggled_label.value;
    form.toggled_label.value = a_tag.innerHTML;
    a_tag.innerHTML = toggled;
    var toggled_action = form.toggled_action.value;
    form.toggled_action.value = form.action.value;
    form.action.value = toggled_action;
    return false;
}


function resizeCookie(name, size) {
    var c = readCookie(name);
    if(c.length > size) {
        var i = size;
        while (i >= 0 && c[i--] != ';') { }
        createCookie(name, (i && c.slice(0, i+1)) || '');
    }
}

/*function updateMods() {
    var mods = readCookie("mod");
    if (mods) {
        mods = mods.split(':');
        for (var i = 0; i < mods.length; i++) {
            var m = mods[i].split('=');
            setMod(m[0], m[1]);
        }
    }
    }*/

function updateClicks() {
    var clicks = readCookie("click");
    if (clicks) {
        clicks = clicks.split(':');
        for (var i = 0; i < clicks.length; i++) {
            setClick(clicks[i]);
        }
    }
}

function showlang() {
    offset = window.pageYOffset||document.body.scrollTop||document.documentElement.scrollTop;

    $('langcover').style.top = offset + 'px';
    $('langpopup').style.top = 40 + offset + 'px'; 
    show("langcover", "langpopup");
    return false; 
}

function showcover(warning, reason) {
    offset = window.pageYOffset||document.body.scrollTop||document.documentElement.scrollTop;
    if (warning) {
        show('cover_msg', 'cover_disclaim');
    }
    else {
        hide('cover_msg', 'cover_disclaim');
    }
    $('loginpopup').style.top = 40 + offset + 'px';

    if (reason == 'sr_change_') {
        //depends on links.js and subreddit.js
        reason += make_sr_list(changed_srs);
    }

    if (reason) {
        $('login_login').elements.reason.value = reason;
        $('login_reg').elements.reason.value = reason;
    }

    new_captcha();
    show("cover", "loginpopup");
    return false;
}

function hidecover(cover, loginpopup) {
    hide(cover, loginpopup);
    /*    $('login_main_form').innerHTML = $('login_cover_form').innerHTML;
          $('login_cover_form').innerHTML = ''; */
}

function check_some() {
  var have_checked = false;
  var elements = $("all-langs").form.elements;
  for (var i = 0; i < elements.length; i++) {
     el = elements[i];
     if (el.name.indexOf("lang-") != -1 && el.checked) {
       have_checked = true;
       break;
     }
  }
  if (have_checked) {
    var some = $("some-langs");
    some.checked = "checked";
  }
}

function clear_all() {
  var all = $("all-langs");
  if (!all.checked) return;
  var elements = all.form.elements;
  for (var i = 0; i < elements.length; i++) {
     el = elements[i];
     if (el.name.indexOf("lang-") != -1)
       el.checked = false;
  }
}

function click(id) {
    setClick(id);
    setClickCookie(id);
    return true;
}

function frame(a_tag, id) {
    click(id);
    a_tag.href = "/goto?id=" + id;
    return true;
}

function set_sort(where, sort) {
    redditRequest('sort', {sort: sort,
                where: where});
    return true;
}

function disable_ui(name) {
    var help = $(name + "-help");
    var gone = $(name + "-gone");
    help.parentNode.innerHTML = gone.innerHTML;
    redditRequest('disable_ui', {id: name});
}

function update_reddit_count() {
    if (!cur_site || !logged) return;

    var decay_factor = .9; //precentage to keep
    var decay_period = 86400; //num of seconds between updates
    var num_recent = 10; //num of recent reddits to report
    var num_count = 100; //num of reddits to actually count

    var date_key = '_date';
    var cur_date = new Date();
    var count_cookie = 'reddit_counts';
    var recent_cookie = 'recent_reddits';
    var reddit_counts = readCookie(count_cookie);

    //init the reddit_counts dict
    if (reddit_counts) reddit_counts = reddit_counts.parseJSON();
    else {
        reddit_counts = {};
        reddit_counts[date_key] = cur_date.toString();
    }

    var last_reset = new Date(reddit_counts[date_key]);
    var decay = cur_date - last_reset > decay_period * 1000;
    var names = [];

    //incrmenet the count on the current reddit
    reddit_counts[cur_site] = (reddit_counts[cur_site] || 0) + 1;

    //collect the reddit names (for sorting) and decay the view counts
    //if necessary
    for (var sr_name in reddit_counts) {
        if (sr_name == date_key || Object.prototype[sr_name]) continue;

        if (decay && sr_name != cur_site) {
            //compute the new count val
            var val = Math.floor(decay_factor * reddit_counts[sr_name]);
            if (val > 0) reddit_counts[sr_name] = val;
            else delete reddit_counts[sr_name];
        }
        
        if (reddit_counts[sr_name]) names.push(sr_name);
    }

    //sort the names by the view counts
    names.sort(function(n1, n2) {return reddit_counts[n2] - reddit_counts[n1];});

    //update the last decay date
    if (decay) reddit_counts[date_key] = cur_date.toString();

    //build the list of names to report as "recent"
    var recent_reddits = "";
    for (var i = 0; i < names.length; i++) {
        var sr_name = names[i];
        if (i < num_recent) {
            recent_reddits += names[i] + ',';
        } else if (i >= num_count && sr_name != cur_site) {
            delete reddit_counts[sr_name];
        }
    }

    //set the two cookies: one for the counts, one for the final
    //recent list
    createCookie(count_cookie, reddit_counts.toJSONString());
    if (recent_reddits) {
        createCookie(recent_cookie, recent_reddits);
    }
}
