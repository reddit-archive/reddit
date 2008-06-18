var style = 'reddit';
var cur_menu = null; //track the current open menu
var have_open = false;

function open_menu(menu) {
    for (var i=0; i< menu.childNodes.length; i++) {
        child = menu.childNodes[i];
        if (child.className == "drop-choices") {
            child.style.visibility = 'visible';
            child.style.top = menu.offsetHeight + 'px';

            //expand the choices to width of the menu. fixes a
            //highlighting issue in FF2
            if (menu.offsetWidth > child.offsetWidth) {
                child.style.width = menu.offsetWidth + 'px';
            }
            break;
        }
    }
    menu.onclick = null;
    cur_menu = menu;
    have_open = true;
}

function close_menus() {
    uls = document.getElementsByTagName('DIV');
    for (var i=0; i<uls.length; i++) {
        var ul = uls[i];
        var menu = ul.parentNode;
        if (menu != cur_menu && ul.className == 'drop-choices') {
            ul.style.visibility = 'hidden';
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

function init() {
    updateClicks();
    /*updateMods();*/
    stc = $("siteTable_comments");
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
        parent.innerHTML = form.executed.value;

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
