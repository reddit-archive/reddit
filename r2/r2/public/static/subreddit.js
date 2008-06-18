function subscribe(checkbox, id) {
    if (!logged) {
        return showcover();
    }
    if (checkbox.checked) {
        action = 'sub';
        set_score(id, 1);
    }
    else {
        action = 'unsub';
        set_score(id, 0);
    }
    redditRequest_no_response('subscribe', 
                              {'sr': id, 'action': action, 'uh': modhash});
}

function Subreddit(id) { }
Subreddit.prototype = new Thing();


function map_links_by_sr(srid, func) {
    var chx = $("sr_sel_chx_" + srid);
    var count = 0;
    if (chx) { chx = chx.checked; }
    for (var s in sr) {
        if (sr[s] == srid) {
            func(new Link(s), chx);
            count += 1;
        }
    }
    return count;
}


var changed_srs = {};
function change_sr(srid) {
    var chx = $("sr_sel_chx_" + srid);
    var srs_list = [];
    if (changed_srs[srid] == null) {
        changed_srs[srid] = chx.checked;
    } else {
        changed_srs[srid] = null;
    }
    var show_save = false;
    for(var x in changed_srs) {
        if (!(x in Object.prototype) && changed_srs[x] != null) {
            show_save = true;
            break;
        }
    }
    if (show_save) {
        show('subscr_sub');
    } else {
        hide('subscr_sub');
    }

    if(chx.checked) {
        show_by_srid(srid, changed_srs);
    }
    else {
        hide_by_srid(srid, changed_srs);
    }
    var box = $("sr_sel_" + srid);
    box.className = (chx.checked && 'selected') || "";
    return true;
}

function hide_by_srid(srid, sr_deltas) {
    var l = new Listing('');
    var res = map_links_by_sr(srid, 
                              function(link, checked) {
                                  if (link.row.parentNode == l.listing) {
                                      link.hide(true);
                                  }
                              });
    
    /*Listing.fetch_more(sr_deltas, null, res);*/
}

function show_by_srid(srid, sr_deltas) {
    var l = new Listing('');
    var res = map_links_by_sr(srid, 
                              function(link, checked) {
                                  if (link.row.parentNode == l.listing) {
                                      link.show(true);
                                  }
                              });
    if(!res) {
        Listing.fetch_more(sr_deltas, srid);
    }
    add_to_aniframes(function() {
            new Listing('').reset_visible_count();
        }, 1);

}


