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
from r2.lib.workqueue import WorkQueue
from r2.lib import s3cp
from r2.lib.utils import timeago, fetch_things2
from r2.lib.db.operators import desc
from r2.lib.scraper import make_scraper, str_to_image, image_to_str, prepare_image

import tempfile
from Queue import Queue

s3_thumbnail_bucket = g.s3_thumb_bucket
media_period = g.media_period
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
    s3cp.send_file(f.name, resource, 'image/png', 'public-read', None, False)
    log.debug('thumbnail %s: %s' % (link._fullname, thumbnail_url(link)))

def make_link_info_job(results, link, useragent):
    """Returns a unit of work to send to a work queue that downloads a
    link's thumbnail and media object. Places the result in the results
    dict"""
    def job():
        try:
            scraper = make_scraper(link.url)

            thumbnail = scraper.thumbnail()
            media_object = scraper.media_object()

            if thumbnail:
                upload_thumb(link, thumbnail)

            results[link] = (thumbnail, media_object)
        except:
            log.warning('error fetching %s %s' % (link._fullname, link.url))
            raise

    return job

def update_link(link, thumbnail, media_object):
    """Sets the link's has_thumbnail and media_object attributes iin the
    database."""
    if thumbnail:
        link.has_thumbnail = True

    if media_object:
        link.media_object = media_object

    link._commit()

def process_new_links(period = media_period, force = False):
    """Fetches links from the last period and sets their media
    properities. If force is True, it will fetch properities for links
    even if the properties already exist"""
    links = Link._query(Link.c._date > timeago(period), sort = desc('_date'),
                        data = True)
    results = {}
    jobs = []
    for link in fetch_things2(links):
        if link.is_self or link.promoted:
            continue
        elif not force and (link.has_thumbnail or link.media_object):
            continue

        jobs.append(make_link_info_job(results, link, g.useragent))

    #send links to a queue
    wq = WorkQueue(jobs, num_workers = 20, timeout = 30)
    wq.start()
    wq.jobs.join()

    #when the queue is finished, do the db writes in this thread
    for link, info in results.items():
        update_link(link, info[0], info[1])

def set_media(link):
    """Sets the media properties for a single link."""
    results = {}
    make_link_info_job(results, link, g.useragent)()
    update_link(link, *results[link])

def force_thumbnail(link, image_data):
    image = str_to_image(image_data)
    image = prepare_image(image)
    upload_thumb(link, image)
    update_link(link, thumbnail = True, media_object = None)
    
