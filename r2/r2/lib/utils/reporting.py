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
# The Original Code is reddit.
#
# The Original Developer is the Initial Developer.  The Initial Developer of
# the Original Code is reddit Inc.
#
# All portions of the code written by reddit are Copyright (c) 2006-2013 reddit
# Inc. All Rights Reserved.
###############################################################################

import sqlalchemy as sa
import datetime as dt
import time
import smtplib

from r2.lib.utils import timeago
from r2.lib.db import tdb_sql
from r2.models.mail_queue import Email

class Report(object):
    """Class for creating reports based on reddit data"""
    def __init__(self, period=None, date=None):
        """Sets up the date storage."""
        self.period = period
        self.date = date

    def append_date_clause(self, table, select, all_time=None):
        """Create the date portion of a where clause based on the time
           period specified."""
        if all_time:
            return select
        if self.period and not self.date:
            select.append_whereclause(table.c.date > timeago(self.period))
        if self.date:
            seconds = 24 * 60 * 60
            wheredate = dt.datetime.strptime(self.date,"%Y%m%d")
            select.append_whereclause(table.c.date >= wheredate)
            select.append_whereclause((table.c.date < wheredate
                                + dt.timedelta(0, seconds)))
        return select

    def total_things(self, table_name, spam=None, all_time=None):
        """Return totals based on items in the thing tables."""
        t = tdb_sql.get_thing_table(table_name)[0]
        s = sa.select([sa.func.count(t.c.thing_id)])
        if spam:
            s.append_whereclause(t.c.spam==spam)
            s.append_whereclause(t.c.deleted=='f')
        s = self.append_date_clause(t, s, all_time=all_time)

        return s.execute().fetchone()[0]

    def total_relation(self, table_name, key, value=None, all_time=None):
        """Return totals based on relationship data."""
        tables = tdb_sql.get_rel_table('%s_account_link' % table_name)
        t1, t2 = tables[0], tables[3]

        s = sa.select([sa.func.count(t1.c.date)], 
                      sa.and_(t1.c.rel_id == t2.c.thing_id, t2.c.key == key))
        if value:
            s.append_whereclause(t2.c.value == value)
        s = self.append_date_clause(t1, s, all_time=all_time)
        return s.execute().fetchone()[0]

    def email_stats(self, table_name, all_time=None):
        """Calculate stats based on the email tables."""
        t = getattr(Email.handler, '%s_table' % table_name)
        s = sa.select([sa.func.count(t.c.kind)])
        s = self.append_date_clause(t, s, all_time=all_time)
        return s.execute().fetchone()[0]
                      
    def css_stats(self, val, all_time=None):
        """Create stats related to custom css and headers."""
        t = tdb_sql.get_thing_table('subreddit')[1]
        s = sa.select([sa.func.count(t.c.key)], t.c.key == val)
        return s.execute().fetchone()[0]
   

class TextReport(object):
    """Class for building text based reports"""
    def __init__(self, period, date):
        self.r = Report(period=period, date=date)
        self.rep = ''
        self.period = period
        self.date = date
        if period:
            self.phrase = "in the last"
            self.time = period
        if date:
            self.phrase = "on"
            self.time = self.pretty_date(date)

    def _thing_stats(self, thing, all_time=None):
        """return a header and a list of thing stats"""
        header = "%ss created " % thing
        if all_time:
            header += "since the beginning:"
        else:
            header += "%s %s:" % (self.phrase, self.time)
        columns = ['all', 'spam', 'non-spam']
        data = [str(self.r.total_things(thing, all_time=all_time)),
                str(self.r.total_things(thing, spam="t", all_time=all_time)),
                str(self.r.total_things(thing, spam="f", all_time=all_time))]
        return [[header], columns, data]

    def pretty_date(self, date):
        """Makes a pretty date from a date"""
        return time.strftime("%a, %b %d, %Y", time.strptime(date,"%Y%m%d"))

    def process_things(self, things, all_time=None):
        """builds a report for a list of things"""
        ret = ''
        for thing in things:
            (header, columns, data) = self._thing_stats(thing, all_time=all_time)
            ret += '\n'.join(['\t'.join(header), '\t'.join(columns), '\t'.join(data)])
            ret += '\n'
        return ret

    def process_relation(self, name, table_name, key, value, all_time=None):
        """build a report for a relation"""
        ret = ("%d\tTotal %s %s %s\n" % 
            (self.r.total_relation(table_name, key, value=value, all_time=all_time),
             name, self.phrase, self.time))
        return ret

    def process_other(self, type, name, table_name, all_time=None):
        """build other types of reports"""
        if type == 'email':
            f = self.r.email_stats
        if type == 'css':
            f = self.r.css_stats
        ret = ("%d\tTotal %s %s %s\n" % 
               (f(table_name, all_time=all_time), name, self.phrase, self.time))
        return ret

    def build(self, show_all_time=True):
        """build a complete text report"""
        rep = 'Subject: reddit stats %s %s\n\n' % (self.phrase, self.time)
        
        rep += self.process_things(['account','subreddit','link','message','comment'])
        
        rep += "\n"
        rep += self.process_relation('valid votes', 'vote', 'valid_thing', 't')
        rep += self.process_relation('organic votes', 'vote', 'organic', 't')
        rep += self.process_relation('votes', 'vote', 'valid_thing', None)
        rep += self.process_relation('reports', 'report', 'amount', None)

        rep += self.process_other('email', 'share emails sent', 'track')
        rep += self.process_other('email', 'share emails rejected', 'reject')

        if show_all_time:
            rep += self.process_other('css', 'subreddits with custom css', 
                                      'stylesheet_hash', all_time=True)
            rep += self.process_other('css', 'subreddits with a custom header', 
                                      'header', all_time=True)
            rep += "\n"
            rep += self.process_things(['account','subreddit','link','message','comment'], 
                                   all_time=True)

        return rep

def yesterday():
    """return yesterday's date"""
    return "%04d%02d%02d" % time.localtime(time.time() - 60*60*24)[0:3]
    
def run(period=None, date=None, show_all_time=True, 
        sender=None, recipients=None, smtpserver=None):
    if not date and not period:
        date = yesterday()
    report = TextReport(period, date).build(show_all_time=show_all_time)
    if sender:
        session = smtplib.SMTP(smtpserver)
        report = "To: %s\n" % ', '.join(recipients) + report
        smtpresult = session.sendmail(sender, recipients, report)
    else:
        print report
