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
# All portions of the code written by reddit are Copyright (c) 2006-2014 reddit
# Inc. All Rights Reserved.
###############################################################################

import base64
import cStringIO
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import traceback
import urllib
import urllib2
import urlparse
import gzip

import BeautifulSoup
import Image
import ImageFile
import requests

from pylons import g

from r2.lib import amqp, hooks
from r2.lib.memoize import memoize
from r2.lib.nymph import optimize_png
from r2.lib.utils import TimeoutFunction, TimeoutFunctionException, domain
from r2.models.link import Link
from r2.models.media_cache import (
    ERROR_MEDIA,
    Media,
    MediaByURL,
)
from urllib2 import (
    HTTPError,
    URLError,
)


thumbnail_size = 70, 70

# TODO: replace this with data from the embedly service api when available
_SECURE_SERVICES = [
    "youtube",
    "vimeo",
    "soundcloud",
    "wistia",
    "slideshare",
]


def _image_to_str(image):
    s = cStringIO.StringIO()
    image.save(s, image.format)
    return s.getvalue()


def str_to_image(s):
    s = cStringIO.StringIO(s)
    image = Image.open(s)
    return image


def _image_entropy(img):
    """calculate the entropy of an image"""
    hist = img.histogram()
    hist_size = sum(hist)
    hist = [float(h) / hist_size for h in hist]

    return -sum(p * math.log(p, 2) for p in hist if p != 0)


def _square_image(img):
    """if the image is taller than it is wide, square it off. determine
    which pieces to cut off based on the entropy pieces."""
    x,y = img.size
    while y > x:
        #slice 10px at a time until square
        slice_height = min(y - x, 10)

        bottom = img.crop((0, y - slice_height, x, y))
        top = img.crop((0, 0, x, slice_height))

        #remove the slice with the least entropy
        if _image_entropy(bottom) < _image_entropy(top):
            img = img.crop((0, 0, x, y - slice_height))
        else:
            img = img.crop((0, slice_height, x, y))

        x,y = img.size

    return img


def _prepare_image(image):
    image = _square_image(image)
    image.thumbnail(thumbnail_size, Image.ANTIALIAS)
    return image


def _clean_url(url):
    """url quotes unicode data out of urls"""
    url = url.encode('utf8')
    url = ''.join(urllib.quote(c) if ord(c) >= 127 else c for c in url)
    return url


def _initialize_request(url, referer, gzip=False):
    url = _clean_url(url)

    if not url.startswith(("http://", "https://")):
        return

    req = urllib2.Request(url)
    if gzip:
        req.add_header('Accept-Encoding', 'gzip')
    if g.useragent:
        req.add_header('User-Agent', g.useragent)
    if referer:
        req.add_header('Referer', referer)
    return req


def _fetch_url(url, referer=None):
    request = _initialize_request(url, referer=referer, gzip=True)
    if not request:
        return None, None
    response = urllib2.urlopen(request)
    response_data = response.read()
    content_encoding = response.info().get("Content-Encoding")
    if content_encoding and content_encoding.lower() in ["gzip", "x-gzip"]:
        buf = cStringIO.StringIO(response_data)
        f = gzip.GzipFile(fileobj=buf)
        response_data = f.read()
    return response.headers.get("Content-Type"), response_data


@memoize('media.fetch_size', time=3600)
def _fetch_image_size(url, referer):
    """Return the size of an image by URL downloading as little as possible."""

    request = _initialize_request(url, referer)
    if not request:
        return None

    parser = ImageFile.Parser()
    response = None
    try:
        response = urllib2.urlopen(request)

        while True:
            chunk = response.read(1024)
            if not chunk:
                break

            parser.feed(chunk)
            if parser.image:
                return parser.image.size
    except urllib2.URLError:
        return None
    finally:
        if response:
            response.close()


def optimize_jpeg(filename):
    with open(os.path.devnull, 'w') as devnull:
        subprocess.check_call(("/usr/bin/jpegoptim", filename), stdout=devnull)


def thumbnail_url(link):
    """Given a link, returns the url for its thumbnail based on its fullname"""
    if link.has_thumbnail:
        if hasattr(link, "thumbnail_url"):
            return link.thumbnail_url
        else:
            return ''
    else:
        return ''


def _filename_from_content(contents):
    hash_bytes = hashlib.sha256(contents).digest()
    return base64.urlsafe_b64encode(hash_bytes).rstrip("=")


def upload_media(image, file_type='.jpg'):
    """Upload an image to the media provider."""
    f = tempfile.NamedTemporaryFile(suffix=file_type, delete=False)
    try:
        img = image
        do_convert = True
        if isinstance(img, basestring):
            img = str_to_image(img)
            if img.format == "PNG" and file_type == ".png":
                img.verify()
                f.write(image)
                f.close()
                do_convert = False

        if do_convert:
            img = img.convert('RGBA')
            if file_type == ".jpg":
                # PIL does not play nice when converting alpha channels to jpg
                background = Image.new('RGBA', img.size, (255, 255, 255))
                background.paste(img, img)
                img = background.convert('RGB')
                img.save(f, quality=85) # Bug in the JPG encoder with the optimize flag, even if set to false
            else:
                img.save(f, optimize=True)

        if file_type == ".png":
            optimize_png(f.name)
        elif file_type == ".jpg":
            optimize_jpeg(f.name)
        contents = open(f.name).read()
        file_name = _filename_from_content(contents) + file_type
        return g.media_provider.put(file_name, contents)
    finally:
        os.unlink(f.name)
    return ""


def upload_stylesheet(content):
    file_name = _filename_from_content(content) + ".css"
    return g.media_provider.put(file_name, content)


def _scrape_media(url, autoplay=False, maxwidth=600, force=False,
                  save_thumbnail=True, use_cache=False, max_cache_age=None):
    media = None
    autoplay = bool(autoplay)
    maxwidth = int(maxwidth)

    # Use media from the cache (if available)
    if not force and use_cache:
        mediaByURL = MediaByURL.get(url,
                                    autoplay=autoplay,
                                    maxwidth=maxwidth,
                                    max_cache_age=max_cache_age)
        if mediaByURL:
            media = mediaByURL.media

    # Otherwise, scrape it
    if not media:
        media_object = secure_media_object = None
        thumbnail_image = thumbnail_url = thumbnail_size = None

        scraper = Scraper.for_url(url, autoplay=autoplay)
        try:
            thumbnail_image, media_object, secure_media_object = (
                scraper.scrape())
        except (HTTPError, URLError) as e:
            if use_cache:
                MediaByURL.add_error(url, str(e),
                                     autoplay=autoplay,
                                     maxwidth=maxwidth)
            return None

        # the scraper should be able to make a media embed out of the
        # media object it just gave us. if not, null out the media object
        # to protect downstream code
        if media_object and not scraper.media_embed(media_object):
            print "%s made a bad media obj for url %s" % (scraper, url)
            media_object = None

        if (secure_media_object and
            not scraper.media_embed(secure_media_object)):
            print "%s made a bad secure media obj for url %s" % (scraper, url)
            secure_media_object = None

        if thumbnail_image and save_thumbnail:
            thumbnail_size = thumbnail_image.size
            thumbnail_url = upload_media(thumbnail_image)

        media = Media(media_object, secure_media_object,
                      thumbnail_url, thumbnail_size)

    # Store the media in the cache (if requested), possibly extending the ttl
    use_cache = use_cache and save_thumbnail    # don't cache partial scrape
    if use_cache and media is not ERROR_MEDIA:
        MediaByURL.add(url,
                       media,
                       autoplay=autoplay,
                       maxwidth=maxwidth)

    return media


def _set_media(link, force=False, **kwargs):
    if link.is_self:
        return
    if not force and link.promoted:
        return
    elif not force and (link.has_thumbnail or link.media_object):
        return

    media = _scrape_media(link.url, force=force, **kwargs)

    if media and not link.promoted:
        link.thumbnail_url = media.thumbnail_url
        link.thumbnail_size = media.thumbnail_size

        link.set_media_object(media.media_object)
        link.set_secure_media_object(media.secure_media_object)

        link._commit()

        hooks.get_hook("scraper.set_media").call(link=link)


def force_thumbnail(link, image_data, file_type=".jpg"):
    image = str_to_image(image_data)
    image = _prepare_image(image)
    thumb_url = upload_media(image, file_type=file_type)

    link.thumbnail_url = thumb_url
    link.thumbnail_size = image.size
    link._commit()


def upload_icon(file_name, image_data, size):
    image = str_to_image(image_data)
    image.format = 'PNG'
    image.thumbnail(size, Image.ANTIALIAS)
    icon_data = _image_to_str(image)
    return g.media_provider.put(file_name + ".png", icon_data)


def _make_custom_media_embed(media_object):
    # this is for promoted links with custom media embeds.
    return MediaEmbed(
        height=media_object.get("height"),
        width=media_object.get("width"),
        content=media_object.get("content"),
    )


def get_media_embed(media_object):
    if not isinstance(media_object, dict):
        return

    embed_hook = hooks.get_hook("scraper.media_embed")
    media_embed = embed_hook.call_until_return(media_object=media_object)
    if media_embed:
        return media_embed

    if media_object.get("type") == "custom":
        return _make_custom_media_embed(media_object)

    if "oembed" in media_object:
        return _EmbedlyScraper.media_embed(media_object)


class MediaEmbed(object):
    """A MediaEmbed holds data relevant for serving media for an object."""

    width = None
    height = None
    content = None
    scrolling = False

    def __init__(self, height, width, content, scrolling=False,
                 public_thumbnail_url=None, sandbox=True):
        """Build a MediaEmbed.

        :param height int - The height of the media embed, in pixels
        :param width int - The width of the media embed, in pixels
        :param content string - The content of the media embed - HTML.
        :param scrolling bool - Whether the media embed should scroll or not.
        :param public_thumbnail_url string - The URL of the most representative
            thumbnail for this media. This may be on an uncontrolled domain,
            and is not necessarily our own thumbs domain (and should not be
            served to browsers).
        :param sandbox bool - True if the content should be sandboxed
            in an iframe on the media domain.
        """

        self.height = int(height)
        self.width = int(width)
        self.content = content
        self.scrolling = scrolling
        self.public_thumbnail_url = public_thumbnail_url
        self.sandbox = sandbox


def _make_thumbnail_from_url(thumbnail_url, referer):
    if not thumbnail_url:
        return
    content_type, content = _fetch_url(thumbnail_url, referer=referer)
    if not content:
        return
    image = str_to_image(content)
    return _prepare_image(image)


class Scraper(object):
    @classmethod
    def for_url(cls, url, autoplay=False, maxwidth=600):
        scraper = hooks.get_hook("scraper.factory").call_until_return(url=url)
        if scraper:
            return scraper

        embedly_services = _fetch_embedly_services()
        for service_re, service_secure in embedly_services:
            if service_re.match(url):
                return _EmbedlyScraper(url,
                                       service_secure,
                                       autoplay=autoplay,
                                       maxwidth=maxwidth)

        return _ThumbnailOnlyScraper(url)

    def scrape(self):
        # should return a 3-tuple of: thumbnail, media_object, secure_media_obj
        raise NotImplementedError

    @classmethod
    def media_embed(cls, media_object):
        # should take a media object and return an appropriate MediaEmbed
        raise NotImplementedError


class _ThumbnailOnlyScraper(Scraper):
    def __init__(self, url):
        self.url = url

    def scrape(self):
        thumbnail_url = self._find_thumbnail_image()
        thumbnail = _make_thumbnail_from_url(thumbnail_url, referer=self.url)
        return thumbnail, None, None

    def _extract_image_urls(self, soup):
        for img in soup.findAll("img", src=True):
            yield urlparse.urljoin(self.url, img["src"])

    def _find_thumbnail_image(self):
        content_type, content = _fetch_url(self.url)

        # if it's an image. it's pretty easy to guess what we should thumbnail.
        if content_type and "image" in content_type and content:
            return self.url

        if content_type and "html" in content_type and content:
            soup = BeautifulSoup.BeautifulSoup(content)
        else:
            return None

        # allow the content author to specify the thumbnail:
        # <meta property="og:image" content="http://...">
        og_image = (soup.find('meta', property='og:image') or
                    soup.find('meta', attrs={'name': 'og:image'}))
        if og_image and og_image['content']:
            return og_image['content']

        # <link rel="image_src" href="http://...">
        thumbnail_spec = soup.find('link', rel='image_src')
        if thumbnail_spec and thumbnail_spec['href']:
            return thumbnail_spec['href']

        # ok, we have no guidance from the author. look for the largest
        # image on the page with a few caveats. (see below)
        max_area = 0
        max_url = None
        for image_url in self._extract_image_urls(soup):
            size = _fetch_image_size(image_url, referer=self.url)
            if not size:
                continue

            area = size[0] * size[1]

            # ignore little images
            if area < 5000:
                g.log.debug('ignore little %s' % image_url)
                continue

            # ignore excessively long/wide images
            if max(size) / min(size) > 1.5:
                g.log.debug('ignore dimensions %s' % image_url)
                continue

            # penalize images with "sprite" in their name
            if 'sprite' in image_url.lower():
                g.log.debug('penalizing sprite %s' % image_url)
                area /= 10

            if area > max_area:
                max_area = area
                max_url = image_url
        return max_url


class _EmbedlyScraper(Scraper):
    EMBEDLY_API_URL = "https://api.embed.ly/1/oembed"

    def __init__(self, url, can_embed_securely, autoplay=False, maxwidth=600):
        self.url = url
        self.can_embed_securely = can_embed_securely
        self.maxwidth = int(maxwidth)
        self.embedly_params = {}

        if autoplay:
            self.embedly_params["autoplay"] = "true"

    def _fetch_from_embedly(self, secure):
        param_dict = {
            "url": self.url,
            "format": "json",
            "maxwidth": self.maxwidth,
            "key": g.embedly_api_key,
            "secure": "true" if secure else "false",
        }

        param_dict.update(self.embedly_params)
        params = urllib.urlencode(param_dict)
        content = requests.get(self.EMBEDLY_API_URL + "?" + params).content
        return json.loads(content)

    def _make_media_object(self, oembed):
        if oembed.get("type") in ("video", "rich"):
            return {
                "type": domain(self.url),
                "oembed": oembed,
            }
        return None

    def scrape(self):
        oembed = self._fetch_from_embedly(secure=False)
        if not oembed:
            return None, None, None

        if oembed.get("type") == "photo":
            thumbnail_url = oembed.get("url")
        else:
            thumbnail_url = oembed.get("thumbnail_url")
        thumbnail = _make_thumbnail_from_url(thumbnail_url, referer=self.url)

        secure_oembed = {}
        if self.can_embed_securely:
            secure_oembed = self._fetch_from_embedly(secure=True)

        return (
            thumbnail,
            self._make_media_object(oembed),
            self._make_media_object(secure_oembed),
        )

    @classmethod
    def media_embed(cls, media_object):
        oembed = media_object["oembed"]

        html = oembed.get("html")
        width = oembed.get("width")
        height = oembed.get("height")
        public_thumbnail_url = oembed.get('thumbnail_url')
        if not (html and width and height):
            return

        return MediaEmbed(
            width=width,
            height=height,
            content=html,
            public_thumbnail_url=public_thumbnail_url,
        )


@memoize("media.embedly_services2", time=3600)
def _fetch_embedly_service_data():
    return requests.get("https://api.embed.ly/1/services/python").json


def _fetch_embedly_services():
    if not g.embedly_api_key:
        if g.debug:
            g.log.info("No embedly_api_key, using no key while in debug mode.")
        else:
            g.log.warning("No embedly_api_key configured. Will not use "
                          "embed.ly.")
            return []

    service_data = _fetch_embedly_service_data()

    services = []
    for service in service_data:
        services.append((
            re.compile("(?:%s)" % "|".join(service["regex"])),
            service["name"] in _SECURE_SERVICES,
        ))
    return services


def run():
    @g.stats.amqp_processor('scraper_q')
    def process_link(msg):
        fname = msg.body
        link = Link._by_fullname(msg.body, data=True)

        try:
            TimeoutFunction(_set_media, 30)(link, use_cache=True)
        except TimeoutFunctionException:
            print "Timed out on %s" % fname
        except KeyboardInterrupt:
            raise
        except:
            print "Error fetching %s" % fname
            print traceback.format_exc()

    amqp.consume_items('scraper_q', process_link)
