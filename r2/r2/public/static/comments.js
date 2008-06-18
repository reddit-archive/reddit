function helpon(link, what, newlabel) {
    var id = _id(link);
    show(what + id);
    var oldlabel = link.innerHTML;
    if(newlabel) {
        link.innerHTML = newlabel
    }
    link.onclick = function() {
        return helpoff(link, what, oldlabel);
    };
    link.blur();
    return false;
}

function helpoff(link, what, newlabel) {
    var id = _id(link);
    hide(what+id);
    var oldlabel = link.innerHTML;
    if(newlabel) {
        link.innerHTML = newlabel
    }
    link.onclick = function() {
        return helpon(link, what, oldlabel);
    };
    link.blur();
    return false;
}


function ReplyTemplate() { return $("samplecomment_"); }

function comment_reply(id) {
    id = id || '';
    var s = $("samplecomment_" + id);
    if (!s) {
        return re_id_node(ReplyTemplate().cloneNode(true), id);
    }
    return s;
};

function _decode(text) {
    return decodeURIComponent(text.replace(/\+/g, " "));
}

function Comment(id) {
    this.__init__(id);
    var edit_body = this.get("edit_body");
    if(edit_body) {
        this.text = decodeURIComponent(edit_body.innerHTML.replace(/\+/g, " "));
    }
};

Comment.prototype = new Thing();

Comment.del = Thing.del;

Comment.prototype._edit = function(listing, where, text) {
    var edit_box = comment_reply(this._id);
    if (edit_box.parentNode != listing.listing) {
        if (edit_box.parentNode) {
            edit_box.parentNode.removeChild(edit_box);
        }
        listing.insert_node_before(edit_box, where);
    }
    else if (edit_box.parentNode.firstChild != edit_box) {
        var p = edit_box.parentNode;
        p.removeChild(edit_box);
        p.insertBefore(edit_box, p.firstChild);
    }
    var box = $("comment_reply_" + this._id);
    clearTitle(box);
    box.value = text;
    show(edit_box);
    return edit_box;
};

Comment.prototype.edit = function() {
    this._edit(this.parent_listing(), this.row, this.text);
    $("commentform_" + this._id).replace.value = "yes";
    this.hide();
};   

Comment.prototype.reply = function() {
    this._edit(this.child_listing(), null, '');
    $("commentform_" + this._id).replace.value = "";
    $("comment_reply_" + this._id).focus();
};

Comment.prototype.cancel = function() {
    var edit_box = comment_reply(this._id);
    hide(edit_box);
    this.show();
};

Comment.comment = function(r) {
    var id = r.id;
    var parent_id = r.parent;
    new Comment(parent_id).cancel(); 
    new Listing(parent_id).push(unsafe(r.content));
    new Comment(r.id).show();
    vl[id] = r.vl;
};

Comment.morechildren = function(r) {
    var c = new Thing(r.id);
    if(c.row) c.del();
    var parent = new Thing(r.parent).child_listing();
    parent.append(unsafe(r.content));

    var c = new Comment(r.id);
    c.show(true);
    vl[r.id] = r.vl;
};

Comment.editcomment = function(r) {
    var com = new Comment(r.id);
    com.get('body').innerHTML = unsafe(r.contentHTML);
    com.get('edit_body').innerHTML = unsafe(r.contentTxt);
    com.cancel();
    com.show();
};


Comment.prototype.collapse = function() { 
    hide(this.get('child'));
    hide(this.get('display'));
    hide(this.get('arrows'));
    show(this.get('collapsed'));
};

Comment.prototype.uncollapse = function() { 
    show(this.get('child'));
    show(this.get('display'));
    show(this.get('arrows'));
    hide(this.get('collapsed'));
};
    

function morechildren(form, link_id, children, depth) {
    var id = _id(form);
    form.innerHTML = _global_loading_tag;
    form.style.color="red";
    redditRequest('morechildren', {link_id: link_id,
                children: children, depth: depth, id: id});
    return false;
}


function editcomment(id)  {
    new Comment(id).edit();
};

function cancelReply(canceler) {
    new Comment(_id(canceler)).cancel();
};


function reply(id) {
    if (logged) {
        var com = new Comment(id).reply();
    }
    else {
        showcover(true, 'reply_' + id);
    }
};

function chkcomment(form) {
    if(form.replace.value) {
        return post_form(form, 'editcomment');
    }
    else {
        return post_form(form, 'comment');
    }
};

function clearTitle(box) {
    if (box.rows && box.rows < 7 || 
        box.style.color == "gray" ||
        box.style.color == "#808080") {
        box.value = "";
        box.style.color = "black";
        if (box.rows) { box.rows = 7;}
        try{
            box.focus();
        }
        catch(e) {};
    }
}

function hidecomment(id) {
    var com = new Comment(id);
    com.collapse();
    return false;
}

function showcomment(id) {
    var com = new Comment(id);
    com.uncollapse();
    return false;
}


Message = Comment;
Message.message = Comment.comment;


