#!/bin/bash

cd ~/reddit/r2
/usr/local/bin/saferun /tmp/rising.pid /usr/local/bin/paster run run.ini r2/lib/rising.py -c "set_rising()"
