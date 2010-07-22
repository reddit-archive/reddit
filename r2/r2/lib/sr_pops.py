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
from pylons import g
from r2.models import Subreddit
from r2.lib.db.operators import desc
from r2.lib import count
from r2.lib.memoize import memoize
from r2.lib.utils import fetch_things2, flatten, keymap

# the length of the stored per-language list
limit = 1000

def cached_srs_key(lang, over18_state):
    assert over18_state in ('no_over18', 'allow_over18', 'only_over18')
    return str('sr_pop_%s_%s' % (lang, over18_state))

def set_downs():
    sr_counts = count.get_sr_counts()
    names = [k for k, v in sr_counts.iteritems() if v != 0]
    srs = Subreddit._by_fullname(names)
    for name in names:
        sr,c = srs[name], sr_counts[name]
        if c != sr._downs and c > 0:
            sr._downs = max(c, 0)
            sr._commit()
    count.clear_sr_counts(names)

def cache_lists():
    def _chop(srs):
        srs.sort(key=lambda s: s._downs, reverse=True)
        return srs[:limit]

    # bylang    =:= dict((lang, over18_state) -> [Subreddit])
    # lang      =:= all | lang()
    # nsfwstate =:= no_over18 | allow_over18 | only_over18
    bylang = {}

    for sr in fetch_things2(Subreddit._query(sort=desc('_date'),
                                             data=True)):
        aid = getattr(sr, 'author_id', None)
        if aid is not None and aid < 0:
            # skip special system reddits like promos
            continue

        if sr.type not in ('public', 'restricted'):
            # skips reddits that can't appear in the default list
            # because of permissions
            continue

        for lang in 'all', sr.lang:
            over18s = ['allow_over18']
            if sr.over_18:
                over18s.append('only_over18')
            else:
                over18s.append('no_over18')

            for over18 in over18s:
                k = (lang, over18)
                bylang.setdefault(k, []).append(sr)

                # keep the lists small while we work
                if len(bylang[k]) > limit*2:
                    bylang[k] = _chop(bylang[k])

    for (lang, over18), srs in bylang.iteritems():
        srs = _chop(srs)
        sr_tuples = map(lambda sr: (sr._downs, sr.allow_top, sr._id), srs)

        print "For %s/%s setting %s" % (lang, over18,
                                        map(lambda sr: sr.name, srs[:50]))

        g.permacache.set(cached_srs_key(lang, over18), sr_tuples)

def run():
    set_downs()
    cache_lists()

def pop_reddits(langs, over18, over18_only, filter_allow_top = False):
    if not over18:
        over18_state = 'no_over18'
    elif over18_only:
        over18_state = 'only_over18'
    else:
        over18_state = 'allow_over18'

    keys = map(lambda lang: cached_srs_key(lang, over18_state), langs)

    # dict(lang_key -> [(_downs, allow_top, sr_id)])
    srs = g.permacache.get_multi(keys)

    tups = flatten(srs.values())

    if filter_allow_top:
        # remove the folks that have opted out of being on the front
        # page as appropriate
        tups = filter(lambda tpl: tpl[1], tups)

    if len(srs) > 1:
        # if there was only one returned, it's already sorted
        tups.sort(key = lambda tpl: tpl[0], reverse=True)

    return map(lambda tpl: tpl[2], tups)
