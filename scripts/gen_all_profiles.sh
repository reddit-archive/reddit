#!/bin/bash

export USER=ri
export INI=production_batch.ini

# e.g. link or comment
export KIND="$1"
# e.g. prec01 for links, db02s8 for comments
export LINKDBHOST="$2"

# e.g. hour
export INTERVAL="$3"

# e.g., '("hour",)'
export TIMES="$4"

export PATH=/usr/local/pgsql/bin:/usr/local/bin:$HOME/bin:$PATH

export THING=/scratch/profile-thing-$KIND.$INTERVAL.dump
export DTHING=/scratch/profile-data-$KIND.$INTERVAL.dump

cd $HOME/reddit/r2

if [ -e $THING ]; then
  echo cannot start because $THING exists
  ls -l $THING
  exit 1
fi

trap "rm -f $THING $DTHING" SIGINT SIGTERM

# make this exist immediately to act as a lock
touch $THING

psql -F"\t" -A -t -d newreddit -U $USER -h $LINKDBHOST \
     -c "\\copy (select t.thing_id, 'thing', '$KIND',
                        t.ups, t.downs, t.deleted, t.spam, extract(epoch from t.date)
                   from reddit_thing_$KIND t
                  where not t.deleted
                     and t.date > now() - interval '1 $INTERVAL'
                  )
                  to '$THING'"

# get the min thing_id 
MINID=`head -n 1 $THING | awk '{print $1}'`

psql -F"\t" -A -t -d newreddit -U $USER -h $LINKDBHOST \
     -c "\\copy (select d.thing_id, 'data', '$KIND',
                        d.key, d.value
                   from reddit_data_$KIND d
                  where d.thing_id >= $MINID
                    and d.key = 'author_id'
                  )
                  to '$DTHING'"

function mrsort {
    #psort -T/mnt/tmp -S50m
    sort -T/scratch -S200m
}

function f {
    paster --plugin=r2 run $INI r2/lib/mr_account.py -c "$1"
}

cat $THING $DTHING | \
    mrsort | \
    f "join_links()" | \
    f "time_listings($TIMES)" | \
    mrsort | \
    f "write_permacache()"

rm $THING $DTHING
