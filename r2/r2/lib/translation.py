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
import json
import os
import pylons
from pylons.i18n.translation import translation, LanguageError, NullTranslations

from r2.lib.i18n import I18N_PATH as _i18n_path


_domain = 'r2'


def _get_translator(lang, graceful_fail=False, **kwargs):
    from pylons import config as conf
    """Utility method to get a valid translator object from a language name"""
    if not isinstance(lang, list):
        lang = [lang]
    try:
        translator = translation(conf['pylons.package'], _i18n_path, 
                                 languages=lang, **kwargs)
    except IOError, ioe:
        if graceful_fail:
            translator = NullTranslations()
        else:
            raise LanguageError('IOError: %s' % ioe)
    translator.pylons_lang = lang
    return translator


def set_lang(lang, graceful_fail = False, **kwargs):
    """Set the i18n language used"""
    registry = pylons.request.environ['paste.registry']
    if not lang:
        registry.replace(pylons.translator, NullTranslations())
    else:
        translator = _get_translator(lang, graceful_fail = graceful_fail, **kwargs)
        registry.replace(pylons.translator, translator)


def load_data(lang, path=_i18n_path, domain=_domain, extension='data'):
    filename = os.path.join(path, lang, 'LC_MESSAGES',
                            domain + '.' + extension)
    with open(filename) as datafile:
        data = json.load(datafile)
    return data


def get_active_langs(path=_i18n_path, default_lang='en'):
    trans = []
    trans_name = {}
    for lang in os.listdir(path):
        x = os.path.join(path, lang, 'LC_MESSAGES')
        if os.path.isdir(x):
            data = load_data(lang)
            name = [data['name'], '']
            if data['_is_enabled'] and lang != default_lang:
                trans.append(lang)
                completion = float(data['num_completed']) / float(data['num_total'])
                if completion < .5:
                    name[1] = ' (*)'
            trans_name[lang] = name
    trans.sort()
    # insert the default language at the top of the list
    trans.insert(0, default_lang)
    if default_lang not in trans_name:
        trans_name[default_lang] = default_lang
    return trans, trans_name
