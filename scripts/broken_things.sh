#!/bin/bash

cd ~/reddit/r2
/usr/local/bin/paster run run.ini r2/lib/utils/utils.py -c "find_recent_broken_things(from_time=timeago('3 minutes'), to_time=timeago('10 seconds'), delete=True)"

