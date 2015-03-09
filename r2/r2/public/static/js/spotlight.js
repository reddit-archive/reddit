!function(r, _, $) {
  r.spotlight = {
    setup: function(organicLinks, interestProb, showPromo, srnames) {
      this.organics = [];
      this.lineup = [];
      this.interestProb = interestProb;
      this.showPromo = showPromo;
      this.srnames = srnames;
      this.lastPromoTimestamp = Date.now();
      this.MIN_PROMO_TIME = 1500;
      this.next = this._advance.bind(this, 1);
      this.prev = this._advance.bind(this, -1);
      this.$listing = $('.organic-listing');

      organicLinks.forEach(function(name) {
        this.organics.push(name);
        this.lineup.push({ fullname: name, });
      }, this);

      if (interestProb) {
        this.lineup.push('.interestbar');
      }

      if (!this.$listing.length) {
        return;
      }

      this.$listing.find('.arrow.prev').on('click', this.prev);
      this.$listing.find('.arrow.next').on('click', this.next);

      var selectedThing;
      var lastClickFullname = r.analytics.breadcrumbs.lastClickFullname();
      var $lastClickThing = $(lastClickFullname ? '.id-' + lastClickFullname : null);

      if ($lastClickThing.length && this.$listing.has($lastClickThing).length) {
        r.debug('restoring spotlight selection to last click');
        selectedThing = { fullname: lastClickFullname, };
      } else {
        selectedThing = this.chooseRandom();
      }

      this.lineup = _.chain(this.lineup)
        .reject(function(el) {
          return _.isEqual(selectedThing, el);
        })
        .shuffle()
        .unshift(selectedThing)
        .value();

      this.lineup.pos = 0;
      this._advance(0);

      if ('hidden' in document) {
        this.readyForNewPromo = !document.hidden;

        $(document).on('visibilitychange', function(e) {
          if (!document.hidden) {
            this.requestNewPromo();
          }
        }.bind(this));
      } else {
        this.readyForNewPromo = document.hasFocus();

        $(window).on('focus', this.requestNewPromo.bind(this));
      }
    },

    requestNewPromo: function() {
      // if the page loads in a background tab, this should be false.  In that
      // case, we don't want to load a new ad, as this will be the first view
      if (!this.readyForNewPromo) {
        this.readyForNewPromo = true;
        return;
      }

      // the ad will be stored as a promise
      if (!this.lineup[this.lineup.pos].promise) {
        return;
      }

      var $promotedLink = this.$listing.find('.promotedlink');
      var $clearLeft = $promotedLink.next('.clearleft');

      if (!$promotedLink.length || $promotedLink.is(':hidden') ||
          $promotedLink.offset().top < window.scrollY ||
          Date.now() - this.lastPromoTimestamp < this.MIN_PROMO_TIME) {
        return;
      }

      var newPromo = this.requestPromo();
      newPromo.then(function($promo) {
        if (!$promo || !$promo.length) {
          return;
        }

        var $link = $promo.eq(0);
        var fullname = $link.data('fullname');

        this.organics[this.lineup.pos] = fullname;
        this.lineup[this.lineup.pos] = newPromo;
        $promotedLink.add($clearLeft).remove();
        $promo.show();
        // force a redraw to prevent showing duplicate ads
        this.$listing.hide().show();
      }.bind(this));
    },

    requestPromo: function() {
      return $.ajax({
        type: 'POST',
        url: '/api/request_promo',
        timeout: 1000,
        data: {
          srnames: this.srnames,
          r: r.config.post_site,
        },
      }).pipe(function(promo) {
        if (promo) {
          this.lastPromoTimestamp = Date.now();
          var $item = $(promo);
          $item.hide().appendTo(this.$listing);
          return $item;
        } else {
          return false;
        }
      }.bind(this));
    },

    chooseRandom: function() {
      if (this.showPromo) {
        return this.requestPromo();
      } else if (Math.random() < this.interestProb) {
        return '.interestbar';
      } else {
        var name = this.organics[Math.floor(Math.random() * this.organics.length)];
        return { fullname: name, };
      }
    },

    _materialize: function(item) {
      if (!item || item instanceof $ || item.promise) {
        return item;
      }

      var itemSel;

      if (typeof item === 'string') {
        itemSel = item;
      } else if (item.campaign) {
        itemSel = '[data-cid="' + item.campaign + '"]';
      } else {
        itemSel = '[data-fullname="' + item.fullname + '"]';
      }

      var $item = this.$listing.find(itemSel);

      if ($item.length) {
        return $item;
      } else {
        r.error('unable to locate spotlight item', itemSel, item);
      }
    },

    _advancePos: function(dir) {
      return (this.lineup.pos + dir + this.lineup.length) % this.lineup.length;
    },

    _materializePos: function(pos) {
      return this.lineup[pos] = this._materialize(this.lineup[pos]);
    },

    _advance: function(dir) {
      var $nextprev = this.$listing.find('.nextprev');
      var $visible = this.$listing.find('.thing:visible');
      var nextPos = this._advancePos(dir);
      var $next = this._materializePos(nextPos);

      var showWorking = setTimeout(function() {
        $nextprev.toggleClass('working', $next.state && $next.state() == 'pending');
      }, 200);

      this.lineup.pos = nextPos;
      var $nextLoad = $.when($next);

      $nextLoad.always(function($next) {
        clearTimeout(showWorking);

        if (this.lineup.pos != nextPos) {
          // we've been passed!
          return;
        }

        if ($nextLoad.state() == 'rejected' || !$next) {
          if (this.lineup.length > 1) {
            this._advance(dir || 1);
            return;
          } else {
            this.$listing.hide();
            return;
          }
        }

        $nextprev.removeClass('working');
        this.$listing.removeClass('loading');

        // match the listing background to that of the displayed thing
        if ($next) {
          var nextColor = $next.css('background-color');
          if (nextColor) {
            this.$listing.css('background-color', nextColor);
          }
        }

        $visible.hide();
        $next.show();
        this.help($next);

        // prefetch forward and backward if advanced beyond default state
        if (this.lineup.pos != 0) {
          this._materializePos(this._advancePos(1));
          this._materializePos(this._advancePos(-1));
        }
      }.bind(this));
    },

    help: function($thing) {
      var $help = $('#spotlight-help');

      if (!$help.length) {
        return;
      }

      // this function can be called before the help bubble has initialized
      $(function() {
        $help.data('HelpBubble').hide(function() {
          $help.find('.help-section').hide();
          if ($thing.hasClass('promoted')) {
            $help.find('.help-promoted').show();
          } else if ($thing.hasClass('interestbar')) {
            $help.find('.help-interestbar').show();
          } else {
            $help.find('.help-organic').show();
          }
        });
      });
    },
  };
}(r, _, jQuery);
