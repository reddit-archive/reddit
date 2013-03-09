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

from r2.lib.manager import tp_manager
from r2.lib.jsontemplates import *

tpm = tp_manager.tp_manager()

def api(type, cls):
    tpm.add_handler(type, 'api', cls())
    tpm.add_handler(type, 'api-html', cls())
    tpm.add_handler(type, 'api-compact', cls())

# blanket fallback rule
api('templated', NullJsonTemplate)

# class specific overrides
api('link',          LinkJsonTemplate)
api('promotedlink',  PromotedLinkJsonTemplate)
api('comment',       CommentJsonTemplate)
api('message',       MessageJsonTemplate)
api('subreddit',     SubredditJsonTemplate)
api('labeledmulti',  LabeledMultiJsonTemplate)
api('morerecursion', MoreCommentJsonTemplate)
api('morechildren',  MoreCommentJsonTemplate)
api('reddit',        RedditJsonTemplate)
api('panestack',     PanestackJsonTemplate)
api('listing',       ListingJsonTemplate)
api('modlist',       UserListJsonTemplate)
api('userlist',      UserListJsonTemplate)
api('contributorlist', UserListJsonTemplate)
api('bannedlist',    UserListJsonTemplate)
api('friendlist',    UserListJsonTemplate)
api('usertableitem', UserTableItemJsonTemplate)
api('account',       AccountJsonTemplate)

api('organiclisting',       OrganicListingJsonTemplate)
api('subreddittraffic', TrafficJsonTemplate)
api('takedownpane', TakedownJsonTemplate)
api('policyview', PolicyViewJsonTemplate)

api('wikibasepage', WikiJsonTemplate)
api('wikipagerevisions', WikiJsonTemplate)
api('wikiview', WikiViewJsonTemplate)
api('wikirevision', WikiRevisionJsonTemplate)

api('wikipagelisting', WikiPageListingJsonTemplate)
api('wikipagediscussions', WikiJsonTemplate)
api('wikipagesettings', WikiSettingsJsonTemplate)

api('flairlist', FlairListJsonTemplate)
api('flaircsv', FlairCsvJsonTemplate)

api('subredditstylesheet', StylesheetTemplate)
api('subredditstylesheetsource', StylesheetTemplate)
api('createsubreddit', SubredditSettingsTemplate)

api('modaction', ModActionTemplate)

tpm.add_handler('usertableitem', 'api-html', UserItemHTMLJsonTemplate())
