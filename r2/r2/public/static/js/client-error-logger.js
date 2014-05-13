!function(global, $, r, _) {
  'use strict'

  var oldOnError = global.onerror

  global.onerror = function(message, file, line, character, errorType) {
    var exception = {
      message: message,
      file: file,
      line: line,
      character: character,
      errorType: errorType,
    }

    r.logging.sendException(exception)

    if (oldOnError) {
      oldOnError.apply(global, arguments)
    }
  }
}(this, jQuery, r, _)

