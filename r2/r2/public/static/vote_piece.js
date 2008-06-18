var upm = "arrow upmod";
var upr = "arrow up";
var downm = "arrow downmod";
var downr = "arrow down";

var upcls    = [upr,   upr,   upm  ];
var downcls  = [downm, downr, downr];
var scorecls = ["score dislikes", "score", "score likes"];


//cookie setting junk
function cookieName(name) {
    return (logged || '') + "_" + name;
}

function createCookie(name,value,days) { 
    if (days) { 
        var date = new Date();
        date.setTime(date.getTime()+(days*24*60*60*1000));
        var expires="; expires="+date.toGMTString();
    }
    else expires="";
    document.cookie=cookieName(name)+"="+value+expires+"; path=/";
} 

function readCookie(name) {
    var nameEQ=cookieName(name) + "=";
    var ca=document.cookie.split(';');
    for(var i=0;i< ca.length;i++) { 
        var c =ca[i]; 
        while(c.charAt(0)==' ') c=c.substring(1,c.length);
        if(c.indexOf(nameEQ)==0) return c.substring(nameEQ.length,c.length);
    }
    return '';
}


/*function setModCookie(id, c) {
    createCookie("mod", readCookie("mod") + id + "=" + c + ":");
    }*/

function set_score(id, dir) 
{
   var label = vl[id];
    var score = $("score_" + id);
    if(score) {
        score.className = scorecls[dir+1];
        score.innerHTML = label   [dir+1];
    }
}

function mod(id, uc, vh) {
    if (vh == null) vh = '';

    //logged is global
    var up = $("up_" + id);
    var down = $("down_" + id);
     var dir = -1; 

    if (uc && up.className == upm || !uc && down.className == downm) {
        dir = 0;
    }
    else if (uc) {
        dir = 1;
    }

    if (logged) {
        redditRequest_no_response('vote', {id: id, uh: modhash, dir: dir, vh: vh});
    }

    up.className    = upcls   [dir+1];
    down.className  = downcls [dir+1];
    set_score(id, dir);
}

