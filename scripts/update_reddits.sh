#!/bin/bash

cd ~/reddit/r2
/home/reddit/reddit/scripts/saferun.sh /tmp/updatereddits.pid nice /usr/local/bin/paster --plugin=r2 run run.ini r2/lib/sr_pops.py -c "run()"
