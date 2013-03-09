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

import re
from collections import defaultdict
from itertools import chain
import inspect
from os.path import abspath, relpath

from pylons import g
from pylons.i18n import _
from reddit_base import RedditController
from r2.lib.utils import Storage
from r2.lib.pages import BoringPage, ApiHelp
from r2.lib.validator import validate, VOneOf

# API sections displayed in the documentation page.
# Each section can have a title and a markdown-formatted description.
section_info = {
    'account': {
        'title': _('account'),
    },
    'apps': {
        'title': _('apps'),
    },
    'flair': {
        'title': _('flair'),
    },
    'links_and_comments': {
        'title': _('links & comments'),
    },
    'messages': {
        'title': _('private messages'),
    },
    'moderation': {
        'title': _('moderation'),
    },
    'misc': {
        'title': _('misc'),
    },
    'listings': {
        'title': _('listings'),
    },
    'search': {
        'title': _('search'),
    },
    'subreddits': {
        'title': _('subreddits'),
    },
    'multis': {
        'title': _('multis'),
    },
    'users': {
        'title': _('users'),
    },
    'wiki': {
        'title': _('wiki'),
    },
    'captcha': {
        'title': _('captcha'),
    }
}

api_section = Storage((k, k) for k in section_info)

def api_doc(section, **kwargs):
    """
    Add documentation annotations to the decorated function.

    See ApidocsController.docs_from_controller for a list of annotation fields.
    """
    def add_metadata(api_function):
        doc = api_function._api_doc = getattr(api_function, '_api_doc', {})
        if 'extends' in kwargs:
            kwargs['extends'] = kwargs['extends']._api_doc
        doc.update(kwargs)
        doc['section'] = section
        doc['lineno'] = api_function.func_code.co_firstlineno

        file_path = abspath(api_function.func_code.co_filename)
        root_dir = g.paths['root']
        if file_path.startswith(root_dir):
            doc['relfilepath'] = relpath(file_path, root_dir)

        return api_function
    return add_metadata

class ApidocsController(RedditController):
    @staticmethod
    def docs_from_controller(controller, url_prefix='/api', oauth_only=False):
        """
        Examines a controller for documentation.  A dictionary index of
        sections containing dictionaries of URLs is returned.  For each URL, a
        dictionary of HTTP methods (GET, POST, etc.) is contained.  For each
        URL/method pair, a dictionary containing the following items is
        available:

        - `doc`: Markdown-formatted docstring.
        - `uri`: Manually-specified URI to list the API method as
        - `uri_variants`: Alternate URIs to access the API method from
        - `extensions`: URI extensions the API method supports
        - `parameters`: Dictionary of possible parameter names and descriptions.
        - `extends`: API method from which to inherit documentation
        """

        api_docs = defaultdict(lambda: defaultdict(dict))
        for name, func in controller.__dict__.iteritems():
            method, sep, action = name.partition('_')
            if not action:
                continue

            valid_methods = ('GET', 'POST', 'PUT', 'DELETE')
            api_doc = getattr(func, '_api_doc', None)
            if api_doc and 'section' in api_doc and method in valid_methods:
                docs = {}
                docs['doc'] = inspect.getdoc(func)

                if 'extends' in api_doc:
                    docs.update(api_doc['extends'])
                    # parameters are handled separately.
                    docs['parameters'] = {}
                docs.update(api_doc)

                uri = docs.get('uri') or '/'.join((url_prefix, action))
                if 'extensions' in docs:
                    # if only one extension was specified, add it to the URI.
                    if len(docs['extensions']) == 1:
                        uri += '.' + docs['extensions'][0]
                        del docs['extensions']
                docs['uri'] = uri

                oauth_perms = getattr(func, 'oauth2_perms', {})
                docs['oauth_scopes'] = oauth_perms.get('allowed_scopes', [])

                # add every variant to the index -- the templates will filter
                # out variants in the long-form documentation
                if oauth_only:
                    if not docs['oauth_scopes']:
                        continue
                    for scope in docs['oauth_scopes']:
                        for variant in chain([uri],
                                             docs.get('uri_variants', [])):
                            api_docs[scope][variant][method] = docs
                else:
                    for variant in chain([uri], docs.get('uri_variants', [])):
                        api_docs[docs['section']][variant][method] = docs

        return api_docs

    @validate(
        mode=VOneOf('mode', options=('methods', 'oauth'), default='methods'))
    def GET_docs(self, mode):
        # controllers to gather docs from.
        from r2.controllers.api import ApiController, ApiminimalController
        from r2.controllers.apiv1 import APIv1Controller
        from r2.controllers.captcha import CaptchaController
        from r2.controllers.front import FrontController
        from r2.controllers.wiki import WikiApiController
        from r2.controllers.multi import MultiApiController
        from r2.controllers import listingcontroller

        api_controllers = [
            (APIv1Controller, '/api/v1'),
            (ApiController, '/api'),
            (ApiminimalController, '/api'),
            (WikiApiController, '/api/wiki'),
            (MultiApiController, '/api/multi'),
            (CaptchaController, ''),
            (FrontController, '')
        ]
        for name, value in vars(listingcontroller).iteritems():
            if name.endswith('Controller'):
                api_controllers.append((value, ''))

        # merge documentation info together.
        api_docs = defaultdict(dict)
        oauth_index = defaultdict(set)
        for controller, url_prefix in api_controllers:
            controller_docs = self.docs_from_controller(controller, url_prefix,
                                                        mode == 'oauth')
            for section, contents in controller_docs.iteritems():
                api_docs[section].update(contents)
                for variant, method_dict in contents.iteritems():
                    for method, docs in method_dict.iteritems():
                        for scope in docs['oauth_scopes']:
                            oauth_index[scope].add((section, variant, method))

        return BoringPage(
            _('api documentation'),
            content=ApiHelp(
                api_docs=api_docs,
                oauth_index=oauth_index,
                mode=mode,
            ),
            css_class="api-help",
            show_sidebar=False,
            show_infobar=False
        ).render()
