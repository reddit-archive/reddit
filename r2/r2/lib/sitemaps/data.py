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

"""Generates all the data used in making sitemaps and sitemap links.

Currently only supports subreddit links but will soon support comment links.
"""

import hashlib
import itertools

from pylons import app_globals as g

from r2.lib.db.operators import asc
from r2.lib.utils import fetch_things2, rate_limited_generator
from r2.models.subreddit import Subreddit


DB_CHUNK_SIZE = 50000
DB_RATE_LIMIT = DB_CHUNK_SIZE
EXPERIMENT_SUBREDDIT_SITEMAP = 'experiment-subreddit-sitemap'
# number of possible ways a subreddit can be partitioned for the experiment.
EXPERIMENT_BUCKET_COUNT = 20


def rate_limit_query(query):
    return rate_limited_generator(
        DB_RATE_LIMIT,
        fetch_things2(query, DB_CHUNK_SIZE),
    )

def is_part_of_experiment(subreddit):
    """Decide that this subreddit is part of the seo traffic experiment.

    At the moment the features system (r2/config/feature/README.md)
    is designed to be bucketed on a per user basis. We would like an
    experiment that is bucketed by subreddits instead. To do this we
    are going completely around the features system and instead
    bucketing the code here and communicating our hashing method with
    the data team.

    Much of this logic is borrowed from FeatureState.
    """
    key = '_'.join((EXPERIMENT_SUBREDDIT_SITEMAP, subreddit.name))
    hashed = hashlib.sha1(key)
    bucket = long(hashed.hexdigest(), 16) % EXPERIMENT_BUCKET_COUNT
    return bucket == 0

def is_subreddit_to_crawl(subreddit):
    return (subreddit.quarantine == False and
            subreddit.over_18 == False and
            is_part_of_experiment(subreddit))

def find_all_subreddits():
    iterator = rate_limit_query(Subreddit._query(
        *[Subreddit.c.type != type_ for type_ in Subreddit.private_types],
        sort=asc('_date')))
    return itertools.ifilter(is_subreddit_to_crawl, iterator)
