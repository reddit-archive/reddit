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
# The Original Code is Reddit.
#
# The Original Developer is the Initial Developer.  The Initial Developer of the
# Original Code is CondeNet, Inc.
#
# All portions of the code written by CondeNet are Copyright (c) 2006-2010
# CondeNet, Inc. All Rights Reserved.
################################################################################
from __future__ import with_statement
from pylons import config
import pytz, os, logging, sys, socket, re, subprocess, random
import signal
from datetime import timedelta, datetime
from urlparse import urlparse
import json
from sqlalchemy import engine
from sqlalchemy import event
from r2.lib.cache import LocalCache, SelfEmptyingCache
from r2.lib.cache import CMemcache, StaleCacheChain
from r2.lib.cache import HardCache, MemcacheChain, MemcacheChain, HardcacheChain
from r2.lib.cache import CassandraCache, CassandraCacheChain, CacheChain, CL_ONE, CL_QUORUM
from r2.lib.utils import thread_dump
from r2.lib.db.stats import QueryStats
from r2.lib.translation import get_active_langs
from r2.lib.lock import make_lock_factory
from r2.lib.manager import db_manager
from r2.lib.stats import Stats, CacheStats, StatsCollectingConnectionPool

class ConfigValue(object):
    @staticmethod
    def int(k, v, data):
        return int(v)

    @staticmethod
    def float(k, v, data):
        return float(v)

    @staticmethod
    def bool(k, v, data):
        return (v.lower() == 'true') if v else None

    @staticmethod
    def tuple(k, v, data):
        return tuple(ConfigValue.to_iter(v))

    @staticmethod
    def choice(k, v, data):
        if v not in data:
            raise ValueError("Unknown option for %r: %r not in %r" % (k, v, data))
        return data[v]

    @staticmethod
    def to_iter(v, delim = ','):
        return (x.strip() for x in v.split(delim) if x)

class ConfigValueParser(dict):
    def __init__(self, raw_data):
        dict.__init__(self, raw_data)
        self.config_keys = {}
        self.raw_data = raw_data

    def add_spec(self, spec):
        new_keys = []
        for parser, keys in spec.iteritems():
            # keys can be either a list or a dict
            for key in keys:
                assert key not in self.config_keys
                # if keys is a dict, the value is passed as extra data to the parser.
                extra_data = keys[key] if type(keys) is dict else None
                self.config_keys[key] = (parser, extra_data)
                new_keys.append(key)
        self._update_values(new_keys)

    def _update_values(self, keys):
        for key in keys:
            if key not in self.raw_data:
                continue

            value = self.raw_data[key]
            if key in self.config_keys:
                parser, extra_data = self.config_keys[key]
                value = parser(key, value, extra_data)
            self[key] = value

class Globals(object):
    spec = {

        ConfigValue.int: [
            'db_pool_size',
            'db_pool_overflow_size',
            'page_cache_time',
            'solr_cache_time',
            'num_mc_clients',
            'MIN_DOWN_LINK',
            'MIN_UP_KARMA',
            'MIN_DOWN_KARMA',
            'MIN_RATE_LIMIT_KARMA',
            'MIN_RATE_LIMIT_COMMENT_KARMA',
            'VOTE_AGE_LIMIT',
            'REPLY_AGE_LIMIT',
            'WIKI_KARMA',
            'HOT_PAGE_AGE',
            'MODWINDOW',
            'RATELIMIT',
            'QUOTA_THRESHOLD',
            'ADMIN_COOKIE_TTL',
            'ADMIN_COOKIE_MAX_IDLE',
            'num_comments',
            'max_comments',
            'max_comments_gold',
            'num_default_reddits',
            'num_query_queue_workers',
            'max_sr_images',
            'num_serendipity',
            'sr_dropdown_threshold',
            'comment_visits_period',
            'min_membership_create_community',
            'bcrypt_work_factor',
            'cassandra_pool_size',
        ],

        ConfigValue.float: [
            'min_promote_bid',
            'max_promote_bid',
            'usage_sampling',
            'statsd_sample_rate',
            'querycache_prune_chance',
        ],

        ConfigValue.bool: [
            'debug',
            'translator',
            'log_start',
            'sqlprinting',
            'template_debug',
            'reload_templates',
            'uncompressedJS',
            'enable_doquery',
            'use_query_cache',
            'write_query_queue',
            'css_killswitch',
            'db_create_tables',
            'disallow_db_writes',
            'exception_logging',
            'disable_ratelimit',
            'amqp_logging',
            'read_only_mode',
            'frontpage_dart',
            'allow_wiki_editing',
            'heavy_load_mode',
            's3_media_direct',
            'disable_captcha',
            'disable_ads',
            'static_pre_gzipped',
            'static_secure_pre_gzipped',
            'trust_local_proxies',
        ],

        ConfigValue.tuple: [
            'stalecaches',
            'memcaches',
            'permacache_memcaches',
            'rendercaches',
            'cassandra_seeds',
            'admins',
            'sponsors',
            'automatic_reddits',
            'agents',
            'allowed_css_linked_domains',
            'authorized_cnames',
            'hardcache_categories',
            's3_media_buckets',
            'allowed_pay_countries',
            'case_sensitive_domains',
        ],

        ConfigValue.choice: {
             'cassandra_rcl': {
                 'ONE': CL_ONE,
                 'QUORUM': CL_QUORUM
             },
             'cassandra_wcl': {
                 'ONE': CL_ONE,
                 'QUORUM': CL_QUORUM
             },
        },
    }

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

        global_conf.setdefault("debug", False)

        self.config = ConfigValueParser(global_conf)
        self.config.add_spec(self.spec)

        self.paths = paths

        self.running_as_script = global_conf.get('running_as_script', False)
        
        # turn on for language support
        if not hasattr(self, 'lang'):
            self.lang = 'en'
        self.languages, self.lang_name = \
            get_active_langs(default_lang=self.lang)

        all_languages = self.lang_name.keys()
        all_languages.sort()
        self.all_languages = all_languages
        
        # set default time zone if one is not set
        tz = global_conf.get('timezone', 'UTC')
        self.tz = pytz.timezone(tz)
        
        dtz = global_conf.get('display_timezone', tz)
        self.display_tz = pytz.timezone(dtz)

    def __getattr__(self, name):
        if not name.startswith('_') and name in self.config:
            return self.config[name]
        else:
            raise AttributeError

    def setup(self):
        # heavy load mode is read only mode with a different infobar
        if self.heavy_load_mode:
            self.read_only_mode = True

        if hasattr(signal, 'SIGUSR1'):
            # not all platforms have user signals
            signal.signal(signal.SIGUSR1, thread_dump)

        # initialize caches. Any cache-chains built here must be added
        # to cache_chains (closed around by reset_caches) so that they
        # can properly reset their local components

        localcache_cls = (SelfEmptyingCache if self.running_as_script
                          else LocalCache)
        num_mc_clients = self.num_mc_clients

        self.cache_chains = {}

        self.memcache = CMemcache(self.memcaches, num_clients = num_mc_clients)
        self.make_lock = make_lock_factory(self.memcache)

        self.stats = Stats(self.config.get('statsd_addr'),
                           self.config.get('statsd_sample_rate'))

        event.listens_for(engine.Engine, 'before_cursor_execute')(
            self.stats.pg_before_cursor_execute)
        event.listens_for(engine.Engine, 'after_cursor_execute')(
            self.stats.pg_after_cursor_execute)

        if not self.cassandra_seeds:
            raise ValueError("cassandra_seeds not set in the .ini")


        keyspace = "reddit"
        self.cassandra_pools = {
            "main":
                StatsCollectingConnectionPool(
                    keyspace,
                    stats=self.stats,
                    logging_name="main",
                    server_list=self.cassandra_seeds,
                    pool_size=self.cassandra_pool_size,
                    timeout=2,
                    max_retries=3,
                    prefill=False
                ),
        }

        perma_memcache = (CMemcache(self.permacache_memcaches, num_clients = num_mc_clients)
                          if self.permacache_memcaches
                          else None)
        self.permacache = CassandraCacheChain(localcache_cls(),
                                              CassandraCache('permacache',
                                                             self.cassandra_pools[self.cassandra_default_pool],
                                                             read_consistency_level = self.cassandra_rcl,
                                                             write_consistency_level = self.cassandra_wcl),
                                              memcache = perma_memcache,
                                              lock_factory = self.make_lock)

        self.cache_chains.update(permacache=self.permacache)

        # hardcache is done after the db info is loaded, and then the
        # chains are reset to use the appropriate initial entries

        if self.stalecaches:
            self.cache = StaleCacheChain(localcache_cls(),
                                         CMemcache(self.stalecaches, num_clients=num_mc_clients),
                                         self.memcache)
        else:
            self.cache = MemcacheChain((localcache_cls(), self.memcache))
        self.cache_chains.update(cache=self.cache)

        self.rendercache = MemcacheChain((localcache_cls(),
                                          CMemcache(self.rendercaches,
                                                    noreply=True, no_block=True,
                                                    num_clients = num_mc_clients)))
        self.cache_chains.update(rendercache=self.rendercache)

        self.thing_cache = CacheChain((localcache_cls(),))
        self.cache_chains.update(thing_cache=self.thing_cache)

        #load the database info
        self.dbm = self.load_db_params()

        # can't do this until load_db_params() has been called
        self.hardcache = HardcacheChain((localcache_cls(),
                                         self.memcache,
                                         HardCache(self)),
                                        cache_negative_results = True)
        self.cache_chains.update(hardcache=self.hardcache)

        # I know this sucks, but we need non-request-threads to be
        # able to reset the caches, so we need them be able to close
        # around 'cache_chains' without being able to call getattr on
        # 'g'
        cache_chains = self.cache_chains.copy()
        def reset_caches():
            for name, chain in cache_chains.iteritems():
                chain.reset()
                chain.stats = CacheStats(self.stats, name)

        self.reset_caches = reset_caches
        self.reset_caches()

        #make a query cache
        self.stats_collector = QueryStats()

        # set the modwindow
        self.MODWINDOW = timedelta(self.MODWINDOW)

        self.REDDIT_MAIN = bool(os.environ.get('REDDIT_MAIN'))

        origin_prefix = self.domain_prefix + "." if self.domain_prefix else ""
        self.origin = "http://" + origin_prefix + self.domain
        self.secure_domains = set([urlparse(self.payment_domain).netloc])
        
        self.trusted_domains = set([self.domain])
        self.trusted_domains.update(self.authorized_cnames)
        if self.https_endpoint:
            https_url = urlparse(self.https_endpoint)
            self.secure_domains.add(https_url.netloc)
            self.trusted_domains.add(https_url.hostname)


        # load the unique hashed names of files under static
        static_files = os.path.join(self.paths.get('static_files'), 'static')
        names_file_path = os.path.join(static_files, 'names.json')
        if os.path.exists(names_file_path):
            with open(names_file_path) as handle:
                self.static_names = json.load(handle)
        else:
            self.static_names = {}

        #setup the logger
        self.log = logging.getLogger('reddit')
        self.log.addHandler(logging.StreamHandler())
        if self.debug:
            self.log.setLevel(logging.DEBUG)
        else:
            self.log.setLevel(logging.INFO)

        # set log level for pycountry which is chatty
        logging.getLogger('pycountry.db').setLevel(logging.CRITICAL)

        if not self.media_domain:
            self.media_domain = self.domain
        if self.media_domain == self.domain:
            print ("Warning: g.media_domain == g.domain. " +
                   "This may give untrusted content access to user cookies")

        self.reddit_host = socket.gethostname()
        self.reddit_pid  = os.getpid()

        for arg in sys.argv:
            tokens = arg.split("=")
            if len(tokens) == 2:
                k, v = tokens
                self.log.debug("Overriding g.%s to %s" % (k, v))
                setattr(self, k, v)

        #if we're going to use the query_queue, we need amqp
        if self.write_query_queue and not self.amqp_host:
            raise Exception("amqp_host must be defined to use the query queue")

        # This requirement doesn't *have* to be a requirement, but there are
        # bugs at the moment that will pop up if you violate it
        if self.write_query_queue and not self.use_query_cache:
            raise Exception("write_query_queue requires use_query_cache")

        # try to set the source control revision number
        try:
            self.version = subprocess.check_output(["git", "rev-parse", "HEAD"])
        except subprocess.CalledProcessError, e:
            self.log.info("Couldn't read source revision (%r)" % e)
            self.version = self.short_version = '(unknown)'
        else:
            self.short_version = self.version[:7]

        if self.log_start:
            self.log.error("reddit app %s:%s started %s at %s" %
                           (self.reddit_host, self.reddit_pid,
                            self.short_version, datetime.now()))


    def load_db_params(self):
        self.databases = tuple(ConfigValue.to_iter(self.config.raw_data['databases']))
        self.db_params = {}
        if not self.databases:
            return

        dbm = db_manager.db_manager()
        db_param_names = ('name', 'db_host', 'db_user', 'db_pass', 'db_port',
                          'pool_size', 'max_overflow')
        for db_name in self.databases:
            conf_params = ConfigValue.to_iter(self.config.raw_data[db_name + '_db'])
            params = dict(zip(db_param_names, conf_params))
            if params['db_user'] == "*":
                params['db_user'] = self.db_user
            if params['db_pass'] == "*":
                params['db_pass'] = self.db_pass
            if params['db_port'] == "*":
                params['db_port'] = self.db_port

            if params['pool_size'] == "*":
                params['pool_size'] = self.db_pool_size
            if params['max_overflow'] == "*":
                params['max_overflow'] = self.db_pool_overflow_size

            dbm.setup_db(db_name, g_override=self, **params)
            self.db_params[db_name] = params

        dbm.type_db = dbm.get_engine(self.config.raw_data['type_db'])
        dbm.relation_type_db = dbm.get_engine(self.config.raw_data['rel_type_db'])

        def split_flags(raw_params):
            params = []
            flags = {}

            for param in raw_params:
                if not param.startswith("!"):
                    params.append(param)
                else:
                    key, sep, value = param[1:].partition("=")
                    if sep:
                        flags[key] = value
                    else:
                        flags[key] = True

            return params, flags

        prefix = 'db_table_'
        self.predefined_type_ids = {}
        for k, v in self.config.raw_data.iteritems():
            if not k.startswith(prefix):
                continue

            params, table_flags = split_flags(ConfigValue.to_iter(v))
            name = k[len(prefix):]
            kind = params[0]
            server_list = self.config.raw_data["db_servers_" + name]
            engines, flags = split_flags(ConfigValue.to_iter(server_list))

            typeid = table_flags.get("typeid")
            if typeid:
                self.predefined_type_ids[name] = int(typeid)

            if kind == 'thing':
                dbm.add_thing(name, dbm.get_engines(engines),
                              **flags)
            elif kind == 'relation':
                dbm.add_relation(name, params[1], params[2],
                                 dbm.get_engines(engines),
                                 **flags)
        return dbm

    def __del__(self):
        """
        Put any cleanup code to be run when the application finally exits 
        here.
        """
        pass

