#!/bin/bash
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


# expects two environment variables
# REDDIT_ROOT = path to the root of the reddit public code; the directory with the Makefile
# REDDIT_CONFIG = path to the ini file to use

USER=ri
LINKDBHOST="$1"

# e.g. 'year'
INTERVAL="$2"

# e.g. '("hour","day","week","month","year")'
LISTINGS="$3"

# e.g. 5432 for default pg or 6543 for pgbouncer
DB_PORT=6543

FNAME=/scratch/top-thing-links.$INTERVAL.dump
DNAME=/scratch/top-data-links.$INTERVAL.dump

cd $REDDIT_ROOT

if [ -e $FNAME ]; then
  echo cannot start because $FNAME existss
  ls -l $FNAME
  exit 1
fi

trap "rm -f $FNAME $DNAME" SIGINT SIGTERM

# make this exist immediately to act as a lock
touch $FNAME

# Get the oldest thing id from the table
MINID=$(psql -F '\t' -A -t -d newreddit -U $USER -h $LINKDBHOST -p $DB_PORT -c "select thing_id from reddit_thing_link t WHERE  t.date > now() - interval '1 $INTERVAL' and t.date < now() ORDER BY thing_id LIMIT 1")

if [ -z $MINID ]; then
    echo MINID is null. Replication is likely behind.
    exit 1
fi


psql -F"\t" -A -t -d newreddit -U $USER -h $LINKDBHOST -p $DB_PORT \
     -c "\\copy (select t.thing_id, 'thing', 'link',
                        t.ups, t.downs, t.deleted, t.spam, extract(epoch from t.date)
                   from reddit_thing_link t
                  where not t.spam and not t.deleted
                     and t.thing_id >= $MINID
                  )
                  to '$FNAME'"
psql -F"\t" -A -t -d newreddit -U $USER -h $LINKDBHOST -p $DB_PORT \
     -c "\\copy (select t.thing_id, 'data', 'link',
                        d.key, d.value
                   from reddit_data_link d, reddit_thing_link t
                  where t.thing_id = d.thing_id
                    and not t.spam and not t.deleted
                    and d.key in ('url', 'sr_id')
                    and t.thing_id >= $MINID
                    and d.thing_id >= $MINID
                  ) to '$DNAME'"

function mrsort {
    #psort -T/mnt/tmp -S50m
    sort -T/scratch -S200m
}

function f {
    paster --plugin=r2 run $REDDIT_CONFIG r2/lib/mr_top.py -c "$1"
}

cat $FNAME $DNAME | \
    mrsort | \
    f "join_links()" | \
    f "time_listings($LISTINGS)" | \
    mrsort | \
    f "write_permacache()"

rm $FNAME $DNAME
