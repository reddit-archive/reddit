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

import base64
import collections
import cStringIO
import hashlib
import json
import math
import mimetypes
import os
import re
import subprocess
import tempfile
import traceback
import urllib
import urllib2
import urlparse

import BeautifulSoup
import Image
import ImageFile

from pylons import g

from r2.lib import amqp, s3cp
from r2.lib.memoize import memoize
from r2.lib.nymph import optimize_png
from r2.lib.utils import TimeoutFunction, TimeoutFunctionException, domain
from r2.models.link import Link


s3_direct_url = "s3.amazonaws.com"
MEDIA_FILENAME_LENGTH = 12
thumbnail_size = 70, 70


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


def _initialize_request(url, referer):
    url = _clean_url(url)

    if not url.startswith(("http://", "https://")):
        return

    req = urllib2.Request(url)
    if g.useragent:
        req.add_header('User-Agent', g.useragent)
    if referer:
        req.add_header('Referer', referer)
    return req


def _fetch_url(url, referer=None):
    request = _initialize_request(url, referer=referer)
    if not request:
        return None, None
    response = urllib2.urlopen(request)
    return response.headers.get("Content-Type"), response.read()


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


def optimize_jpeg(filename, optimizer):
    if optimizer:
        with open(os.path.devnull, 'w') as devnull:
            subprocess.check_call((optimizer, filename),
                                  stdout=devnull)


def thumbnail_url(link):
    """Given a link, returns the url for its thumbnail based on its fullname"""
    if link.has_thumbnail:
        if hasattr(link, "thumbnail_url"):
            return link.thumbnail_url
        else:
            bucket = g.s3_old_thumb_bucket
            baseurl = "http://%s" % (bucket)
            if g.s3_media_direct:
                baseurl = "http://%s/%s" % (s3_direct_url, bucket)
            res = '%s/%s.png' % (baseurl,link._fullname)
            if hasattr(link, "thumbnail_version"):
                res += "?v=%s" % link.thumbnail_version
            return res
    else:
        return ''

def filename_to_s3_bucket(file_name):
    num = ord(file_name[-1]) % len(g.s3_media_buckets)
    return g.s3_media_buckets[num]

def s3_upload_media(data, file_name, file_type, mime_type, never_expire,
                    replace=False):
    bucket = filename_to_s3_bucket(file_name)
    s3cp.send_file(bucket, file_name+file_type, data, mime_type,
                       never_expire=never_expire,
                       replace=replace,
                       reduced_redundancy=True)
    if g.s3_media_direct:
        return "http://%s/%s/%s%s" % (s3_direct_url, bucket, file_name, file_type)
    else:
        return "http://%s/%s%s" % (bucket, file_name, file_type)

def get_filename_from_content(contents):
    sha = hashlib.sha1(contents).digest()
    return base64.urlsafe_b64encode(sha[0:MEDIA_FILENAME_LENGTH])

def upload_media(image, never_expire=True, file_type='.jpg'):
    """Given a link and an image, uploads the image to s3 into an image
    based on the link's fullname"""
    url = str()
    mime_type = mimetypes.guess_type("file" + file_type)[0] # Requires a filename with the extension
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
            optimize_png(f.name, g.png_optimizer)
        elif file_type == ".jpg":
            optimize_jpeg(f.name, g.jpeg_optimizer)
        contents = open(f.name).read()
        file_name = get_filename_from_content(contents)
        if g.media_store == "s3":
            url = s3_upload_media(contents, file_name=file_name, mime_type=mime_type, file_type=file_type, never_expire=True)
    finally:
        os.unlink(f.name)
    return url


def update_link(link, thumbnail, media_object, thumbnail_size=None):
    """Sets the link's has_thumbnail and media_object attributes iin the
    database."""
    if thumbnail:
        link.thumbnail_url = thumbnail
        link.thumbnail_size = thumbnail_size
        g.log.debug("Updated link with thumbnail: %s" % link.thumbnail_url)
        
    if media_object:
        link.media_object = media_object

    link._commit()


def _set_media(embedly_services, link, force=False):
    if link.is_self:
        return
    if not force and link.promoted:
        return
    elif not force and (link.has_thumbnail or link.media_object):
        return

    scraper = Scraper.for_url(embedly_services, link.url)
    thumbnail, media_object = scraper.scrape()

    if media_object:
        # the scraper should be able to make a media embed out of the
        # media object it just gave us. if not, null out the media object
        # to protect downstream code
        res = scraper.media_embed(media_object)

        if not res:
            print "%s made a bad media obj for link %s" % (scraper, link._id36)
            media_object = None

    thumbnail_url = upload_media(thumbnail) if thumbnail else None
    thumbnail_size = thumbnail.size if thumbnail else None

    update_link(link, thumbnail_url, media_object, thumbnail_size=thumbnail_size)

def force_thumbnail(link, image_data, never_expire=True, file_type=".jpg"):
    image = str_to_image(image_data)
    image = _prepare_image(image)
    thumb_url = upload_media(image, never_expire=never_expire, file_type=file_type)
    update_link(link, thumbnail=thumb_url, media_object=None, thumbnail_size=image.size)

def upload_icon(file_name, image_data, size):
    assert g.media_store == 's3'
    image = str_to_image(image_data)
    image.format = 'PNG'
    image.thumbnail(size, Image.ANTIALIAS)
    icon_data = _image_to_str(image)
    return s3_upload_media(icon_data,
                           file_name=file_name,
                           mime_type='image/png',
                           file_type='.png',
                           never_expire=True,
                           replace=True)

def can_upload_icon():
    return g.media_store == 's3'


def get_media_embed(media_object):
    if not isinstance(media_object, dict):
        return

    if "oembed" not in media_object:
        return

    return _EmbedlyScraper.media_embed(media_object)


class MediaEmbed(object):
    width = None
    height = None
    content = None
    scrolling = False

    def __init__(self, height, width, content, scrolling=False):
        self.height = int(height)
        self.width = int(width)
        self.content = content
        self.scrolling = scrolling


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
    def for_url(cls, embedly_services, url):
        url_domain = domain(url)
        domain_embedly_regex = embedly_services.get(url_domain, None)

        if domain_embedly_regex and re.match(domain_embedly_regex, url):
            return _EmbedlyScraper(url)
        return _ThumbnailOnlyScraper(url)

    def scrape(self):
        # should return a 2-tuple of: thumbnail, media_object
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
        return thumbnail, None

    def _extract_image_urls(self, soup):
        for img in soup.findAll("img", src=True):
            yield urlparse.urljoin(self.url, img["src"])

    def _find_thumbnail_image(self):
        content_type, content = _fetch_url(self.url)

        # if it's an image. it's pretty easy to guess what we should thumbnail.
        if "image" in content_type:
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
    EMBEDLY_API_URL = "http://api.embed.ly/1/oembed"

    def __init__(self, url):
        self.url = url

    @classmethod
    def _utf8_encode(cls, input):
        """UTF-8 encodes any strings in an object (from json.loads)"""
        if isinstance(input, dict):
            return {cls._utf8_encode(key): cls._utf8_encode(value)
                    for key, value in input.iteritems()}
        elif isinstance(input, list):
            return [cls._utf8_encode(item)
                    for item in input]
        elif isinstance(input, unicode):
            return input.encode('utf-8')
        else:
            return input

    def scrape(self):
        params = urllib.urlencode({
            "url": self.url,
            "format": "json",
            "maxwidth": 600,
            "key": g.embedly_api_key,
        })
        response = urllib2.urlopen(self.EMBEDLY_API_URL + "?" + params)
        oembed = json.load(response, object_hook=self._utf8_encode)

        if not oembed:
            return None, None

        if oembed.get("type") == "photo":
            thumbnail_url = oembed.get("url")
        else:
            thumbnail_url = oembed.get("thumbnail_url")
        thumbnail = _make_thumbnail_from_url(thumbnail_url, referer=self.url)

        embed = {}
        if oembed.get("type") in ("video", "rich"):
            embed = {
                "type": domain(self.url),
                "oembed": oembed,
            }

        return thumbnail, embed

    @classmethod
    def media_embed(cls, media_object):
        oembed = media_object["oembed"]

        html = oembed.get("html")
        width = oembed.get("width")
        height = oembed.get("height")
        if not (html and width and height):
            return

        return MediaEmbed(
            width=width,
            height=height,
            content=html,
        )


@memoize("media.embedly_services", time=3600)
def _fetch_embedly_services():
    response = urllib2.urlopen("http://api.embed.ly/1/services/python")
    service_data = json.load(response)

    patterns_by_domain = collections.defaultdict(set)
    for service in service_data:
        for domain in [service["domain"]] + service["subdomains"]:
            patterns_by_domain[domain].update(service["regex"])

    return {domain: "(?:%s)" % "|".join(patterns)
            for domain, patterns in patterns_by_domain.iteritems()}


def run():
    embedly_services = _fetch_embedly_services()

    @g.stats.amqp_processor('scraper_q')
    def process_link(msg):
        fname = msg.body
        link = Link._by_fullname(msg.body, data=True)

        try:
            TimeoutFunction(_set_media, 30)(embedly_services, link)
        except TimeoutFunctionException:
            print "Timed out on %s" % fname
        except KeyboardInterrupt:
            raise
        except:
            print "Error fetching %s" % fname
            print traceback.format_exc()

    amqp.consume_items('scraper_q', process_link)
