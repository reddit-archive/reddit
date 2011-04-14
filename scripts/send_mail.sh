#!/bin/bash

cd ~/reddit/r2
/home/reddit/reddit/scripts/saferun.sh /tmp/share.pid /usr/local/bin/paster run run.ini r2/lib/emailer.py -c "send_queued_mail()"
