/* Analytics, such as event tracking for google analytics */
$(function() {
    
    function recordOutboundLink(link) {
        /* category/action/label are essentially "tags" used by
           google analytics */
        var category = "outbound link";
        var action = link.attr("domain");
        var label = link.attr("srcurl") || link.attr("href");
        
        /* Find the parent link <div> for info on promoted/self/etc */
        var link_entry = link.thing();
        
        if (link_entry.hasClass("selflink")){
            category = "internal link";
        }
        
        if (link_entry.hasClass("promotedlink")){
            category += " promoted";
        }
        
        _gaq.push(['_trackEvent', category, action, label]);
    }
    
    $("body").delegate("div.link .entry .title a.title, div.link a.thumbnail",
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

});
