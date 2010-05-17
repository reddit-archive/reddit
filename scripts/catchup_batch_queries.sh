#!/bin/bash

cd ~/reddit/r2
/usr/local/bin/paster run run.ini r2/lib/utils/utils.py -c "from r2.lib.db import queries; queries.catch_up_batch_queries()"
