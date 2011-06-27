#!/bin/bash

cd ~/reddit/r2
~/reddit/scripts/saferun.sh /tmp/update_sr_names.pid nice /usr/local/bin/paster --plugin=r2 run run.ini r2/lib/subreddit_search.py -c "load_all_reddits()"
