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

import subprocess

from pylons import g, config

from r2.models.link import Link
from r2.lib import s3cp
from r2.lib.utils import timeago, fetch_things2
from r2.lib.utils import TimeoutFunction, TimeoutFunctionException
from r2.lib.db.operators import desc
from r2.lib.scraper import make_scraper, str_to_image, image_to_str, prepare_image
from r2.lib import amqp
from r2.lib.nymph import optimize_png

import Image

import os
import tempfile
import traceback

import base64
import hashlib

import mimetypes

s3_direct_url = "s3.amazonaws.com"

threads = 20
log = g.log

MEDIA_FILENAME_LENGTH = 12


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


def set_media(link, force = False):
    if link.is_self:
        return
    if not force and link.promoted:
        return
    elif not force and (link.has_thumbnail or link.media_object):
        return
        
    scraper = make_scraper(link.url)

    thumbnail = scraper.thumbnail()
    media_object = scraper.media_object()

    if media_object:
        # the scraper should be able to make a media embed out of the
        # media object it just gave us. if not, null out the media object
        # to protect downstream code
        res = scraper.media_embed(**media_object)

        if not res:
            print "%s made a bad media obj for link %s" % (scraper, link._id36)
            media_object = None
    
    thumbnail_url = upload_media(thumbnail) if thumbnail else None
    thumbnail_size = thumbnail.size if thumbnail else None

    update_link(link, thumbnail_url, media_object, thumbnail_size=thumbnail_size)

def force_thumbnail(link, image_data, never_expire=True, file_type=".jpg"):
    image = str_to_image(image_data)
    image = prepare_image(image)
    thumb_url = upload_media(image, never_expire=never_expire, file_type=file_type)
    update_link(link, thumbnail=thumb_url, media_object=None, thumbnail_size=image.size)

def upload_icon(file_name, image_data, size):
    assert g.media_store == 's3'
    image = str_to_image(image_data)
    image.format = 'PNG'
    image.thumbnail(size, Image.ANTIALIAS)
    icon_data = image_to_str(image)
    return s3_upload_media(icon_data,
                           file_name=file_name,
                           mime_type='image/png',
                           file_type='.png',
                           never_expire=True,
                           replace=True)

def can_upload_icon():
    return g.media_store == 's3'

def run():
    @g.stats.amqp_processor('scraper_q')
    def process_link(msg):
        def _process_link(fname):
            link = Link._by_fullname(fname, data=True)
            set_media(link)

        fname = msg.body
        try:
            TimeoutFunction(_process_link, 30)(fname)
        except TimeoutFunctionException:
            print "Timed out on %s" % fname
        except KeyboardInterrupt:
            raise
        except:
            print "Error fetching %s" % fname
            print traceback.format_exc()

    amqp.consume_items('scraper_q', process_link)
