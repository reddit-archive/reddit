#!/bin/bash

USER=ri
LINKDBHOST=prec01

# e.g. 'year'
INTERVAL="$1"

# e.g. '("hour","day","week","month","year")'
LISTINGS="$2"

INI=production_batch.ini

FNAME=links.$INTERVAL.joined
DNAME=data.$INTERVAL.joined
export PATH=/usr/local/pgsql/bin:/usr/local/bin:$PATH

cd $HOME/reddit/r2

if [ -e $FNAME ]; then
  echo cannot start because $FNAME existss
  exit 1
fi

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

cat $FNAME $DNAME | sort -T. -S200m | \
    paster --plugin=r2 run $INI r2/lib/mr_top.py -c "join_links()" | \
    paster --plugin=r2 run $INI r2/lib/mr_top.py -c "time_listings($LISTINGS)" | \
    sort -T. -S200m | \
    paster --plugin=r2 run $INI r2/lib/mr_top.py -c "write_permacache()"


rm $FNAME $DNAME

