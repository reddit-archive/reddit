#!/bin/bash

cd ~/reddit/r2
/usr/local/bin/paster run run.ini -c "from r2.lib import promote; promote.Run()"
