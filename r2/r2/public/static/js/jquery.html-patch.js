!function(jQuery, r) {
  // Mostly forklifted from jquery-migrate:
  // https://github.com/jquery/jquery-migrate/blob/e6bda6a84c294eb1319fceb48c09f51042c80892/src/core.js#L9
  function migrateWarn(message) {
    r.sendError(message, { tag: 'jquery-migrate-bad-html' })
  }

  var oldInit = jQuery.fn.init
  var rquickExpr = /^([^<]*)(<[\w\W]+>)([^>]*)$/

  // $(html) 'looks like html' rule change
  jQuery.fn.init = function(selector, context, rootjQuery) {
    var match

    if (selector && typeof selector === 'string' && !jQuery.isPlainObject(context) &&
         (match = rquickExpr.exec(jQuery.trim(selector))) && match[0]) {

      // This is an HTML string according to the 'old' rules is it still?
      if (selector.charAt(0) !== '<') {
        migrateWarn('$(html) HTML strings must start with "<" character')
      }

      if (match[3]) {
        migrateWarn('$(html) HTML text after last tag is ignored')
      }

      // Consistently reject any HTML-like string starting with a hash (#9521)
      // Note that this may break jQuery 1.6.x code that otherwise would work.
      if (match[0].charAt(0) === '#') {
        migrateWarn('HTML string cannot start with a "#" character')
      }

      // Now process using loose rules let pre-1.8 play too
      if (context && context.context) {
        // jQuery object as context parseHTML expects a DOM object
        context = context.context
      }

      if (jQuery.parseHTML) {
        return oldInit.call(this, jQuery.parseHTML(selector, context, true),
                            context, rootjQuery)
      }
    }

    return oldInit.apply(this, arguments)
  }

  jQuery.fn.init.prototype = jQuery.fn

}(jQuery, r)
