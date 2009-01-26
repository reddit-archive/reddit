function frame_mod(id, uc) {
    if(!logged) {
        return frame_showlogin();
    }
    mod(id, uc);
}

function frame_showlogin() {
    hide("left", "menu", "vertxt", "passwd2", "user", "passwd");
    $("logbtn").innerHTML = "login";
    $("logform").op.value = "login";
    show("frame_middle", "usrtxt", "passtxt", "rem", "remlbl");
}

function cancel () {
    hide("frame_middle");
    show("frame_left", "menu");
    $("user").value = $("passwd").value = "";
    return false;
}

function kill(uh) {
    hide("main");
    show("killed");
    redditRequest('noframe');
}

function unkill() {
    hide("killed");
    show("main");
    redditRequest('frame');
}


function swapel(e1, e2, e) {hide(e1); show(e2); $(e2).select(); }

