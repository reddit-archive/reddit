function unsafe(text) {
    text = text.replace?text:"";
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
function redditRequest(op, parameters, worker_in, block) {
    var action = op;
    var worker = worker_in;
    if (!parameters) {
        parameters = {};
    }
    if (post_site) {
        parameters.r = post_site;
    }
    if (cnameframe) {
        parameters.cnameframe = 1;
    }
    op = api_loc + op;
    if(!worker) {
        worker = handleResponse(action);
    }
    else {
        worker = function(r) {
            remove_ajax_work(action);
            return worker_in(r);
        }
    }
    if(block == null || add_ajax_work(action)) {
        new Ajax.Request(op, {parameters: make_get_params(parameters), 
                    onComplete: worker});
    }
}

var _ajax_work_queue = {};
function add_ajax_work(op) {
    if(_ajax_work_queue[op]) {
        return false;
    }
    _ajax_work_queue[op] = true;
    return true;
} 
function remove_ajax_work(op) {
    _ajax_work_queue[op] = false;
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

function applyStylesheet(cssText) {
  /* also referred to in the reddit.html template, for the name of the
     stylesheet set for this reddit. These must be in sync, because
     I'm over-writing it here */
  var sheet_title = 'applied_subreddit_stylesheet';

  if(document.styleSheets[0].cssText) {
    /* of course IE has to do this differently from everyone else. */
    for(var x=0; x < document.styleSheets.length; x++) {
      if(document.styleSheets[x].title == sheet_title) {
        document.styleSheets[x].cssText = cssText;
        break;
      }
    }
  } else {
    /* for everyone else, we walk <head> for the <link> or <style>
       that has the old stylesheet, and delete it. Then we add a
       <style> with the new one */
    var headNode  = document.getElementsByTagName("head")[0];
    var headNodes = headNode.childNodes;

    for(var x=0; x < headNodes.length; x++) {
      var node = headNodes[x];
    
      if(node.title == sheet_title) {
        headNode.removeChild(node);
        break;
      }
    }

    var appliedCSSNode = document.createElement('style');
    appliedCSSNode.type = 'text/css';
    appliedCSSNode.rel = 'stylesheet';
    appliedCSSNode.media = 'screen';
    appliedCSSNode.title = sheet_title;
    
    appliedCSSNode.textContent = cssText;
    
    headNode.appendChild(appliedCSSNode);
  }
}

function showDefaultStylesheet() {
  return toggleDefaultStylesheet(true);
}
function hideDefaultStylesheet() {
  return toggleDefaultStylesheet(false);
}
function toggleDefaultStylesheet(p_show) {
  var stylesheet_contents = $('stylesheet_contents').parentNode.parentNode;
  var default_stylesheet  = $('default_stylesheet').parentNode.parentNode;
  
  var show_button  = $('show_default_stylesheet');
  var hide_button  = $('hide_default_stylesheet');

  if(p_show) {
      default_stylesheet.style.width = "50%";
      stylesheet_contents.style.width = "50%";
      show(default_stylesheet, hide_button);
      hide(show_button);
  } else {
      stylesheet_contents.style.width = "100%";
      default_stylesheet.style.width = "";
      show(show_button);
      hide(default_stylesheet, hide_button);
  }

  return false; // don't post the form
}

function gotoTextboxLine(textboxID, lineNo) {
  var textbox = $(textboxID);
  var text = textbox.value;

  var newline = '\n';
  var newline_length = 1;
  var caret_pos = 0;

  if ( text.indexOf('\r') > 0) {
    /* IE hack */
    newline = '\r';
    newline_length = 0;
    caret_pos = 1;
  }

  var lines = textbox.value.split(newline);

  for(var x=0; x<lineNo-1; x++) {
    caret_pos += lines[x].length + newline_length;
  }
  var end_pos = caret_pos;
  if (lineNo < lines.length) {
      end_pos += lines[lineNo-1].length + newline_length;
  }
 

  textbox.focus();
  if(textbox.createTextRange) {   /* IE */
      var start = textbox.createTextRange();
      start.move('character', caret_pos);
      var end = textbox.createTextRange();
      end.move('character', end_pos);
      start.setEndPoint("StartToEnd", end);
      start.select();
  } else if (textbox.selectionStart) {
      textbox.setSelectionRange(caret_pos, end_pos);
  }

  if(textbox.scrollHeight) {
      var avgLineHight = textbox.scrollHeight / lines.length;
      textbox.scrollTop = (lineNo-2) * avgLineHight;
  }
}


function insertAtCursor(textbox, value) {
    textbox = $(textbox);
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
            textbox.value.substring(textbox.selectionEnd, textbox.value.length);
        prev_start += value.length;
        textbox.setSelectionRange(prev_start, prev_start);
    } else {
        textbox.value += value;
    }

    if(textbox.scrollHeight) {
        textbox.scrollTop = orig_pos;
    }

    textbox.focus();
}



function upload_image(form, status) {
  $('img-status').innerHTML = status;
  show('img-status');
  return true;
}


function completedUploadImage(status, img_src, name, errors) {
  show('img-status');
  $('img-status').innerHTML = status;
  for(var i = 0; i < errors.length; i++) {
      var e = $(errors[i][0]);
      if( errors[i][1]) {
          show(e);
          e.innerHTML = errors[i][1];
      }
      else {
          hide(e);
      }
          
  }

  if(img_src) {
      $('upload-image').reset();
      hide('submit-header-img');
      if (!name) {
          $('header-img').src = img_src;
          $('img-preview').src = img_src;
          show('delete-img');
          hide('submit-img');
          show('img-preview-container');
      } else {
          var img = $("img-preview_" + name);
          if(img) { 
              /* Because IE isn't smart enought to eval "!img" */
          }
          else {
              var ul = $("image-preview-list");
              var li = $("img-prototype").cloneNode(true);
              li.id = "img-li_";
              ul.appendChild(li);
              re_id_node(li, ''+name);
              var name_b = $("img_name_" + name);
              if(name_b) {
                  name_b.innerHTML = name;
              }
              var label = $("img_url_" + name);
              if(label) {
                  label.innerHTML = "url(%%" + name + "%%)";
              }
              img = $("img-preview_" + name);

              var sel_list = $('old-names');
              if (sel_list) {
                  var opt = document.createElement('option');
                  opt.innerHTML = name;
                  sel_list.appendChild(opt);
              }
          } 
          img.src = img_src;
          $("img-preview-a_" + name).href = img_src;
          show("img-li_" + name);
      }
  }
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
        remove_ajax_work(action);
        var res_obj = parse_response(r);
        if(!res_obj) {
            if($('status')) 
                $('status').innerHTML = '';
            return;
        }
        // first thing to check is if a redirect has been requested
        if(res_obj.redirect) {
            window.location = unsafe(res_obj.redirect);
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
        // handle applied CSS
        if(r.call) {
          var calls = r.call;
          for(var i=0; i<calls.length; i++) {
              eval(calls[i]);
          }
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
                var id = r.captcha.id;
                var captcha = $("capimage" + (id?('_'+id):''));
                var capiden = $("capiden" + (id?('_'+id):''));
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
                                field[i] = unsafe(u[i]);
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
    function add_id(s) {
        if(id && s && typeof(s) == "string") {
            if(s.substr(s.length-1) != '_') s += '_';
            s += id;
        }
        return s;
    }
    if(node.id && typeof(node.id) == "string") { node.id = add_id(node.id); }
    if(node.htmlFor) { add_id(node.htmlFor); }
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

function post_form(form, where, statusfunc, nametransformfunc, block) {
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
    redditRequest(where, p, null, block); 
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

function view_embeded_media(id, media_link) {
    var eid = "embeded_media_" + id;
    var watchid = "view_embeded_media_span_watch_" + id;    
    var closeid = "view_embeded_media_span_close_" + id;
    var watchspan = document.getElementById(watchid);
    var closespan = document.getElementById(closeid);
    var e = document.getElementById(eid);
    if (e.style.display == "none") {
	e.style.display = "block";
	e.innerHTML = media_link;
	watchspan.style.display = "none";
	closespan.style.display = "inline";
    } else {
	e.style.display = "none";
	watchspan.style.display = "inline";
	closespan.style.display = "none";
    }

}

function show_hide_child(el, tagName, label) {
    code_block = el.parentNode.getElementsByTagName(tagName)[0];
    if (code_block.style.display == "none") {
            show(code_block);
            el.innerHTML = 'hide ' + label;
    } else if (code_block.style.display == "") {
            hide(code_block);
            el.innerHTML = 'view ' + label;
        }
}
    