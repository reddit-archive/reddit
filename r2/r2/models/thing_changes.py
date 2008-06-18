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
from r2.config.databases import change_engine
import sqlalchemy as sa
from r2.lib.db.tdb_sql import make_metadata, settings
from r2.lib.utils import worker


def index_str(table, name, on, where = None):
    index_str = 'create index idx_%s_' % name
    index_str += table.name
    index_str += ' on '+ table.name + ' (%s)' % on
    if where:
        index_str += ' where %s' % where
    return index_str
    
def create_table(table, index_commands=None, force = False):
    t = table
    if settings.DB_CREATE_TABLES:
        if not t.engine.has_table(t.name) or force:
            try:
                t.create(checkfirst = False)
            except: pass
            if index_commands:
                for i in index_commands:
                    try:
                        t.engine.execute(i)
                    except: pass

def change_table(metadata):
    return sa.Table(settings.DB_APP_NAME + '_changes', metadata,
                    sa.Column('fullname', sa.String, nullable=False,
                              primary_key = True),
                    sa.Column('thing_type', sa.Integer, nullable=False),
                    sa.Column('date',
                              sa.DateTime(timezone = True),
                              default = sa.func.now(),
                              nullable = False)
                    )

def make_change_tables(force = False):
    metadata = make_metadata(change_engine)
    table = change_table(metadata)
    indices = [
        index_str(table, 'table', 'thing_type'),
        index_str(table, 'date', 'date')
        ]
    create_table(table, indices, force = force)
    return table

_change_table = make_change_tables()

def changed(thing):
    def _changed():
        d = dict(fullname = thing._fullname,
                 thing_type = thing._type_id)
        try:
            _change_table.insert().execute(d)
        except sa.exceptions.SQLError:
            t = _change_table
            t.update(t.c.fullname == thing._fullname,
                     values = {t.c.date: sa.func.now()}).execute()
    worker.do(_changed)


def _where(cls, min_date = None, max_date = None):
    t = _change_table
    where = [t.c.thing_type == cls._type_id]
    if min_date:
        where.append(t.c.date > min_date)
    if max_date:
        where.append(t.c.date < max_date)
    return sa.and_(*where)

def get_changed(cls, min_date = None, limit = None):
    t = _change_table
    res = sa.select([t.c.fullname, t.c.date], _where(cls, min_date = min_date),
                    order_by = t.c.date, limit = limit).execute()
    return res.fetchall()

def clear_changes(cls, min_date, max_date):
    t = _change_table
    t.delete(_where(cls, min_date = min_date, max_date = max_date)).execute()
