#!/bin/bash -e
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
# All portions of the code written by reddit are Copyright (c) 2006-2013 reddit
# Inc. All Rights Reserved.
###############################################################################

###############################################################################
# The reddit installer
# --------------------
# This script installs a reddit stack suitable for development. DO NOT run
# this on a system that you use for other purposes as it may accidentally
# an important file.
#
# You can run this script as is, in which case a user "reddit" will be created
# and the code will be placed in its home directory. The various reddit-code
# components of the stack will run as this user.
#
# To change aspects of the install, modify the variables in the "Configuration"
# section below.
###############################################################################
set -e

###############################################################################
# Configuration
###############################################################################

# which user should run the reddit code
REDDIT_USER=reddit

# the group to run reddit code as
REDDIT_GROUP=nogroup

# the root directory in which to install the reddit code
REDDIT_HOME=/home/$REDDIT_USER

# which user should own the installed reddit files
# NOTE: if you change this option, you should move the mako template
# cache directory by changing the "cache_dir" option in the [app:main]
# section of the update files as $REDDIT_HOME will most likely
# not be writable by the reddit user.
REDDIT_OWNER=reddit

# the domain that you will connect to your reddit install with.
# MUST contain a . in it somewhere as browsers won't do cookies for dotless
# domains. an IP address will suffice if nothing else is available.
REDDIT_DOMAIN=${REDDIT_DOMAIN:-reddit.local}

###############################################################################
# Sanity Checks
###############################################################################
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: Must be run with root privileges."
    exit 1
fi

# seriously! these checks aren't here for no reason. the packages from the
# reddit ppa aren't built for anything but precise (12.04) right now, so
# if you try and use this install script on another release you're gonna
# have a bad time.
source /etc/lsb-release
if [ "$DISTRIB_ID" != "Ubuntu" -o "$DISTRIB_RELEASE" != "12.04" ]; then
    echo "ERROR: Only Ubuntu 12.04 is supported."
    exit 1
fi

###############################################################################
# Install prerequisites
###############################################################################
set -x

# create the user if non-existent
if ! id $REDDIT_USER &> /dev/null; then
    adduser --system $REDDIT_USER
fi

# aptitude configuration
APTITUDE_OPTIONS="-y" # limit bandwidth: -o Acquire::http::Dl-Limit=100"
export DEBIAN_FRONTEND=noninteractive

# run an aptitude update to make sure python-software-properties
# dependencies are found
apt-get update

# add the reddit ppa for some custom packages
apt-get install $APTITUDE_OPTIONS python-software-properties
apt-add-repository -y ppa:reddit/ppa

# pin the ppa -- packages present in the ppa will take precedence over
# ones in other repositories (unless further pinning is done)
cat <<HERE > /etc/apt/preferences.d/reddit
Package: *
Pin: release o=LP-PPA-reddit
Pin-Priority: 600
HERE

# grab the new ppas' package listings
apt-get update

# install prerequisites
cat <<PACKAGES | xargs apt-get install $APTITUDE_OPTIONS
git-core

python-dev
python-setuptools
python-routes
python-pylons
python-boto
python-tz
python-crypto
python-babel
cython
python-sqlalchemy
python-beautifulsoup
python-cssutils
python-chardet
python-psycopg2
python-pycountry
python-pycassa
python-imaging
python-pycaptcha
python-amqplib
python-pylibmc
python-bcrypt
python-snudown
python-l2cs
python-lxml
python-zope.interface
python-kazoo
python-stripe

nodejs
gettext
make
optipng
jpegoptim

memcached
postgresql
postgresql-client
rabbitmq-server
cassandra
haproxy
PACKAGES

###############################################################################
# Wait for all the services to be up
###############################################################################
# cassandra no longer auto-starts
service cassandra start

# check each port for connectivity
echo "Waiting for services to be available, see source for port meanings..."
# 11211 - memcache
# 5432 - postgres
# 5672 - rabbitmq
# 9160 - cassandra
for port in 11211 5432 5672 9160; do
    while ! nc -vz localhost $port; do
        sleep 1
    done
done

###############################################################################
# Install the reddit source repositories
###############################################################################
if [ ! -d $REDDIT_HOME ]; then
    mkdir -p $REDDIT_HOME
    chown $REDDIT_OWNER $REDDIT_HOME
fi

cd $REDDIT_HOME

if [ ! -d $REDDIT_HOME/reddit ]; then
    sudo -u $REDDIT_OWNER git clone https://github.com/reddit/reddit.git
fi

if [ ! -d $REDDIT_HOME/reddit-i18n ]; then
    sudo -u $REDDIT_OWNER git clone https://github.com/reddit/reddit-i18n.git
fi

###############################################################################
# Configure Cassandra
###############################################################################
if ! echo | cassandra-cli -h localhost -k reddit &> /dev/null; then
    echo "create keyspace reddit;" | cassandra-cli -h localhost -B
fi

cat <<CASS | cassandra-cli -B -h localhost -k reddit || true
create column family permacache with column_type = 'Standard' and
                                     comparator = 'BytesType';
CASS

###############################################################################
# Configure PostgreSQL
###############################################################################
SQL="SELECT COUNT(1) FROM pg_catalog.pg_database WHERE datname = 'reddit';"
IS_DATABASE_CREATED=$(sudo -u postgres psql -t -c "$SQL")

if [ $IS_DATABASE_CREATED -ne 1 ]; then
    cat <<PGSCRIPT | sudo -u postgres psql
CREATE DATABASE reddit WITH ENCODING = 'utf8' TEMPLATE template0;
CREATE USER reddit WITH PASSWORD 'password';
PGSCRIPT
fi

sudo -u postgres psql reddit < $REDDIT_HOME/reddit/sql/functions.sql

###############################################################################
# Configure RabbitMQ
###############################################################################
if ! rabbitmqctl list_vhosts | egrep "^/$"
then
    rabbitmqctl add_vhost /
fi

if ! rabbitmqctl list_users | egrep "^reddit"
then
    rabbitmqctl add_user reddit reddit
fi

rabbitmqctl set_permissions -p / reddit ".*" ".*" ".*"

###############################################################################
# Install and configure the reddit code
###############################################################################
cd $REDDIT_HOME/reddit/r2
sudo -u $REDDIT_OWNER make pyx # generate the .c files from .pyx
sudo -u $REDDIT_OWNER python setup.py build
python setup.py develop

cd $REDDIT_HOME/reddit-i18n/
sudo -u $REDDIT_OWNER python setup.py build
python setup.py develop
sudo -u $REDDIT_OWNER make

# this builds static files and should be run *after* languages are installed
# so that the proper language-specific static files can be generated.
cd $REDDIT_HOME/reddit/r2
sudo -u $REDDIT_OWNER make

cd $REDDIT_HOME/reddit/r2

if [ ! -f development.update ]; then
    cat > development.update <<DEVELOPMENT
# after editing this file, run "make ini" to
# generate a new development.ini

[DEFAULT]
debug = true

disable_ads = true
disable_captcha = true
disable_ratelimit = true
disable_require_admin_otp = true

page_cache_time = 0

set debug = true

domain = $REDDIT_DOMAIN

[server:main]
port = 8001
DEVELOPMENT
    chown $REDDIT_OWNER development.update
fi

if [ ! -f production.update ]; then
    cat > production.update <<PRODUCTION
# after editing this file, run "make ini" to
# generate a new production.ini

[DEFAULT]
debug = false
reload_templates = false
uncompressedJS = false

set debug = false

domain = $REDDIT_DOMAIN

[server:main]
port = 8001
PRODUCTION
    chown $REDDIT_OWNER production.update
fi

sudo -u $REDDIT_OWNER make ini

if [ ! -L run.ini ]; then
    sudo -u $REDDIT_OWNER ln -s development.ini run.ini
fi

###############################################################################
# haproxy
###############################################################################
if [ -e /etc/haproxy/haproxy.cfg ]; then
    BACKUP_HAPROXY=$(mktemp /etc/haproxy/haproxy.cfg.XXX)
    echo "Backing up /etc/haproxy/haproxy.cfg to $BACKUP_HAPROXY"
    cat /etc/haproxy/haproxy.cfg > $BACKUP_HAPROXY
fi

# make sure haproxy is enabled
cat > /etc/default/haproxy <<DEFAULT
ENABLED=1
DEFAULT

# configure haproxy
cat > /etc/haproxy/haproxy.cfg <<HAPROXY
global
    maxconn 100

frontend frontend 0.0.0.0:80
    mode http
    timeout client 10000
    option forwardfor except 127.0.0.1
    option httpclose

    default_backend dynamic

backend dynamic
    mode http
    timeout connect 4000
    timeout server 30000
    timeout queue 60000
    balance roundrobin

    server app01-8001 localhost:8001 maxconn 1
HAPROXY

# this will start it even if currently stopped
service haproxy restart

###############################################################################
# Upstart Environment
###############################################################################
CONSUMER_CONFIG_ROOT=$REDDIT_HOME/consumer-count.d
cp $REDDIT_HOME/reddit/upstart/* /etc/init/

if [ ! -f /etc/default/reddit ]; then
    cat > /etc/default/reddit <<DEFAULT
export REDDIT_ROOT=$REDDIT_HOME/reddit/r2
export REDDIT_INI=$REDDIT_HOME/reddit/r2/run.ini
export REDDIT_USER=$REDDIT_USER
export REDDIT_GROUP=$REDDIT_GROUP
export REDDIT_CONSUMER_CONFIG=$CONSUMER_CONFIG_ROOT
alias wrap-job=$REDDIT_HOME/reddit/scripts/wrap-job
alias manage-consumers=$REDDIT_HOME/reddit/scripts/manage-consumers
DEFAULT
fi

###############################################################################
# Queue Processors
###############################################################################
mkdir -p $CONSUMER_CONFIG_ROOT

function set_consumer_count {
    if [ ! -f $CONSUMER_CONFIG_ROOT/$1 ]; then
        echo $2 > $CONSUMER_CONFIG_ROOT/$1
    fi
}

set_consumer_count log_q 0
set_consumer_count cloudsearch_q 0
set_consumer_count scraper_q 0
set_consumer_count commentstree_q 1
set_consumer_count newcomments_q 1
set_consumer_count vote_link_q 1
set_consumer_count vote_comment_q 1

initctl emit reddit-start

###############################################################################
# Cron Jobs
###############################################################################
if [ ! -f /etc/cron.d/reddit ]; then
    cat > /etc/cron.d/reddit <<CRON
0    3 * * * root /sbin/start --quiet reddit-job-update_sr_names
30  16 * * * root /sbin/start --quiet reddit-job-update_reddits
0    * * * * root /sbin/start --quiet reddit-job-update_promos
*/5  * * * * root /sbin/start --quiet reddit-job-clean_up_hardcache
*    * * * * root /sbin/start --quiet reddit-job-email
*/2  * * * * root /sbin/start --quiet reddit-job-broken_things
*/2  * * * * root /sbin/start --quiet reddit-job-rising

# disabled by default, uncomment if you need these jobs
#*/2  * * * * root /sbin/start --quiet reddit-job-google_checkout
#0    0 * * * root /sbin/start --quiet reddit-job-update_gold_users
CRON
fi

###############################################################################
# All done!
###############################################################################
cd $REDDIT_HOME

cat <<CONCLUSION

Congratulations! reddit is now installed.

The reddit application code is managed with upstart, to see what's currently
running, run

    sudo initctl list | grep reddit

Cron jobs start with "reddit-job-" and queue processors start with
"reddit-consumer-". The crons are managed by /etc/cron.d/reddit. You can
initiate a restart of all the consumers by running:

    sudo initctl emit reddit-restart

or target specific ones:

    sudo initctl emit reddit-restart TARGET=scraper_q

See the GitHub wiki for more information on these jobs:

* https://github.com/reddit/reddit/wiki/Cron-jobs
* https://github.com/reddit/reddit/wiki/Services

Now that the core of reddit is installed, you may want to do some additional
steps:

* Ensure that $REDDIT_DOMAIN resolves to this machine.

* To populate the database with test data, run:

    cd $REDDIT_HOME/reddit/r2
    paster run run.ini r2/models/populatedb.py -c 'populate()'

* Manually run reddit-job-update_reddits immediately after populating the db
  or adding your own subreddits.
CONCLUSION
