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
# All portions of the code written by CondeNet are Copyright (c) 2006-2008
# CondeNet, Inc. All Rights Reserved.
################################################################################
from r2.lib.db.thing import Thing, Relation, NotFound
from r2.lib.db.userrel import UserRel
from r2.lib.db.operators import desc, lower
from r2.lib.memoize import memoize
from r2.models import Account
from pylons import c, g, request

class Award (Thing):
    _defaults = dict(
        awardtype = 'regular',
        )

    @classmethod
    @memoize('award.all_awards')
    def _all_awards_cache(cls):
        return [ a._id for a in Award._query(limit=100) ]

    @classmethod
    def _all_awards(cls, _update=False):
        all = Award._all_awards_cache(_update=_update)
        return Award._byID(all, data=True).values()

    @classmethod
    def _new(cls, codename, title, awardtype, imgurl):
#        print "Creating new award codename=%s title=%s imgurl=%s" % (
#            codename, title, imgurl)
        a = Award(codename=codename, title=title, awardtype=awardtype,
                  imgurl=imgurl)
        a._commit()
        Award._all_awards_cache(_update=True)

    @classmethod
    def _by_codename(cls, codename):
        q = cls._query(lower(Award.c.codename) == codename.lower())
        q._limit = 1
        award = list(q)

        if award:
            return cls._byID(award[0]._id, True)
        else:
            raise NotFound, 'Award %s' % codename

    @classmethod
    def give_if_needed(cls, codename, user, cup_expiration=None):
        """Give an award to a user, unless they already have it.
           Returns silently (except for g.log.debug) if the award
           doesn't exist"""

        try:
            award = Award._by_codename(codename)
        except NotFound:
            g.log.debug("No award named '%s'" % codename)
            return

        trophies = Trophy.by_account(user)

        for trophy in trophies:
            if trophy._thing2.codename == codename:
                g.log.debug("%s already has %s" % (user, codename))
                return

        Trophy._new(user, award, cup_expiration=cup_expiration)
        g.log.debug("Gave %s to %s" % (codename, user))

    @classmethod
    def take_away(cls, codename, user):
        """Takes an award out of a user's trophy case.  Returns silently
           (except for g.log.debug) if there's no such award."""

        found = False

        try:
            award = Award._by_codename(codename)
        except NotFound:
            g.log.debug("No award named '%s'" % codename)
            return

        trophies = Trophy.by_account(user)

        for trophy in trophies:
            if trophy._thing2.codename == codename:
                if found:
                    g.log.debug("%s had multiple %s awards!" % (user, codename))
                trophy._delete()
                Trophy.by_account(user, _update=True)
                Trophy.by_award(award, _update=True)
                found = True

        if found:
            g.log.debug("Took %s from %s" % (codename, user))
        else:
            g.log.debug("%s didn't have %s" % (user, codename))

class Trophy(Relation(Account, Award)):
    @classmethod
    def _new(cls, recipient, award, description = None,
             url = None, cup_expiration = None):

        # The "name" column of the relation can't be a constant or else a
        # given account would not be allowed to win a given award more than
        # once. So we're setting it to the string form of the timestamp.
        # Still, we won't have that date just yet, so for a moment we're
        # setting it to "trophy".

        t = Trophy(recipient, award, "trophy")

        t._name = str(t._date)

        if description:
            t.description = description

        if url:
            t.url = url

        if cup_expiration:
            recipient.extend_cup(cup_expiration)

        t._commit()
        Trophy.by_account(recipient, _update=True)
        Trophy.by_award(award, _update=True)

    @classmethod
    @memoize('trophy.by_account')
    def by_account(cls, account):
        q = Trophy._query(Trophy.c._thing1_id == account._id,
                          eager_load = True, thing_data = True,
                          data = True,
                          sort = desc('_date'))
        q._limit = 50
        return list(q)

    @classmethod
    @memoize('trophy.by_award')
    def by_award(cls, award):
        q = Trophy._query(Trophy.c._thing2_id == award._id,
                          eager_load = True, thing_data = True,
                          data = True,
                          sort = desc('_date'))
        q._limit = 500
        return list(q)
