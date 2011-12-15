#!/bin/bash

USER=ri
LINKDBHOST=pg-05s0

# e.g. 'year'
INTERVAL="$1"

# e.g. '("hour","day","week","month","year")'
LISTINGS="$2"

INI=production_batch.ini

FNAME=/scratch/top-thing-links.$INTERVAL.dump
DNAME=/scratch/top-data-links.$INTERVAL.dump
export PATH=/usr/local/pgsql/bin:/usr/local/bin:$HOME/bin:$PATH

cd $HOME/reddit/r2

if [ -e $FNAME ]; then
  echo cannot start because $FNAME existss
  ls -l $FNAME
  exit 1
fi

trap "rm -f $FNAME $DNAME" SIGINT SIGTERM

# make this exist immediately to act as a lock
touch $FNAME

psql -F"\t" -A -t -d newreddit -U $USER -h $LINKDBHOST \
     -c "\\copy (select t.thing_id, 'thing', 'link',
                        t.ups, t.downs, t.deleted, t.spam, extract(epoch from t.date)
                   from reddit_thing_link t
                  where not t.spam and not t.deleted
                     and t.date > now() - interval '1 $INTERVAL'
                  )
                  to '$FNAME'"
psql -F"\t" -A -t -d newreddit -U $USER -h $LINKDBHOST \
     -c "\\copy (select t.thing_id, 'data', 'link',
                        d.key, d.value
                   from reddit_data_link d, reddit_thing_link t
                  where t.thing_id = d.thing_id
                    and not t.spam and not t.deleted
                    and (d.key = 'url' or d.key = 'sr_id')
                    and t.date > now() - interval '1 $INTERVAL'
                  ) to '$DNAME'"

function mrsort {
    #psort -T/mnt/tmp -S50m
    sort -T/scratch -S200m
}

function f {
    paster --plugin=r2 run $INI r2/lib/mr_top.py -c "$1"
}

cat $FNAME $DNAME | \
    mrsort | \
    f "join_links()" | \
    f "time_listings($LISTINGS)" | \
    mrsort | \
    f "write_permacache()"

rm $FNAME $DNAME
