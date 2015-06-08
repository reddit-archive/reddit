# Feature

`r2.config.feature` is reddit's feature flagging API. It lets us quickly
switch on and off features for specific segments of users and requests. It may
also be used in the future for ramping up big changes or A/B testing.

It's heavily simplified version of Etsy's feature framework, at
https://github.com/etsy/feature - if you're looking to add to this, you may
want to check there first to see if there's learning to be had. There almost
certainly is.

## Use

Using the feature API is simple. At its core:

```python

from r2.config import feature

if feature.is_enabled('some_flag'):
    result = do_new_thing()
else:
    result = do_old_thing()
```

Or in a mako template:

```html

% if feature.is_enabled('some_flag'):
  <strong>New thing!</strong>
% else:
  <span>Old thing.</span>
% endif
```


Along with a component in live_config, currently as an "on" or "off" symbol or JSON:

```ini

# Completely On
feature_some_flag = on

# Completely Off
feature_some_flag = off

# On for admin
feature_some_flag = {"admin": true}

# On for employees
feature_some_flag = {"employee": true}

# On for gold users
feature_some_flag = {"gold": true}

# On for users with the beta preference enabled
feature_some_flag = {"beta": true}

# On for logged in users
feature_some_flag = {"loggedin": true}

# On for logged out users
feature_some_flag = {"loggedout": true}

# On by URL, like ?feature=public_flag_name
feature_some_flag = {"url": "public_flag_name"}

# On by group of users
feature_some_flag = {"users": ["umbrae", "ajacksified"]}

# On when viewing certain subreddits
feature_some_flag = {"subreddits": ["wtf", "aww"]}

# On by subdomain
feature_some_flag = {"subdomains": ["beta"]}

# On by OAuth client IDs
feature_some_flag = {"oauth_clients: ["xyzABC123"]}

# On for a percentage of loggedin users (0 being no users, 100 being all of them)
feature_some_flag = {"percent_loggedin": 25}

# For both admin and a group of users
feature_some_flag = {"admin": true, "users": ["user1", "user2"]}

# Not yet available: rampups, variants for A/B, etc.
```

Since we're currently overloading live_config, each feature flag should be
prepended with `feature_` in the config. We may choose to make a live-updating
features block in the future. 


## When should I use this?

This is useful for a whole lot of reasons.

* To admin-launch something to the company for review before it goes live to
  everyone, and staging isn't a good fit.

* To release something to third party devs and mods before it goes live

* (eventually) to gradually add traffic to something that may have serious
  impact on load

* To guard something that you might need to quickly turn off for some reason
  or another. Load shedding, security, etc.


## Style guidelines

Copied essentially wholesale from Etsy's guidelines:

To make it easier to push features through the life cycle there are a
few coding guidelines to observe.

First, the feature name argument to the Feature methods (`is_enabled`,
`is_enabled_for`) should always be a string literal. This will make it easier
to find all the places that a particular feature is checked. If you find
yourself creating feature names at run time and then checking them, you’re
probably abusing the Feature system. Chances are in such a case you don’t
really want to be using the Feature API but rather simply driving your code
with some plain old config data.

Second, the results of the Feature methods should not be cached, such
as by calling `feature.is_enabled` once and storing the result in an
instance variable of some controller. The Feature machinery already
caches the results of the computation it does so it should already be
plenty fast to simply call `feature.is_enabled` whenever needed. This
will again aid in finding the places that depend on a particular feature.

Third, as a check that you’re using the Feature API properly, whenever
you have an if block whose test is a call to `feature.is_enabled`,
make sure that it would make sense to either remove the check and keep
the code or to delete the check and the code together. There shouldn’t
be bits of code within a block guarded by an is_enabled check that
needs to be salvaged if the feature is removed.


