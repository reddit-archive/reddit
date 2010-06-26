#!/bin/bash

cd ~/reddit/r2
/usr/local/bin/saferun /tmp/updatereddits.pid nice /usr/local/bin/paster --plugin=r2 run production.ini r2/lib/sr_pops.py -c "run()"
