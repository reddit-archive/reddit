# "The contents of this file are subject to the Common Public Attribution
# License Version 1.0. (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy of the License at
# http://code.reddit.com/LICENSE. The License is based on the Mozilla Public
# License Version 1.1, but Sections 14 and 15 have been added to cover use of
# software over a computer network and provide for limited attribution for the
# Original Developer. In addition, Exhibit A has been modified to be consistent
# with Exhibit B.
# 
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License for
# the specific language governing rights and limitations under the License.
# 
# The Original Code is Reddit.
# 
# The Original Developer is the Initial Developer.  The Initial Developer of the
# Original Code is CondeNet, Inc.
# 
# All portions of the code written by CondeNet are Copyright (c) 2006-2008
# CondeNet, Inc. All Rights Reserved.
################################################################################
from r2.models import Subreddit
from r2.lib.db.operators import desc

# def pop_reddits():
#     from r2.lib import count
#     counts = count.get_counts()
#     num_views = {}
#     for num, sr in counts.values():
#         info = num_views.setdefault(sr, [0, 0, 0])
#         info[0] += num
#         info[1] += 1
#         info[2] = info[0] / info[1]
#     pop = num_views.items()
#     pop.sort(key = lambda x: x[1][2], reverse = True)
#     return [i[0] for i in pop[:30]]
    
def all_srs():
    #can't use > 0 yet cause we'd have to cast, which requires some
    #changes to tdb_sql
    limit = 100
    q = Subreddit._query(Subreddit.c.valid_votes != 0,
                         limit = limit,
                         sort = desc('_date'),
                         data = True)
    srs = list(q)
    while srs:
        for sr in srs:
            yield sr
        srs = list(q._after(sr)) if len(srs) == limit else None

def update_sr(sr):
    count = sr.valid_votes
    if count != sr._downs and count > 0:
        sr._downs = count
        sr._commit()
        sr._incr('valid_votes', -count)
    elif count < 0:
        #just in case
        sr.valid_votes = 0
        sr._commit()

def run():
    for sr in all_srs():
        update_sr(sr)
