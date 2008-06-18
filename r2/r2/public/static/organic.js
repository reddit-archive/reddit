function OrganicListing() {
    this.__init__('organic');
    this._links = organic_links;
    /* first time, init the position and figure out what is loaded */
    if(!this.listing._loaded) {
        this.listing._loaded = {};
        /* and which ones are present in the listing  */
        var _this = this;
        this.map(function(t) {
                _this.listing._loaded[t._id] = t;
                if(t.is_visible()) {
                    for(var i = 0; i < _this._links.length; i++) {
                        if (t._id == _this._links[i]) {
                            _this.listing.pos = i;
                            break;
                        }
                    }
                }
                _this.listing.max_pos = _this.listing.pos;
                _this.listing.update_pos = true;
            });
    }
};

OrganicListing.prototype = new Listing();

OrganicListing.prototype.current = function() {
    return this.listing._loaded[this._links[this.listing.pos]];
};

OrganicListing.prototype.check_ahead = function(dir, num) {
    num = num || 10;
    dir = (dir > 0)? 1: -1;
    var pos = this.listing.pos;
    var len = this._links.length;
    var to_load = [];
    var streak = null;
    for(var i = 0; i < num; i++) {
        var j = ((i+1) * dir + pos + len) % len;
        if (!this.listing._loaded[this._links[j]]) {
            to_load.unshift(this._links[j]);
            if(streak == null) streak = true;
        }
        else if (streak) {
            streak = false;
        }
    }
    if( (streak && to_load.length > num/2) ||
        (!streak && to_load.length > 0) ) {
        to_load = to_load.join(',');
        var cur = this.current();                       
        redditRequest('fetch_links', {num_margin: cur.$("num")   .style.width,
                    mid_margin: cur.$("arrows").style.width,
                    links: to_load});
    }
};

function _fire_and_shift(type) {
    return function(fullname) {
        redditRequest(type, {id: fullname, uh: modhash});
        get_organic(true);
    };
}

OrganicListing.unhide = _fire_and_shift('unhide');
OrganicListing.hide   = _fire_and_shift('hide');
OrganicListing.report = _fire_and_shift('report');
OrganicListing.del    = _fire_and_shift('del');


OrganicListing.populate = function(links) {
    var o = new OrganicListing();
    for(var i = 0; i < links.length; i++) {
        d = links[i].data;
        var t = o.append(unsafe(d.content));
        if(t && t[0]) {
            vl[d.id] = d.vl;
            o.listing._loaded[d.id] = t[0];
        }
    }
};

OrganicListing.prototype.change = function(dir) {
    dir = (dir > 0)? 1: -1;
    this.check_ahead(dir);
    var pos = this.listing.pos;
    var len = this._links.length;
    pos = (pos + dir + len) % len;

    var n = this.listing._loaded[this._links[pos]];
    var c = this.current();
    if(n && c) {
        /* only update on "next" */
        if(dir > 0) {
            if(this.listing.max_pos == pos)
                this.listing.update_pos = true;
            else if (this.listing.update_pos)  {
                redditRequest('update_pos', {pos: (pos+1) % len});
                this.listing.max_pos = pos;
            }
        }
        else {
            this.listing.update_pos = false;
        }

        var _list = this.listing;
        _list.changing = true;
        _list.pos = pos;
        c.fade("veryfast");
        add_to_aniframes(function() {
                c.hide();
                n.show();
                n.set_opacity(0);
            }, 1);
        n.unfade("veryfast", 2);
        add_to_aniframes(function() {
                _list.changing = false;
            }, 3);
    }
};

function get_organic(next) {
    var l = new OrganicListing();
    if(l.listing.changing)
        return false;
    else if(next)
        l.change(1);
    else
        l.change(-1);
    return false;
}
