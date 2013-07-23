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

"""
Setup your Routes options here
"""
from routes import Mapper
from pylons import config


def not_in_sr(environ, results):
    return ('subreddit' not in environ and
            'sub_domain' not in environ and
            'domain' not in environ)


# FIXME: submappers with path prefixes are broken in Routes 1.11. Once we
# upgrade, we should be able to replace this ugliness with submappers.
def partial_connect(mc, **override_args):
    def connect(path, **kwargs):
        if 'path_prefix' in override_args:
            path = override_args['path_prefix'] + path
        kwargs.update(override_args)
        mc(path, **kwargs)
    return connect


def make_map():
    map = Mapper()
    mc = map.connect

    for plugin in reversed(config['r2.plugins']):
        plugin.add_routes(mc)

    mc('/admin/', controller='awards')

    mc('/login', controller='forms', action='login')
    mc('/register', controller='forms', action='register')
    mc('/logout', controller='forms', action='logout')
    mc('/verify', controller='forms', action='verify')
    mc('/adminon', controller='forms', action='adminon')
    mc('/adminoff', controller='forms', action='adminoff')
    mc('/submit', controller='front', action='submit')

    mc('/over18', controller='post', action='over18')

    mc('/rules', controller='front', action='rules')
    mc('/sup', controller='front', action='sup')
    mc('/traffic', controller='front', action='site_traffic')
    mc('/traffic/languages/:langcode', controller='front',
       action='lang_traffic', langcode='')
    mc('/traffic/adverts/:code', controller='front',
       action='advert_traffic', code='')
    mc('/traffic/subreddits/report', controller='front',
       action='subreddit_traffic_report')
    mc('/account-activity', controller='front', action='account_activity')

    mc('/subreddits/create', controller='front', action='newreddit')
    mc('/subreddits/search', controller='front', action='search_reddits')
    mc('/subreddits/login', controller='forms', action='login')
    mc('/subreddits/:where', controller='reddits', action='listing',
       where='popular', requirements=dict(where="popular|new|banned"))

    mc('/subreddits/mine/:where', controller='myreddits', action='listing',
       where='subscriber',
       requirements=dict(where='subscriber|contributor|moderator'))

    # These routes are kept for backwards-compatibility reasons
    # Using the above /subreddits/ ones instead is preferable
    mc('/reddits/create', controller='front', action='newreddit')
    mc('/reddits/search', controller='front', action='search_reddits')
    mc('/reddits/login', controller='forms', action='login')
    mc('/reddits/:where', controller='reddits', action='listing',
       where='popular', requirements=dict(where="popular|new|banned"))

    mc('/reddits/mine/:where', controller='myreddits', action='listing',
       where='subscriber',
       requirements=dict(where='subscriber|contributor|moderator'))

    mc('/buttons', controller='buttons', action='button_demo_page')

    #/button.js and buttonlite.js - the embeds
    mc('/button', controller='buttons', action='button_embed')
    mc('/buttonlite', controller='buttons', action='button_lite')

    mc('/widget', controller='buttons', action='widget_demo_page')
    mc('/bookmarklets', controller='buttons', action='bookmarklets')

    mc('/awards', controller='front', action='awards')
    mc('/awards/confirm/:code', controller='front',
       action='confirm_award_claim')
    mc('/awards/claim/:code', controller='front', action='claim_award')
    mc('/awards/received', controller='front', action='received_award')

    mc('/i18n', controller='redirect', action='redirect',
       dest='http://www.reddit.com/r/i18n')
    mc('/feedback', controller='feedback', action='feedback')
    mc('/ad_inq', controller='feedback', action='ad_inq')

    mc('/admin/awards', controller='awards')
    mc('/admin/awards/:awardcn/:action', controller='awards',
       requirements=dict(action="give|winners"))

    mc('/admin/errors', controller='errorlog')

    mc('/user/:username/about', controller='user', action='about',
       where='overview')
    mc('/user/:username/:where', controller='user', action='listing',
       where='overview')

    multi_prefixes = (
       partial_connect(mc, path_prefix='/user/:username/m/:multipath'),
       partial_connect(mc, path_prefix='/me/m/:multipath', my_multi=True),
    )

    for connect in multi_prefixes:
       connect('/', controller='hot', action='listing')
       connect('/submit', controller='front', action='submit')
       connect('/:sort', controller='browse', sort='top',
          action='listing', requirements=dict(sort='top|controversial'))
       connect('/:controller', action='listing',
          requirements=dict(controller="hot|new|rising|randomrising"))

    mc('/about/sidebar', controller='front', action='sidebar')
    mc('/about/flair', controller='front', action='flairlisting')
    mc('/about', controller='front', action='about')
    mc('/comments/gilded', controller='redirect', action='gilded_comments',
       conditions={'function': not_in_sr})
    for connect in (mc,) + multi_prefixes:
       connect('/about/message/:where', controller='message',
          action='listing')
       connect('/about/log', controller='front', action='moderationlog')
       connect('/about/:location', controller='front',
          action='spamlisting',
          requirements=dict(location='reports|spam|modqueue|unmoderated'))
       connect('/about/:location', controller='front', action='editreddit',
          location='about')
       connect('/comments', controller='comments', action='listing')
       connect('/comments/gilded', action='listing', controller='gilded')
       connect('/search', controller='front', action='search')

    mc('/u/:username', controller='redirect', action='user_redirect')
    mc('/u/:username/*rest', controller='redirect', action='user_redirect')

    # preserve timereddit URLs from 4/1/2012
    mc('/t/:timereddit', controller='redirect', action='timereddit_redirect')
    mc('/t/:timereddit/*rest', controller='redirect',
       action='timereddit_redirect')

    mc('/prefs/:location', controller='forms', action='prefs',
       location='options')

    mc('/info/0:article/*rest', controller='front',
       action='oldinfo', dest='comments', type='ancient')
    mc('/info/:article/:dest/:comment', controller='front',
       action='oldinfo', type='old', dest='comments', comment=None)


    mc('/related/:article/:title', controller='front',
       action='related', title=None)
    mc('/details/:article/:title', controller='front',
       action='details', title=None)
    mc('/traffic/:link/:campaign', controller='front', action='traffic',
       campaign=None)
    mc('/comments/:article/:title/:comment', controller='front',
       action='comments', title=None, comment=None)
    mc('/duplicates/:article/:title', controller='front',
       action='duplicates', title=None)

    mc('/mail/optout', controller='forms', action='optout')
    mc('/mail/optin', controller='forms', action='optin')
    mc('/stylesheet', controller='front', action='stylesheet')
    mc('/frame', controller='front', action='frame')
    mc('/framebuster/:blah', controller='front', action='framebuster')
    mc('/framebuster/:what/:blah',
       controller='front', action='framebuster')

    mc('/admin/promoted', controller='promote', action='admin')
    mc('/promoted/edit_promo/:link',
       controller='promote', action='edit_promo')
    mc('/promoted/edit_promo_cpm/:link',  # development only
       controller='promote', action='edit_promo_cpm')
    mc('/promoted/edit_promo/pc/:campaign', controller='promote',  # admin only
       action='edit_promo_campaign')
    mc('/promoted/pay/:link/:campaign',
       controller='promote', action='pay')
    mc('/promoted/graph',
       controller='promote', action='graph')
    mc('/promoted/admin/graph', controller='promote', action='admingraph')
    mc('/promoted/inventory/:sr_name',
       controller='promote', action='inventory')

    mc('/promoted/:action', controller='promote',
       requirements=dict(action="edit_promo|new_promo|roadblock"))
    mc('/promoted/report', controller='promote', action='report')
    mc('/promoted/:sort/:sr', controller='promote', action='listing',
       requirements=dict(sort='live_promos'))
    mc('/promoted/:sort', controller='promote', action="listing")
    mc('/promoted/', controller='promoted', action="listing", sort="")

    mc('/health', controller='health', action='health')
    mc('/health/ads', controller='health', action='promohealth')

    mc('/', controller='hot', action='listing')

    mc('/:controller', action='listing',
       requirements=dict(controller="hot|new|rising|randomrising"))
    mc('/saved', controller='user', action='saved_redirect')

    mc('/by_id/:names', controller='byId', action='listing')

    mc('/:sort', controller='browse', sort='top', action='listing',
       requirements=dict(sort='top|controversial'))

    mc('/message/compose', controller='message', action='compose')
    mc('/message/messages/:mid', controller='message', action='listing',
       where="messages")
    mc('/message/:where', controller='message', action='listing')
    mc('/message/moderator/:subwhere', controller='message', action='listing',
       where='moderator')

    mc('/thanks', controller='forms', action="claim", secret='')
    mc('/thanks/:secret', controller='forms', action="claim")

    mc('/gold', controller='forms', action="gold")
    mc('/gold/creditgild/:passthrough', controller='forms', action='creditgild')
    mc('/gold/about', controller='front', action='gold_info')
    mc('/gold/partners', controller='front', action='gold_partners')
    mc('/gold/thanks', controller='front', action='goldthanks')

    mc('/password', controller='forms', action="password")
    mc('/:action', controller='front',
       requirements=dict(action="random|framebuster|selfserviceoatmeal"))
    mc('/:action', controller='embed',
       requirements=dict(action="blog"))
    mc('/help/gold', controller='redirect', action='redirect',
       dest='/gold/about')

    mc('/help/:page', controller='policies', action='policy_page',
       conditions={'function':not_in_sr},
       requirements={'page':'privacypolicy|useragreement'})

    mc('/wiki/create/*page', controller='wiki', action='wiki_create')
    mc('/wiki/edit/*page', controller='wiki', action='wiki_revise')
    mc('/wiki/revisions', controller='wiki', action='wiki_recent')
    mc('/wiki/revisions/*page', controller='wiki', action='wiki_revisions')
    mc('/wiki/settings/*page', controller='wiki', action='wiki_settings')
    mc('/wiki/discussions/*page', controller='wiki', action='wiki_discussions')
    mc('/wiki/pages', controller='wiki', action='wiki_listing')

    mc('/api/wiki/create', controller='wikiapi', action='wiki_create')
    mc('/api/wiki/edit', controller='wikiapi', action='wiki_edit')
    mc('/api/wiki/hide', controller='wikiapi', action='wiki_revision_hide')
    mc('/api/wiki/revert', controller='wikiapi', action='wiki_revision_revert')
    mc('/api/wiki/alloweditor/:act', controller='wikiapi',
       requirements=dict(act="del|add"), action='wiki_allow_editor')

    mc('/wiki/*page', controller='wiki', action='wiki_page')
    mc('/wiki/', controller='wiki', action='wiki_page')

    mc('/:action', controller='wiki', requirements=dict(action="help|faq"))
    mc('/help/*page', controller='wiki', action='wiki_redirect')
    mc('/w/*page', controller='wiki', action='wiki_redirect')

    mc('/goto', controller='toolbar', action='goto')
    mc('/tb/:id', controller='toolbar', action='tb')
    mc('/toolbar/:action', controller='toolbar',
       requirements=dict(action="toolbar|inner|login"))
    mc('/toolbar/comments/:id', controller='toolbar', action='comments')

    mc('/c/:comment_id', controller='front', action='comment_by_id')

    mc('/s/*rest', controller='toolbar', action='s')
    # additional toolbar-related rules just above the catchall

    mc('/d/:what', controller='api', action='bookmarklet')

    mc('/resetpassword/:key', controller='forms',
       action='resetpassword')
    mc('/verification/:key', controller='forms',
       action='verify_email')
    mc('/resetpassword', controller='forms',
       action='resetpassword')

    mc('/post/:action/:url_user', controller='post',
       requirements=dict(action="login|reg"))
    mc('/post/:action', controller='post',
       requirements=dict(action="options|over18|unlogged_options|optout"
                         "|optin|login|reg"))

    mc('/api', controller='redirect', action='redirect', dest='/dev/api')
    mc('/api/distinguish/:how', controller='api', action="distinguish")
    # wherever this is, google has to agree.
    mc('/api/gcheckout', controller='ipn', action='gcheckout')
    mc('/api/spendcreddits', controller='ipn', action="spendcreddits")
    mc('/api/stripecharge/gold', controller='stripe', action='goldcharge')
    mc('/api/stripewebhook/gold/:secret', controller='stripe',
       action='goldwebhook')
    mc('/api/coinbasewebhook/gold/:secret', controller='coinbase',
       action='goldwebhook')
    mc('/api/rgwebhook/gold/:secret', controller='redditgifts',
       action='goldwebhook')
    mc('/api/ipn/:secret', controller='ipn', action='ipn')
    mc('/ipn/:secret', controller='ipn', action='ipn')
    mc('/api/:action/:url_user', controller='api',
       requirements=dict(action="login|register"))
    mc('/api/gadget/click/:ids', controller='api', action='gadget',
       type='click')
    mc('/api/gadget/:type', controller='api', action='gadget')
    mc('/api/:action', controller='promote',
       requirements=dict(action=("promote|unpromote|edit_promo|link_thumb|"
                                 "freebie|promote_note|update_pay|refund|"
                                 "traffic_viewer|rm_traffic_viewer|"
                                 "edit_campaign|delete_campaign|meta_promo|"
                                 "add_roadblock|rm_roadblock")))
    mc('/api/:action', controller='apiminimal',
       requirements=dict(action="new_captcha"))
    mc('/api/:type', controller='api',
       requirements=dict(type='wikibannednote|bannednote'),
       action='relnote')
    mc('/api/:action', controller='api')

    mc("/api/multi/mine", controller="multiapi", action="my_multis")
    mc("/api/multi/copy", controller="multiapi", action="multi_copy")
    mc("/api/multi/rename", controller="multiapi", action="multi_rename")
    mc("/api/multi/*multipath/r/:srname", controller="multiapi", action="multi_subreddit")
    mc("/api/multi/*multipath/description", controller="multiapi", action="multi_description")
    mc("/api/multi/*multipath", controller="multiapi", action="multi")

    mc("/api/v1/:action", controller="oauth2frontend",
       requirements=dict(action="authorize"))
    mc("/api/v1/:action", controller="oauth2access",
       requirements=dict(action="access_token"))
    mc("/api/v1/:action", controller="apiv1")

    mc('/dev', controller='redirect', action='redirect', dest='/dev/api')
    mc('/dev/api', controller='apidocs', action='docs')
    mc('/dev/api/:mode', controller='apidocs', action='docs',
       requirements=dict(mode="oauth"))

    mc("/button_info", controller="api", action="info", limit=1)

    mc('/captcha/:iden', controller='captcha', action='captchaimg')

    mc('/mediaembed/:link', controller="mediaembed", action="mediaembed")

    mc('/doquery', controller='query', action='doquery')

    mc('/code', controller='redirect', action='redirect',
       dest='http://github.com/reddit/')

    mc('/socialite', controller='redirect', action='redirect',
       dest='https://addons.mozilla.org/firefox/addon/socialite/')

    mc('/mobile', controller='redirect', action='redirect',
       dest='http://m.reddit.com/')

    mc('/authorize_embed', controller='front', action='authorize_embed')

    # Used for showing ads
    mc("/ads/", controller="ad", action="ad")

    mc("/try", controller="forms", action="try_compact")

    # This route handles displaying the error page and
    # graphics used in the 404/500
    # error pages. It should likely stay at the top
    # to ensure that the error page is
    # displayed properly.
    mc('/error/document/:id', controller='error', action="document")

    # these should be near the buttom, because they should only kick
    # in if everything else fails. It's the attempted catch-all
    # reddit.com/http://... and reddit.com/34fr, but these redirect to
    # the less-guessy versions at /s/ and /tb/
    mc('/:linkoid', controller='toolbar', action='linkoid',
       requirements=dict(linkoid='[0-9a-z]{1,6}'))
    mc('/:urloid', controller='toolbar', action='urloid',
       requirements=dict(urloid=r'(\w+\.\w{2,}|https?).*'))

    mc("/*url", controller='front', action='catchall')

    return map
