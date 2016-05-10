# The contents of this file are subject to the Common Public Attribution
# License Version 1.0. (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy of the License at
# http://code.reddit.com/LICENSE. The License is based on the Mozilla Public
# License Version 1.1, but Sections 14 and 15 have been added to cover use of
# software over a computer network and provide for limited attribution for the
# Original Developer. In addition, Exhibit A has been modified to be consistent
# with Exhibit B.
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License for
# the specific language governing rights and limitations under the License.
#
# The Original Code is reddit.
#
# The Original Developer is the Initial Developer.  The Initial Developer of
# the Original Code is reddit Inc.
#
# All portions of the code written by reddit are Copyright (c) 2006-2015 reddit
# Inc. All Rights Reserved.
###############################################################################

from r2.config.feature.state import FeatureState
from r2.config.feature.world import World
from r2.lib.hooks import HookRegistrar

feature_hooks = HookRegistrar()

_world = World()
_featurestate_cache = {}


def is_enabled(name, user=None, subreddit=None):
    """Test and return whether a given feature is enabled for this request.

    If `feature` is not found, returns False.

    The optional arguments allow overriding that you generally don't want, but
    is useful outside of request contexts - cron jobs and the like.

    :param name string - a given feature name
    :param user - (optional) an Account
    :param subreddit - (optional) a Subreddit
    :return bool
    """
    if not user:
        user = _world.current_user()
    if not subreddit:
        subreddit = _world.current_subreddit()
    subdomain = _world.current_subdomain()
    oauth_client = _world.current_oauth_client()

    return _get_featurestate(name).is_enabled(
        user=user,
        subreddit=subreddit,
        subdomain=subdomain,
        oauth_client=oauth_client,
    )

def variant(name, user=None):
    """Return which variant of an experiment a user is part of.

    If the experiment is not found, has no variants, or the user is not part of
    any of them (control), return None.

    :param name string - an experiment (feature) name
    :param user - (optional) an Account.  Defaults to the currently signed in
                  user.
    :return string, or None if not part of an experiment
    """
    if not user:
        user = _world.current_user()

    return _get_featurestate(name).variant(user)

def all_enabled(user=None):
    """Return a list of enabled features and experiments for the user.
    
    Provides the user's assigned variant and the experiment ID for experiments.

    This does not trigger bucketing events, so it should not be used for
    feature flagging purposes on the server. It is meant to let clients
    condition features on experiment variants. Those clients should manually
    send the appropriate bucketing events.

    :param user - (optional) an Account. Defaults to None, for which we
                  determine logged-out features.
    :return dict - a dictionary mapping enabled feature keys to True or to the
                   experiment/variant information
    """
    features = FeatureState.get_all(_world)

    # Get enabled features and experiments
    active = {}
    for feature in features:
        experiment = feature.config.get('experiment')
        if experiment:
            # Get experiment names, ids, and assigned variants, leaving out
            # experiments for which this user is excluded
            variant = feature.variant(user)
            if variant:
                active[feature.name] = {
                    'experiment_id': experiment.get('experiment_id'),
                    'variant': variant
                }
        elif feature.is_enabled(user):
                active[feature.name] = True

    return active

@feature_hooks.on('worker.live_config.update')
def clear_featurestate_cache():
    global _featurestate_cache
    _featurestate_cache = {}


def _get_featurestate(name):
    """Get a FeatureState object for this feature, creating it if necessary.

    :param name string - a given feature name
    :return FeatureState
    """
    if name not in _featurestate_cache:
        _featurestate_cache[name] = FeatureState(name, _world)

    return _featurestate_cache[name]
