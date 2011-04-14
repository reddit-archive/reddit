#!/bin/bash

cd ~/reddit/r2
/home/reddit/reddit/scripts/saferun.sh /tmp/rising.pid /usr/local/bin/paster run run.ini r2/lib/rising.py -c "set_rising()"
