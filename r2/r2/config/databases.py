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
from r2.lib.manager import db_manager
from pylons import g
try:
    #TODO: move?
    from r2admin.config.databases import *
except:
    pass

tz = g.tz

dbm = db_manager.db_manager()

main_engine = db_manager.get_engine(g.main_db_name,
                                    db_host = g.main_db_host,
                                    db_user = g.main_db_user,
                                    db_pass = g.main_db_pass)

comment_engine = db_manager.get_engine(g.comment_db_name,
                                    db_host = g.comment_db_host,
                                    db_user = g.comment_db_user,
                                    db_pass = g.comment_db_pass)

vote_engine = db_manager.get_engine(g.vote_db_name,
                                    db_host = g.vote_db_host,
                                    db_user = g.vote_db_user,
                                    db_pass = g.vote_db_pass)

change_engine = db_manager.get_engine(g.change_db_name,
                                      db_host = g.change_db_host,
                                      db_user = g.change_db_user,
                                      db_pass = g.change_db_pass,
                                      pool_size = 2,
                                      max_overflow = 2)

dbm.type_db = main_engine
dbm.relation_type_db = main_engine

dbm.thing('link', main_engine, main_engine)
dbm.thing('account', main_engine, main_engine)
dbm.thing('message', main_engine, main_engine)

dbm.relation('savehide', 'account', 'link', main_engine)
dbm.relation('click', 'account', 'link', main_engine)

dbm.thing('comment', comment_engine, comment_engine)

dbm.thing('subreddit', comment_engine, comment_engine)
dbm.relation('srmember', 'subreddit', 'account', comment_engine)

dbm.relation('friend', 'account', 'account', comment_engine)

dbm.relation('vote_account_link', 'account', 'link', vote_engine)
dbm.relation('vote_account_comment', 'account', 'comment', vote_engine)

dbm.relation('inbox_account_comment', 'account', 'comment', comment_engine)
dbm.relation('inbox_account_message', 'account', 'message', main_engine)

dbm.relation('report_account_link', 'account', 'link', main_engine)
dbm.relation('report_account_comment', 'account', 'comment', comment_engine)
dbm.relation('report_account_message', 'account', 'message', main_engine)
dbm.relation('report_account_subreddit', 'account', 'subreddit', main_engine)


