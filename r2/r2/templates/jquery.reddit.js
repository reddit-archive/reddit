/* The reddit extension for jquery.  This file is intended to store
 * "utils" type function declarations and to add functionality to "$"
 * or "jquery" lookups. See 
 *   http://docs.jquery.com/Plugins/Authoring 
 * for the plug-in spec.
*/

jQuery.log = function(message) {
    if (window.console) 
        console.debug(message);
    else
        alert(message);
};
