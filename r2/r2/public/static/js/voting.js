!function(r) {
  var UP_CLS = "up";
  var DOWN_CLS = "down";
  var theFakeClick;
  var MouseEvent;
  var createEvent;
  
  try {
    MouseEvent = window.MouseEvent;
    createEvent = document.createEvent.bind(document);

    if (MouseEvent) {
      theFakeClick = new MouseEvent('click', {bubbles: true});
    } else if (createEvent) {
      theFakeClick = createEvent('MouseEvent');
    } else {
      theFakeClick = {};
    }

    window.MouseEvent = function(type, init) {
      return theFakeClick;
    }

    document.createEvent = function(type) {
      if (type === 'MouseEvent' || type === 'MouseEvents') {
        return theFakeClick;
      } else {
        return createEvent(type);
      }
    }
  } catch (e) {
    // something went wrong
  }

  $(function() {
    $(document.body).on('click', '.arrow', function vote(e) {
      var $el = $(this);

      if (!r.config.logged) {
        return;
      }

      if ($el.hasClass('archived')) {
        $el.show_unvotable_message();
        return;
      }

      var $thing = $el.thing();
      var id = $thing.thing_id();
      var dir = $el.hasClass(UP_CLS) ? 1 : $el.hasClass(DOWN_CLS) ? -1 : 0;
      var isTrusted;

      if (!e || !e.originalEvent) {
        isTrusted = false;
      } else if ('isTrusted' in MouseEvent.prototype) {
        isTrusted = e.originalEvent.isTrusted;
      } else if (MouseEvent) {
        isTrusted = (e.originalEvent instanceof MouseEvent &&
                     e.originalEvent !== theFakeClick);
      }

      var voteData = {
        id: id,
        dir: dir,
        vh: r.config.vote_hash,
        isTrusted: isTrusted,
      };

      $.request("vote", voteData);
      $thing.updateThing({ voted: dir });
    });
  })
}(r);
