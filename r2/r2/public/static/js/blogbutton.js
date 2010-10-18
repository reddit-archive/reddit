$(function() {
        /* set default arrow behavior */
        var state = null;
        function color(x) {
            if(x.substring(0,1) != "#") 
                return "#" + x;
            return x;
        }
        function set_score_class() {
            if (state == 1) {
                $(".arrow.up").addClass("upmod").removeClass("up");
                $(".arrow.downmod").removeClass("downmod").addClass("down");
                $(".entry").removeClass("dislikes").addClass("likes");
            }
            else if (state == -1) {
                $(".arrow.upmod").removeClass("upmod").addClass("up");
                $(".arrow.down").addClass("downmod").removeClass("down");
                $(".entry").addClass("dislikes").removeClass("likes");
            }
            else {
                $(".arrow.upmod").removeClass("upmod").addClass("up");
                $(".arrow.downmod").removeClass("downmod").addClass("down");
                $(".entry").removeClass("dislikes").removeClass("likes");
            }
        }
        $(".arrow.up").click(function() {
                state = $(this).hasClass("up") ? 1: 0;
                set_score_class();
            });
        $(".arrow.down").click(function() {
                state = $(this).hasClass("down") ? -1: 0;
                set_score_class();
            });

        var q = document.location.search;
        if (q && q.substring(0,1) == '?') {
            q = q.slice(1, q.length);
        }
        var querydict = {};
        $.map(q.split("&"), function(x) {
                var a, b, lst;
                lst = $.map(x.split('='), function(t) {
                        return $.websafe(decodeURIComponent(t));
                    });
                a = lst[0];
                b = lst[1];
                querydict[a] = b;
            }); 
        var submit = "/submit?url=" + encodeURIComponent(querydict.url);
        if (querydict.sr) {
            submit = "/r/" + querydict.sr + submit;
        }
        if (querydict.title) {
            submit += "&title=" + encodeURIComponent(querydict.title);
        }
        $("a").attr("href", submit);
        if(querydict.bgcolor) {
            $("body").css("background-color", color(querydict.bgcolor));
        }
        if(querydict.bordercolor) {
            $(".blog").css("border-color", color(querydict.bordercolor));
        }

        var target = (querydict.newwindow)?"_blank":"_top";
        $("a").attr("target", target);

        var w = $("body").width();
        var h = $("body").height();
        $(".button").width(w ? (w + "px") : "100%");
        $(".button").height(h ? (h + "px") : "100%");

        var update_button = function(res) {
	    try {
            var modhash = res.data.modhash;
            if (modhash) {
                reddit.logged = true;
                reddit.modhash = modhash;
            }
            var data = res.data.children[0].data;
            var realstate = 0; 
            var transition_score = function(callback) {
                return $(".score:visible").fadeOut(function() {
                          callback();
                          $(this).fadeIn().css("display", "");
                    });
            };
            /* add the thing's id */
            $(".thing").addClass("id-" + data.name);
            $(".bling a, a.bling").attr("href", data.permalink);
            if(data.likes) {
                real_state = 1;
                transition_score(function() {
                        $(".score.likes").html(point_label(data.score));
                        $(".score.unvoted").html(point_label(data.score-1));
                        $(".score.dislikes").html(point_label(data.score-2)); });
            }
            else if(data.likes == false) {
                real_state = -1;
                transition_score(function() {
                        $(".score.likes").html(point_label(data.score+2));
                        $(".score.unvoted").html(point_label(data.score+1));
                        $(".score.dislikes").html(point_label(data.score)); });
            }
            else {
                real_state = 0;
                transition_score(function() {
                        $(".score.likes").html(point_label(data.score+1));
                        $(".score.unvoted").html(point_label(data.score));
                        $(".score.dislikes").html(point_label(data.score-1)) });
            }

            /* if logged in, over-write the click event on arrows */
            $(".arrow").unbind("click").click(function() {
                    $(this).vote('', set_score, true);
                });
            if(reddit.logged && state != real_state) {
                if(state != null) {
                    $.request("vote", {id: data.name, dir : state});
                }
                else {
                    state = real_state;
                }
            }
            set_score_class();
            finalize_thing(data);
	    } catch(e) {
		make_submit();
	    };
        };

        var make_submit = function() {
            var submit = "/submit?url=" + encodeURIComponent(querydict.url);
            if (querydict.sr) {
                submit = "/r/" + querydict.sr + submit;
            }
            if (querydict.title) {
                submit += "&title=" + encodeURIComponent(querydict.title);
            }
            $(".score:visible").fadeOut(function() {
                    $(".score").html('<a class="submit" target="' +
                                     target + '" href="' +
                                     submit + '">submit</a>');
                    $(this).fadeIn().css("display", "");});
            $(".bling a, a.bling").attr("href", submit);
            $(".arrow").each(function() {
                    $(this).get(0).onclick = function() {
                        if(target == '_blank'){
                            window.open(submit, target);
                        } else {
                            window.parent.location = submit;
                       }
                    }
                });
        }

        var url = "/button_info.json";
        if (querydict.sr) {
            url = "/r/" + querydict.sr + url;
        }
        params = {};
        if ($.defined(querydict.url)) {
            params["url"] = querydict.url;
        }
        if ($.defined(querydict.id)) {
            params["id"] = querydict.id;
        }

        $.ajax({ type: "GET", url: url,
                    data: params, 
                    success : update_button,
                    error: make_submit,
                    dataType: "json"});
   }
  );

function point_label(x) {
    return x;
}

function set_score() {
    /* to be overridden for anything in the non-general case */
}

function finalize_thing(data) {
    /* to be overridden for anything in the non-general case */
}