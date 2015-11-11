/*
  requires Backbone
  requires r.errors
  requires r.models.validators.js
 */
!function(models, Backbone, undefined) {
  r.models = r.models || {};


  function ValidRule(attrName) {
    var vLength = r.models.validators.StringLength(attrName, 1, 50);

    return function validate(model) {
      var collection = model.collection;
      var isNew = model.isNew();

      if (collection) {
        if (isNew && collection.length >= collection.maxLength) {
          return r.errors.createAPIError(attrName, 'SR_RULE_TOO_MANY');
        }
      }

      var lengthError = vLength(model, attrName);

      if (lengthError) {
        return lengthError;
      }

      if (collection) {
        var query = {};
        query[model.idAttribute] = model.get(model.idAttribute);
        var matches = collection.where(query);
        var isDuplicate = matches && matches.length > (isNew ? 0 : 1);

        if (isDuplicate) {
          return r.errors.createAPIError(attrName, 'SR_RULE_EXISTS');
        }
      }
    };
  };


  var SubredditRule = Backbone.Model.extend({
    idAttribute: 'short_name',

    validators: [
      ValidRule('short_name'),
      r.models.validators.StringLength('description', 0, 500),
    ],

    api: {
      create: function(model) {
        var data = model.toJSON();
        return {
          url: 'add_subreddit_rule',
          data: data,
        };
      },

      update: function(model) {
        var data = model.toJSON();
        data.old_short_name = model._old_short_name;
        return {
          url: 'update_subreddit_rule',
          data: data,
        };
      },

      delete: function(model) {
        var data = { short_name: model._old_short_name };
        return {
          url: 'remove_subreddit_rule',
          data: data,
        };
      },
    },

    defaults: function() {
      return {
        short_name: '',
        description: '',
        md_description: '',
        priority: 0,
      };
    },

    initialize: function() {
      var short_name = this.get('short_name');
      this._old_short_name = short_name;

      if (!this.isNew()) {
        this.once('sync:create', function(model) {
          model.updateOldShortName();
        });
      }

      this.on('sync:update', function(model) {
        model.updateOldShortName();
      });
    },

    updateOldShortName: function() {
      this._old_short_name = this.get('short_name');
    },

    isNew: function() {
      return !this._old_short_name;
    },

    revert: function() {
      return this.set(this.previousAttributes(), { silent: true });
    },

    sync: function(method, model) {
      if (!this.api[method]) {
        throw new Error('Invalid action');
      }
      
      var req = this.api[method](model);
      req.data.api_type = 'json';
      this.trigger('request', this);

      $.request(req.url, req.data, function(res) {
        var errors = r.errors.getAPIErrorsFromResponse(res);
        
        if (errors) {
          this.trigger('error', this, errors);
        } else {
          this.trigger('sync:' + method, this);
          this.trigger('sync', this, method);
        }
      }.bind(this));
    },

    validate: function(attrs) {
      return r.models.validators.validate(this, this.validators);
    },
  });


  var SubredditRuleCollection = Backbone.Collection.extend({
    model: SubredditRule,
    maxLength: 10,    
  });


  r.models.SubredditRule = SubredditRule;
  r.models.SubredditRuleCollection = SubredditRuleCollection;
}(r, Backbone);
