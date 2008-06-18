# "The contents of this file are subject to the Common Public Attribution
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
# The Original Code is Reddit.
# 
# The Original Developer is the Initial Developer.  The Initial Developer of the
# Original Code is CondeNet, Inc.
# 
# All portions of the code written by CondeNet are Copyright (c) 2006-2008
# CondeNet, Inc. All Rights Reserved.
################################################################################
from __future__ import with_statement
from pylons import config
import pytz, os
from datetime import timedelta
from r2.lib.cache import LocalCache, Memcache, CacheChain
from r2.lib.db.stats import QueryStats
from r2.lib.translation import _get_languages

class Globals(object):

    int_props = ['page_cache_time',
                 'MIN_DOWN_LINK',
                 'MIN_UP_KARMA',
                 'MIN_DOWN_KARMA',
                 'MIN_RATE_LIMIT_KARMA',
                 'MIN_RATE_LIMIT_COMMENT_KARMA',
                 'HOT_PAGE_AGE',
                 'MODWINDOW',
                 'RATELIMIT',
                 'num_comments',
                 'max_comments',
                 'num_side_reddits',
                 ]
    
    bool_props = ['debug', 'translator', 
                  'template_debug',
                  'uncompressedJS']

    tuple_props = ['memcaches',
                   'rec_cache',
                   'admins',
                   'monitored_servers',
                   'default_srs',
                   'agents']

    def __init__(self, global_conf, app_conf, paths, **extra):
        """
        Globals acts as a container for objects available throughout
        the life of the application.

        One instance of Globals is created by Pylons during
        application initialization and is available during requests
        via the 'g' variable.
        
        ``global_conf``
            The same variable used throughout ``config/middleware.py``
            namely, the variables from the ``[DEFAULT]`` section of the
            configuration file.
            
        ``app_conf``
            The same ``kw`` dictionary used throughout
            ``config/middleware.py`` namely, the variables from the
            section in the config file for your application.
            
        ``extra``
            The configuration returned from ``load_config`` in 
            ``config/middleware.py`` which may be of use in the setup of
            your global variables.
            
        """

        def to_bool(x):
            return (x.lower() == 'true') if x else None
        
        def to_iter(name, delim = ','):
            return (x.strip() for x in global_conf.get(name, '').split(delim))


        # slop over all variables to start with
        for k, v in  global_conf.iteritems():
            if not k.startswith("_") and not hasattr(self, k):
                if k in self.int_props:
                    v = int(v)
                elif k in self.bool_props:
                    v = to_bool(v)
                elif k in self.tuple_props:
                    v = tuple(to_iter(k))
                setattr(self, k, v)

        # initialize caches
        mc = Memcache(self.memcaches)
        self.cache = CacheChain((LocalCache(), mc))

        self.rec_cache = Memcache(self.rec_cache)
        
        # set default time zone if one is not set
        self.tz = pytz.timezone(global_conf.get('timezone'))

        #make a query cache
        self.stats_collector = QueryStats()

        # set the modwindow
        self.MODWINDOW = timedelta(self.MODWINDOW)

        self.REDDIT_MAIN = bool(os.environ.get('REDDIT_MAIN'))

        # turn on for language support
        self.languages, self.lang_name = _get_languages()

        all_languages = self.lang_name.keys()
        all_languages.sort()
        self.all_languages = all_languages

        # load the md5 hashes of files under static
        static_files = os.path.join(paths.get('static_files'), 'static')
        self.static_md5 = {}
        if os.path.exists(static_files):
            for f in os.listdir(static_files):
                if f.endswith('.md5'):
                    key = f.strip('.md5')
                    f = os.path.join(static_files, f)
                    with open(f, 'r') as handle:
                        md5 = handle.read().strip('\n')
                    self.static_md5[key] = md5


        #set up the logging directory
        log_path = self.log_path
        process_iden = global_conf.get('scgi_port', 'default')
        if log_path:
            if not os.path.exists(log_path):
                os.makedirs(log_path)
            for fname in os.listdir(log_path):
                if fname.startswith(process_iden):
                    full_name = os.path.join(log_path, fname)
                    os.remove(full_name)

    def __del__(self):
        """
        Put any cleanup code to be run when the application finally exits 
        here.
        """
        pass
