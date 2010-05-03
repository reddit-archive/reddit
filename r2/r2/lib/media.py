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
# All portions of the code written by CondeNet are Copyright (c) 2006-2009
# CondeNet, Inc. All Rights Reserved.
################################################################################

from pylons import g, config

from r2.models.link import Link
from r2.lib import s3cp
from r2.lib.utils import timeago, fetch_things2
from r2.lib.utils import TimeoutFunction, TimeoutFunctionException
from r2.lib.db.operators import desc
from r2.lib.scraper import make_scraper, str_to_image, image_to_str, prepare_image
from r2.lib import amqp
from r2.lib.contrib.nymph import optimize_png

import tempfile
import traceback

s3_thumbnail_bucket = g.s3_thumb_bucket
threads = 20
log = g.log

def thumbnail_url(link):
    """Given a link, returns the url for its thumbnail based on its fullname"""
    return 'http:/%s%s.png' % (s3_thumbnail_bucket, link._fullname)

def upload_thumb(link, image):
    """Given a link and an image, uploads the image to s3 into an image
    based on the link's fullname"""
    f = tempfile.NamedTemporaryFile(suffix = '.png')
    image.save(f)

    resource = s3_thumbnail_bucket + link._fullname + '.png'
    log.debug('uploading to s3: %s' % link._fullname)
    s3cp.send_file(optimize_png(f.name, g.png_optimizer),
                   resource, 'image/png', 'public-read', None, False)
    log.debug('thumbnail %s: %s' % (link._fullname, thumbnail_url(link)))


def update_link(link, thumbnail, media_object):
    """Sets the link's has_thumbnail and media_object attributes iin the
    database."""
    if thumbnail:
        link.has_thumbnail = True

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

    if thumbnail:
        upload_thumb(link, thumbnail)

    update_link(link, thumbnail, media_object)

def force_thumbnail(link, image_data):
    image = str_to_image(image_data)
    image = prepare_image(image)
    upload_thumb(link, image)
    update_link(link, thumbnail = True, media_object = None)

def run():
    def process_msgs(msgs, chan):
        def _process_link(fname):
            link = Link._by_fullname(fname, data=True, return_dict=False)
            set_media(link)

        for msg in msgs:
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

    amqp.handle_items('scraper_q', process_msgs, limit=1)
