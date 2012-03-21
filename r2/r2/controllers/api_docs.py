import re
from collections import defaultdict

from pylons.i18n import _
from reddit_base import RedditController
from r2.lib.pages import BoringPage, ApiHelp

class ApidocsController(RedditController):
    @staticmethod
    def docs_from_controller(controller, url_prefix='/api'):
        """
        Examines a controller for documentation.  A dictionary of URLs is
        returned.  For each URL, a dictionary of HTTP methods (GET, POST, etc.)
        is contained.  For each URL/method pair, a dictionary containing the
        following items is available:

        - `__doc__`: Markdown-formatted docstring.
        - `oauth2_scopes`: List of OAuth2 scopes
        - *more to come...*
        """

        api_methods = defaultdict(dict)
        for name, func in controller.__dict__.iteritems():
            i = name.find('_')
            if i > 0:
                method = name[:i]
                action = name[i+1:]
            else:
                continue

            if func.__doc__ and method in ('GET', 'POST'):
                docs = {
                    '__doc__': re.sub(r'\n +', '\n', func.__doc__).strip(),
                }

                if hasattr(func, 'oauth2_perms'):
                    scopes = func.oauth2_perms.get('allowed_scopes')
                    if scopes:
                        docs['oauth2_scopes'] = scopes

                # TODO: in the future, it would be cool to introspect the
                # validators in order to generate a list of request
                # parameters.  Some decorators also give a hint as to response
                # type (JSON, etc.) which could be included as well.

                api_methods['/'.join((url_prefix, action))][method] = docs

        return api_methods

    def GET_docs(self):
        from r2.controllers.api import ApiController, ApiminimalController
        from r2.controllers.apiv1 import APIv1Controller
        from r2.controllers.oauth2 import OAuth2FrontendController, OAuth2AccessController, scope_info

        api_methods = defaultdict(dict)
        for controller, url_prefix in ((ApiController, '/api'),
                                       (ApiminimalController, '/api'),
                                       (OAuth2FrontendController, '/api/v1'),
                                       (OAuth2AccessController, '/api/v1'),
                                       (APIv1Controller, '/api/v1')):
            for url, methods in self.docs_from_controller(controller, url_prefix).iteritems():
                api_methods[url].update(methods)

        return BoringPage(
            _('api documentation'),
            content=ApiHelp(
                api_methods=api_methods,
                oauth2_scopes=scope_info,
            )
        ).render()
