var aniqueue = [];
var _frameRate = 15; /* ms */
var _duration = 750; /* ms */

var _ani_speeds = {slow: 2* _duration,
                   medium: _duration,
                   fast: _duration/2,
                   veryfast: _duration/4};

function __animate() {
    var a = aniqueue ? aniqueue[0] : [];
    var newqueue = [];
    for(var i = 0;  i < a.length; i++) {
        var y = a[i]();
        if (y) newqueue.unshift(a[i]);
    }
    if(newqueue.length > 0) {
        aniqueue[0] = newqueue;
    }
    else {
        aniqueue  = aniqueue.slice(1);
    }

    if (!aniqueue.length && animator) {
        stop_animate();
    }
}

var animator;

function add_to_aniframes(func, frame_indx) {
    frame_indx = frame_indx || 0;
    if((frame_indx >= 0 && aniqueue.length <= frame_indx) || aniqueue.length == 0) {
        aniqueue.push([]);
        frame_indx = Math.min(aniqueue.length-1, frame_indx);
    }
    aniqueue[frame_indx].unshift(func);
    if(! animator) {
        setTimeout(function() { start_animate(_frameRate); }, 30);
    }
    return frame_indx;
}

function animate(func, goal, duration, frame_indx) {
    var d = null;
    var g = goal ? 1 : 0;
    if (_ani_speeds[duration])
        duration = _ani_speeds[duration];
    duration = duration || _duration;
    
    add_to_aniframes(function() {
            d = d || new Date().getTime();
            var level = (new Date().getTime() - d)/duration;
            level = g ? level : 1 - level;
            level = Math.max(Math.min(level, 1), 0);
            try {
                func(level);
                return (level != g); 
            } catch(e) {
                return false;
            }
        }, frame_indx);
}

function start_animate(interval) {
    if (!animator) {
        animator = setInterval(__animate, interval);
    }
}

function stop_animate() {
    clearInterval(animator);
    animator = null;
}