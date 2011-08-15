/* Analytics, such as event tracking for google analytics */
$(function() {
    
    /* _trackEvent takes 2-3 parameters, which act like "tags". For
      our purposes:
       * category: Type of event (outbound link, embed video, etc.)
       * action: domain, for aggregating data by domain. Will be
                 "self.<subreddit>" for subreddits
       * label: Full URL of thing
    */
    
    function recordOutboundLink(link) {
        var category = "outbound link";
        var label = link.attr("srcurl") || link.attr("href");
        var action = parse_domain(label);
        
        /* Find the parent link <div> for info on promoted/self/etc */
        var link_entry = link.thing();
        
        if (link_entry.hasClass("self")) {
            category = "internal link";
        }
        
        if (link_entry.hasClass("promotedlink")) {
            category += " promoted";
        }
        
        _gaq.push(['_trackEvent', category, action, label]);
    }
    
    function recordExpando() {
    /* Track self-post or embedded item expanded */
        var expando = $(this);
        if (expando.hasClass("tracked")) {
            return;
        }
        
        var thing = expando.thing();
        var link = thing.find("a.title");
        
        var category = "embed";
        if (expando.hasClass("selftext")) {
            category += " self";
        } else if (expando.hasClass("video")) {
            category += " external";
        }
        
        var label = link.attr("srcurl") || link.attr("href");
        var action = parse_domain(label);
        
        _gaq.push(['_trackEvent', category, action, label]);
        
        expando.addClass("tracked");
    }
    
    $("body").delegate("a.title, a.thumbnail, a.reddit-link-title, .self a.comments",
                       "mouseup", function(e) {
        switch (e.which){
            /* Record left and middle clicks */
            case 1:
            /* CAUTION - left click case falls through to middle click */
            case 2:
                recordOutboundLink($(this));
                break;
            default:
                /* right-clicks and non-standard clicks ignored; no way to
                   know if context menu is used to pull up new tab or not */
                break;
        }
        
    });
    
    $("body").delegate("div.expando-button", "click", recordExpando);

});
