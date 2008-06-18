function unsafe(text) {
    text = text || "";
    return text.replace(/&gt;/g, ">").replace(/&lt;/g, "<").replace(/&amp;/g, "&");
}


function hide () {
    for (var i = 0; i < arguments.length; i++) {
            var e = $(arguments[i]); 
            if (e) e.style.display = "none";
    }
}

function show () {
    for (var i = 0; i < arguments.length; i++) {
        var e = $(arguments[i]); 
        if (e) e.style.display = "";
    }
}

Object.prototype.__iter__ = function(func) {
    var res = [];
    for(var o in this) {
        if(!(o in Object.prototype)) {
            res.unshift(func(o, this[o]));
        }
    }
    return res;
};

function make_get_params(obj) {
    return obj.__iter__(function(x, y) {
            return x + "=" + encodeURIComponent(y);
        }).join("&");
}

function update_get_params(updates) {
    var getparams = {};
    where.params.__iter__(function(x, y) {
            getparams[x] = y;
        });
    if (updates)
        updates.__iter__(function(x, y) {
                getparams[x] = y;
            });
    return getparams;
}

/* where is global */
function relative_path(updates) {
    var getparams = update_get_params(updates);
    path = where.path;
    if(getparams) {
        path += "?" +  make_get_params(getparams);
    }
    return path;
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
    cur_menu = null;
}


function _id(obj) {
    if(obj && obj.id) {
        var id = obj.id;
        if(id.value) {id = id.value};
        id = id.split('_');
        if (id.length > 2) {
            id = id[id.length-2] + '_' + id[id.length-1];
            if(id == null) {return '';}
            return id;
        }
    }
    return '';
}

function buildParams(parameters) {
    if(parameters) {
        try {
            var p = new Array();
            for(var i = 0; i+1 < parameters.length; i += 2) {
                p.push(parameters[i] + '=' + encodeURIComponent(parameters[i+1]));
            }
            parameters = p.join('&');
        } catch(e) {
            parameters = '';
            alert(e);
        }
    }
    return parameters;
}

var api_loc = '/api/';
function redditRequest(op, parameters, worker_in) {
    var action = op;
    var worker = worker_in;
    if (!parameters) {
        parameters = {};
    }
    if (post_site) {
        parameters.r = post_site;
    }
    op = api_loc + op;
    if(!worker) {
        worker = handleResponse(action);
    }
    else {
        worker = function(r) {
            return worker_in(r);
        }
    }
    new Ajax.Request(op, {parameters: make_get_params(parameters), 
                onComplete: worker});
}

function redditRequest_no_response(op, parameters) {
    redditRequest(op, parameters, function(r){});
}

function get_class_from_id(id) {
    if(id) {
        id = id.split('_')[0];
        return class_dict[id];
    }
}

function parse_response(r) {
    if(r.status == 500) return;
    return r.responseText.parseJSON();
}

function tup(x) {
    if(! x.length ) { return [x] };
    return x;
}

function handleResponse(action) {
    var my_iter = function(x, func) {
        if(x) {
            var y = tup(x);
            for(var j = 0; j < y.length; j++) {
                func(y[j]);
            }
        }
    };
    var responseHandler = function(r) {
        var res_obj = parse_response(r);
        if(!res_obj) {
            if($('status')) 
                $('status').innerHTML = '';
            return;
        }
        // first thing to check is if a redirect has been requested
        if(res_obj.redirect) {
            window.location = res_obj.redirect;
            return;
        }
        // next check for errors
        var error = res_obj.error;
        if(error && error.name) {
            var errid = error.name;
            if (error.id) { errid += "_" + error.id; }
            errid = $(errid);
            if (errid) { 
                show(errid);
                $(errid).innerHTML = error.message; 
            }
        }
        var r = res_obj.response;
        if(!r) return;
        var obj = r.object;
        if(obj) {
            my_iter(tup(obj),
                    function(u) {
                        if(u && u.kind && class_dict[u.kind]) {
                            var func = (class_dict[u.kind][u.action] || 
                                        class_dict[u.kind][action]);
                            if(func) {
                                func(u.data);
                            }
                        }
                    });
        }
        // handle shifts of focus
        if (r.focus) {
            var f = $(r.focus);
            if(f) {f.focus();
                f.onfocus = null;}
        }
        if (r.blur) {
            var f = $(r.blur);
            if(f) {f.blur();
                f.onblur = null;}
        }
        if (r.captcha) {
            if (r.captcha.refresh) {
                var captcha = $("capimage");
                var capiden = $("capiden");
                capiden.value = r.captcha.iden;
                captcha.src = ("/captcha/" + r.captcha.iden + ".png?" +
                               Math.random())
            }
        }
        if (r.success) {
            fire_success();
        }
        my_iter(r.update, 
                function(u) {
                    var field = u.id && $(u.id);
                    if(field) {
                        for(var i in u) {
                            if(typeof(u[i]) != "function" && u != 'name') {
                                field[i] = u[i];
                            }
                        } }});
        my_iter(r.hide,
                function(h) {
                    var field = h.name && $(h.name);
                    if(field) { hide(field); }});
        my_iter(r.show,
                function(h) {
                    var field = h.name && $(h.name);
                    if(field) { show(field); }});
    };
    return responseHandler;
}

function re_id_node(node, id) {
    if(node.id && typeof(node.id) == "string") { node.id += id; }
    var children = node.childNodes;
    for(var i = 0; i < children.length; i++) {
        re_id_node(children[i], id);
    }
    return node;
}


function Thing(id) {
    this.__init__(id);
};

function field(form_field) {
    if (form_field == null || form_field.value == null || 
        ((form_field.type == 'text'  || form_field.type == 'textarea')
         && form_field.style.color == "gray") ||
        (form_field.type == 'radio' && ! form_field.checked)) {
        return '';
    }
    else if (form_field.type == 'checkbox') {
        return form_field.checked?'on':'off';
    }
    return form_field.value;
}

function change_w_callback(link, func) {
    var parent = link.parentNode;
    var form = parent.parentNode;
    var id = form.id.value;
    link.blur();
    var executed = document.createElement('span');
    executed.innerHTML = form.executed.value;
    parent.insertBefore(executed, link);
    hide(link);
    func(id);
    return false;
}

function change_state(link, type) {
    change_w_callback(link, function(id) {
            redditRequest(type, {id: id, uh:modhash});
        });
    return false;
}

function post_form(form, where, statusfunc, nametransformfunc) {
    var p = {uh: modhash};
    var id = _id(form);
    var status = $("status");
    
    if(statusfunc == null) {
        statusfunc = function(x) { return _global_submitting_tag; };
    }
    if(nametransformfunc == null) {
        nametransformfunc = function(x) {return x;}
    }
    if(id) {
        status = $("status_" + id);
        p.id = id;
    }
    if(status) { status.innerHTML = statusfunc(form); }
    for(var i = 0; i < form.elements.length; i++) {
        if(! form.elements[i].id || !id || 
           _id(form.elements[i]) == id) {
            var f = field(form.elements[i]);
            if (f) {
                p[nametransformfunc(form.elements[i].name)] = f;
            }
        }
    }
    redditRequest(where, p); 
    return false;
}


// Used in submitted form rendering to allow for an empty field
// when no JS is present, but some greyed text otherwise.
function setMessage(field, msg) {
    if (! field.value || field.value == msg ) {
        field.value = msg;
        field.style.color = "gray";
    }
    else {
        field.onfocus = null;
    }
}
                            

function more(a_tag, new_label, div_on, div_off) {
    var old_label = a_tag.innerHTML;
    a_tag.innerHTML = new_label;
    var i;
    for(i = 0; i < div_on.length; i++) { show(div_on[i]); }
    for(i = 0; i < div_off.length; i++) { hide(div_off[i]); }
    a_tag.onclick = function() {
        return more(a_tag, old_label, div_off, div_on);
    };
    return false;
}


function new_captcha() {
    redditRequest("new_captcha"); 
}
