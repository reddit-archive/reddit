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
# All portions of the code written by reddit are Copyright (c) 2006-2015 reddit
# Inc. All Rights Reserved.
###############################################################################

import hashlib

from pylons import g

from r2.lib.configparse import ConfigValue
from r2.lib.providers.image_resizing import (
    ImageResizingProvider,
    NotLargeEnough,
)
from r2.lib.utils import UrlParser, query_string

class ImgixImageResizingProvider(ImageResizingProvider):
    """A provider that uses imgix to create on-the-fly resizings."""
    config = {
        ConfigValue.str: [
            'imgix_domain',
        ],
    }

    def resize_image(self, image, width=None, censor_nsfw=False):
        url = UrlParser(image['url'])
        url.hostname = g.imgix_domain
        # Let's encourage HTTPS; it's cool, works just fine on HTTP pages, and
        # will prevent insecure content warnings on HTTPS pages.
        url.scheme = 'https'
        if width:
            if width > image['width']:
                raise NotLargeEnough()
            # http://www.imgix.com/docs/reference/size#param-w
            url.update_query(w=width)
        if censor_nsfw:
            # Since we aren't concerned with inhibiting a user's ability to
            # reverse the censoring for privacy reasons, pixellation is better
            # than a Gaussian blur because it compresses well.  The specific
            # value is just "what looks about right".
            #
            # http://www.imgix.com/docs/reference/stylize#param-px
            url.update_query(px=20)
        if g.imgix_signing:
            url = self._sign_url(url, g.secrets['imgix_signing_token'])
        return url.unparse()

    def _sign_url(self, url, token):
        """Sign a url for imgix's secured sources.

        Based very heavily on the example code in the docs:
            http://www.imgix.com/docs/tutorials/securing-images

        Arguments:

        * url -- a UrlParser instance of the url to sign.  This object may be
                 modified by the function, so make a copy beforehand if that is
                 a concern.
        * token -- a string token provided by imgix for request signing

        Returns a UrlParser instance with signing parameters.
        """
        # Build the signing value
        signvalue = token + url.path
        if url.query_dict:
          signvalue += query_string(url.query_dict)

        # Calculate MD5 of the signing value.
        signature = hashlib.md5(signvalue).hexdigest()

        url.update_query(s=signature)
        return url
