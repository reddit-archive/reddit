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

import os
import glob

try:
    import reddit_i18n
    I18N_PATH = os.path.dirname(reddit_i18n.__file__)
except ImportError:
    I18N_PATH = os.path.abspath('r2/r2/i18n')


def get_available_languages():
    search_expression = os.path.join(I18N_PATH, "*", "LC_MESSAGES", "r2.mo")
    mo_files = glob.glob(search_expression) # _i18n_path/<lang code>/LC_MESSAGES/r2.mo
    languages = [os.path.basename(os.path.dirname(os.path.dirname(p))) for p in mo_files]
    return sorted(languages)
