# The contents of this file are subject to the Common Public Attribution
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
# All portions of the code written by CondeNet are Copyright (c) 2006-2010
# CondeNet, Inc. All Rights Reserved.
################################################################################

from r2.lib.db.tdb_sql import make_metadata, index_str, create_table
from pylons import g
import sqlalchemy as sa

ENGINE_NAME = 'authorize'

ENGINE = g.dbm.get_engine(ENGINE_NAME)
METADATA = make_metadata(ENGINE)

gold_table = sa.Table('reddit_gold', METADATA,
                      sa.Column('trans_id', sa.String, nullable = False,
                                primary_key = True),
                      # status can be: invalid, unclaimed, claimed
                      sa.Column('status', sa.String, nullable = False),
                      sa.Column('date', sa.DateTime(timezone=True),
                                        nullable=False),
                      sa.Column('payer_email', sa.String, nullable = False),
                      sa.Column('paying_id', sa.String, nullable = False),
                      sa.Column('pennies', sa.Integer, nullable = False),
                      sa.Column('secret', sa.String, nullable = True),
                      sa.Column('account_id', sa.String, nullable = True))

indices = [index_str(gold_table, 'status', 'status'),
           index_str(gold_table, 'date', 'date'),
           index_str(gold_table, 'account_id', 'account_id'),
           index_str(gold_table, 'secret', 'secret', unique = True),
           index_str(gold_table, 'payer_email', 'payer_email')]
create_table(gold_table, indices)

def create_unclaimed_gold (trans_id, payer_email, paying_id,
                           pennies, secret, date):
    gold_table.insert().execute(trans_id=trans_id,
                                status="unclaimed",
                                payer_email=payer_email,
                                paying_id=paying_id,
                                pennies=pennies,
                                secret=secret,
                                date=date)

# caller is expected to engoldenate user
def create_claimed_gold (trans_id, payer_email, paying_id,
                         pennies, account, date):
    gold_table.insert().execute(trans_id=trans_id,
                                status="claimed",
                                payer_email=payer_email,
                                paying_id=paying_id,
                                pennies=pennies,
                                account_id=account._id,
                                date=date)

# returns the number of pennies paid, if there's valid unclaimed gold
# returns 0 if the ID is valid but the gold's already been claimed
# returns None if the ID was never valid
def claim_gold(secret, account_id):
    if not secret:
        return None

    # The donation email has the code at the end of the sentence,
    # so they might get sloppy and catch the period or some whitespace.
    secret = secret.strip(". ")

    rp = gold_table.update(sa.and_(gold_table.c.status == 'unclaimed',
                                   gold_table.c.secret == secret),
                           values = {
                                      gold_table.c.status: 'claimed',
                                      gold_table.c.account_id: account_id,
                                    },
                           ).execute()
    if rp.rowcount == 0:
        just_claimed = False
    elif rp.rowcount == 1:
        just_claimed = True
    else:
        raise ValueError("rowcount == %d?" % rp.rowcount)

    s = sa.select([gold_table.c.pennies],
                  gold_table.c.secret == secret,
                  limit = 1)
    rows = s.execute().fetchall()

    if not rows:
        return None
    elif just_claimed:
        return rows[0].pennies
    else:
        return 0

def check_by_email(email):
    s = sa.select([gold_table.c.status,
                           gold_table.c.secret,
                           gold_table.c.pennies,
                           gold_table.c.account_id],
                          gold_table.c.payer_email == email)
    return s.execute().fetchall()
