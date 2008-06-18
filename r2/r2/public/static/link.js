function Thing(id) {
    this.__init__(id);
};

Thing.prototype = {
    __init__: function(id) {
        this._id = id;
        this.row = this.$("thingrow");
        if (this.row) {
            /* initialize sizing info for animations if not already */
            if (!this.max_height()) {
                this.set_height("fit");
            }
        }
    },

    _fade_and_hide: function(fraction) {
        fraction = Math.max(Math.min(fraction, 1), 0);
        var height_frac = Math.max(Math.min(2*fraction, 1), 0);
        var opac_frac = Math.max(Math.min(2 * fraction -1 , 1), 0);
        if(fraction == 0) 
            this.hide();
        else if (this.row.style.display == 'none')
            this.show();
        this.set_opacity(opac_frac);
        this.set_height((height_frac == 1) ? 'fit' : (this.max_height() * height_frac));
        this.row.cur_hide = fraction;
    },

    set_opacity : function(opac) {
            this.row.style.opacity = opac;
            var filt = "alpha(opacity=" + parseInt(opac*100) + ")";
            this.row.style.filter = filt;
            this.row.style.zoom = 1;
    },

    get: function(name) {
        return $(name + '_' + this._id);
    },

    $: function(name) {
        return $(name + '_' + this._id);
    },

    _fade_step: function(frac, fading) {
        if(fading == this.row.fading) {
            var opac_frac = Math.max(Math.min(frac , 1), 0);
            this.set_opacity(opac_frac);
        }
    },

    fade: function(duration, indx) {
        var t = this;
        this.row.fading = true;
        animate(function(x) { t._fade_step(x, true); }, 0, duration, indx);
    },

    unfade: function(duration, indx) {
        var t = this;
        this.row.fading = false;
        animate(function(x) { t._fade_step(x, false); }, 1, duration, indx);
    },

    _hide_step: function(fraction) {
        if(this.row.cur_hide == null)
            this.row.cur_hide = 1;
        if (this.row.hiding && fraction < this.row.cur_hide) {
            this._fade_and_hide(fraction);
        }
    },

    _show_step: function(fraction) {
        if(this.row.cur_hide == null)
            this.row.cur_hide = 0;
        if (!this.row.hiding && fraction > this.row.cur_hide) {
            this._fade_and_hide(fraction);
        }
    },

    hide: function(do_animate) {
        this.row.hidden = true;
        if(do_animate) {
            var t = this;
            this.row.hiding = true;
            animate(function(x) { t._hide_step(x); }, 0);
        }
        else {
            hide(this.row);
            if(this.__destroy && this.row && this.row.parentNode) {
                this.row.parentNode.removeChild(this.row);
            }
        }
    },

    show: function(do_animate) {
        this.row.hidden = false;
        if(do_animate) {
            var t = this;
            this.row.hiding = false;
            animate(function(x) { t._show_step(x) }, 1);
        }
        else {
            show(this.row);
        }
    },

    del: function(do_animate) {
        this.__destroy = true;
        this.hide(do_animate);
    },
    
    child_listing: function() {
        var child = this.$("child");
        if (!Listing.exists(this._id)) {
            l = Listing.create(this._id);
            child.insertBefore(l.ajaxHook, child.firstChild);
            child.insertBefore(l.listing,  child.firstChild);
        }
        return new Listing(this._id);
    },
    
    is_visible: function() {
        if(this.row) {
            if(this.row.hidden == null) 
                this.row.hidden = (this.row.style.display == 'none');
            return !this.row.hidden;
        }
        return false;
    },

    compute_height:function() {
        var arrows = this.$("arrows");
        var entry  = this.$("entry");
        var num  = this.$("num");
        return Math.max(arrows ? arrows.offsetHeight : 0,
                        entry  ? entry.offsetHeight  : 0,
                        num    ? num.offsetHeight    : 0);
    },
    
    parent_listing: function() {
        return Listing.attach(this.row.parentNode);
    },
    
    max_height: function() {
        return this.row._height + this.row._top_pad + this.row._bot_pad;
    },

    get_height: function() {
        return this.row.offsetHeight;
    },
    
    set_height: function(h) {
        var entry = this.$('entry');
        var arrows   = this.$('arrows');
        var num   = this.$('num');
        if(h == "fit" ||
           (this.max_height() && h >= this.max_height() *.90 )) {
            this.row.style.paddingTop = "";
            this.row.style.paddingBottom = "";
            h = "";
        }
        else if (h <= 0) {
            this.row.style.paddingTop = "0px";
            this.row.style.paddingBottom = "0px";
            h = "0px";
        }
        else {
            if(this.row._top_pad && h <= this.row._top_pad) {
                this.row.style.paddingTop = h + "px";
                this.row.style.paddingBottom = "0px";
                h = "0px";
            }
            else {
                var height;
                if (this.row.style.height) {
                    height = parseInt(this.row.style.height);
                }
                else {
                    height = this.compute_height();
                }
                var pad = this.row.offsetHeight - height;
                this.row.style.paddingTop = "";
                if(h < pad) {
                    this.row.style.paddingBottom = 
                        Math.max(h - this.row._top_pad, 0) + "px";
                    h = 0;
                }
                h += "px";
            }
        }
        entry.style.height = h;
        if(arrows) { arrows.style.height = h; }
        if(num) { 
            if (h) 
                num.style.marginTop = 0;
            else 
                num.style.marginTop = "";
            num.style.height = h;
                  
        }
        this.row.style.height = h;
        
        if(h == "" && this.is_visible()) {
            height =  this.compute_height();
            top_pad = entry.offsetTop - this.row.offsetTop - 1;
            bot_pad = this.row.offsetHeight - height - top_pad -1;
            /* cache heights for later restoration */
            this.row._height  = height;
            this.row._top_pad = top_pad;
            this.row._bot_pad = bot_pad;
        }

        return this.row.offsetHeight;
    }
};

Thing.del = function(r) {
    new Thing(r.id).del(true);
};

function Listing(id) {
    this.__init__(id);
};

Listing.prototype = { 
    __init__: function(id) {
        if(id) {
            id = "_" + id;
        }
        this.listing = $('siteTable' + id);
        this.ajax_hook = $('ajaxHook' + id);
        if(this.listing) {
            if(! this.listing.start_count) {
                this.listing.start_count = this.visible_count();
            }
        }
    },
    
    insert_node_before:  function(node, before_me, append_me) {
        before_me = before_me || this.listing.firstChild;
        if(!append_me && before_me) {
            this.listing.insertBefore(node, before_me);
        }
        else {
            this.listing.appendChild(node);
        }
    },

    /* insert content via innerHTML and return Thing objects of
     * inserted things */
    insert: function(content, before_me, append_me) {
        var a = this.ajax_hook;
        a.innerHTML = content;
        var childs = a.childNodes;
        var things = [];
        for(var i = 0; i < childs.length; i++) {
            var id = _id(childs[i]);
            if(id) {
                var t = new Thing(id);
                t.set_height("fit");
                t.hide();
                things.unshift(t);
            }
            this.insert_node_before(childs[i], before_me, append_me);
        }
        /*a.innerHTML = '';*/
        return things;
    },

    push: function(content) {
        return this.insert(content, this.listing.firstChild);
    },

    append: function(content) {
        return this.insert(content, null, true);
    },

    map: function(func) {
        if(this.listing) {
            var c = this.listing.childNodes;
            for(var i = 0; i < c.length; i++) {
                var id = _id(c[i]);
                if(id) {
                    func(new Thing(id));
                }
            }
        }
    },
    
    select: function(func) {
        var agg = [];
        this.map(function(t) { if(func(t)) agg.unshift(t); });
        return agg;
    },

    visible_count: function() {
        return this.select(function(t) { 
                return t.is_visible(); 
            }).length;
    },

    renumber: function(start_num) {
        var n = start_num;
        this.map(function(t) { 
                var num = t.$('num');
                if(num.firstChild.innerHTML) {
                    num = num.firstChild
                }
                if(num) {
                    var current_num = parseInt(num.innerHTML);
                    n = n || current_num;
                    if(t.is_visible()) {
                        num.innerHTML = (n++);
                    }
                }
            }
            );
    },
    
    reset_visible_count: function(n) {
        n = n || this.listing.start_count;
        this.map(function(t) {
                if(t.is_visible()) {
                    if(--n < 0) {
                        t.hide();
                    }
                }
            });
        this.renumber();
    }
};

Listing.exists = function(id) {
    return $('siteTable_' + id);
};

Listing.attach = function(node) {
    var id = /siteTable_(.*)/.exec(node.id);
    if (id) {
        var listing = new Listing(id[1]);
        if (listing.listing) {
            return listing;
        }
    }
};

Listing.create = function(id) {
    var l = new Listing(id);
    if (!l.listing) {
        l.listing = document.createElement("div");
        l.listing.id = "siteTable_" + id;
        l.ajaxHook = document.createElement("div");
        l.ajaxHook.id = "ajaxHook_" + id;
        l.ajaxHook.className = "ajaxhook";
    };
    return l; 
};

function make_sr_list(sr_diffs) {
    var srs = [];
    for(var sr in sr_diffs) {
        if (!(sr in Object.prototype) && sr_diffs[sr] != null) {
            srs.unshift(sr + ":" + (sr_diffs[sr]?1:0));
        }
    }
    return srs.join(',');
}


Listing.fetch_more = function(sr_diffs, sr_needed, num_needed) {
    var args = update_get_params({srs: make_sr_list(sr_diffs)});
    /* assumes one listing per page, where is global */
    new Ajax.Request(where.path + ".json-html", { parameters: make_get_params(args), 
                method: "get", onComplete: Listing_merge(sr_needed, num_needed) } );
};

function _fire_and_hide(type) {
    return function(fullname) {
        redditRequest(type, {id: fullname, uh: modhash});
        new Link(fullname).hide(true);
    };
}

Listing.unhide = _fire_and_hide('unhide');
Listing.hide   = _fire_and_hide('hide');
Listing.report = _fire_and_hide('report');
Listing.del    = _fire_and_hide('del');

Listing.parse = function(r) {
    var links = [];
    var res_obj = parse_response(r);
    if(res_obj && res_obj.response) {
        var r = res_obj.response.object;
        for(var i = 0; i < r.length; i++) {
            if (r[i].kind == "Listing") {
                for(var j = 0; j < r[i].data.length; j++) {
                    links.push(r[i].data[j].data);
                }
            }
        }
    }
    return links;
};

function Listing_merge(sr_needed, num_needed) {
    return function (r) {
        /* assumes only one listing */
        var l = new Listing("");
        var links = Listing.parse(r);
        var things = [];
        var count = Math.max(l.listing.start_count, links.length);

        for(var i = 0; i < links.length; i++) {
            var d = links[i];
            var t = new Thing(d.id);
            if(t.row) {
                if (! t.is_visible()) 
                    things.unshift(t);
            }
            else {
                if (! num_needed && i < count) {
                    t = l.insert(unsafe(d.content), l.listing.childNodes[i+1]);}
                else  
                    t = l.append(unsafe(d.content));
                if(d.sr == sr_needed || 
                   (num_needed && i >= count - num_needed)) 
                    things = things.concat(t);
                vl[d.id] = d.vl;
                sr[d.id] = d.sr;
            }
        }
        for(var i = 0; i < things.length; i++) {
            things[i].show(true);
        }
        add_to_aniframes(function() {
                l.reset_visible_count(count);
            }, 1);

        return;
    };
}

function Link(id) {
    this.__init__(id);
};

Link.prototype = new Thing();

// Commenting on a link is handled by the Comment API so defer to it
Link.comment = Comment.comment;

function linkstatus(form) {
    var title = field(form.title);
    if(title) {
        return _global_submitting_tag;
    }
    return _global_fetching_tag;
}

function setClick(a) {
    var id = _id(a);
    if (id) {
        if(logged) {
            a.className = "title loggedin click";
        }
        else {
            a.className = "title click";
        }
        setClickCookie(id);
    }
    return true;
}

function setClickCookie(id) {
    createCookie("click", readCookie("click") + id + ":");
}

