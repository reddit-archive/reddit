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
# All portions of the code written by CondeNet are Copyright (c) 2006-2008
# CondeNet, Inc. All Rights Reserved.
################################################################################

from pylons import g
from r2.lib import utils
from r2.lib.memoize import memoize

from urllib2 import Request, HTTPError, URLError, urlopen
import urlparse, re, urllib, logging, StringIO, logging
import Image, ImageFile

log = g.log
useragent = g.useragent

chunk_size = 1024
thumbnail_size = 70, 70

def image_to_str(image):
    s = StringIO.StringIO()
    image.save(s, image.format)
    s.seek(0)
    return s.read()

def str_to_image(s):
    s = StringIO.StringIO(s)
    s.seek(0)
    image = Image.open(s)
    return image

@memoize('media.fetch_url')
def fetch_url(url, referer = None, retries = 1, dimension = False):
    cur_try = 0
    #log.debug('fetching: %s' % url)
    nothing = None if dimension else (None, None)
    while True:
        try:
            req = Request(url)
            if useragent:
                req.add_header('User-Agent', useragent)
            if referer:
                req.add_header('Referer', referer)

            open_req = urlopen(req)

            #if we only need the dimension of the image, we may not
            #need the entire image
            if dimension:
                content = open_req.read(chunk_size)
            else:
                content = open_req.read()
            content_type = open_req.headers.get('content-type')

            if 'image' in content_type:
                p = ImageFile.Parser()
                new_data = content
                while not p.image and new_data:
                    p.feed(new_data)
                    new_data = open_req.read(chunk_size)
                    content += new_data

                #return the size, or return the data
                if dimension and p.image:
                    return p.image.size
                elif dimension:
                    return nothing
            elif dimension:
                #expected an image, but didn't get one
                return nothing

            return content_type, content

        except (URLError, HTTPError), e:
            cur_try += 1
            if cur_try >= retries:
                log.debug('error while fetching: %s referer: %s' % (url, referer))
                log.debug(e)
                return nothing
        finally:
            if 'open_req' in locals():
                open_req.close()

img_rx = re.compile(r'<\s*(?:img)[^>]*src\s*=\s*[\"\']?([^\"\'\s>]*)[^>]*', re.IGNORECASE | re.S) 
def image_urls(base_url, html):
    for match in img_rx.findall(html):
        image_url = urlparse.urljoin(base_url, match)
        yield image_url

class Scraper:
    def __init__(self, url):
        self.url = url
        self.content = None
        self.content_type = None

    def download(self):
        self.content_type, self.content = fetch_url(self.url)

    def largest_image_url(self):
        if not self.content:
            self.download()

        #if download didn't work
        if not self.content:
            return None

        max_area = 0
        max_url = None

        #if the original url was an image, use that
        if 'image' in self.content_type:
            urls = [self.url]
        else:
            urls = image_urls(self.url, self.content)

        for image_url in urls:
            size = fetch_url(image_url, referer = self.url, dimension = True)
            if not size:
                continue

            area = size[0] * size[1]

            #ignore little images
            if area < 5000:
                log.debug('ignore little %s' % image_url)
                continue

            #ignore excessively long/wide images
            if max(size) / min(size) > 1.5:
                log.debug('ignore dimensions %s' % image_url)
                continue

            if area > max_area:
                max_area = area
                max_url = image_url

        return max_url

    def thumbnail(self):
        image_url = self.largest_image_url()
        if image_url:
            content_type, image_str = fetch_url(image_url, referer = self.url)
            if image_str:
                image = str_to_image(image_str)
                image.thumbnail(thumbnail_size, Image.ANTIALIAS)
                return image

    def media_object(self):
        return None

youtube_rx = re.compile('.*v=([A-Za-z0-9-_]+).*')

class YoutubeScraper(Scraper):
    media_template = '<object width="425" height="350"><param name="movie" value="http://www.youtube.com/v/%s"></param><param name="wmode" value="transparent"></param><embed src="http://www.youtube.com/v/%s" type="application/x-shockwave-flash" wmode="transparent" width="425" height="350"></embed></object>'

    def __init__(self, url):
        m = youtube_rx.match(url)
        if m:
            self.video_id = m.groups()[0]
        else:
            #if it's not a youtube video, just treat it like a normal page
            log.debug('reverting youtube to regular scraper: %s' % url)
            self.__class__ = Scraper

        Scraper.__init__(self, url)

    def largest_image_url(self):
         return 'http://img.youtube.com/vi/%s/default.jpg' % self.video_id

    def media_object(self):
        return self.media_template % (self.video_id, self.video_id)

gootube_rx = re.compile('.*videoplay\?docid=([A-Za-z0-9-_]+).*')
gootube_thumb_rx = re.compile(".*thumbnail:\s*\'(http://[^/]+/ThumbnailServer2[^\']+)\'.*", re.IGNORECASE | re.S)

class GootubeScraper(Scraper):
    media_template = '<embed style="width:400px; height:326px;" id="VideoPlayback" type="application/x-shockwave-flash" src="http://video.google.com/googleplayer.swf?docId=%s&hl=en" flashvars=""> </embed>'
    def __init__(self, url):
        m = gootube_rx.match(url)
        if m:
            self.video_id = m.groups()[0]
        else:
            self.__class__ = Scraper
        Scraper.__init__(self, url)

    def largest_image_url(self):
        if not self.content:
            self.download()

        if not self.content:
            return None

        m = gootube_thumb_rx.match(self.content)
        if m:
            image_url = m.groups()[0]
            image_url = utils.safe_eval_str(image_url)
            return image_url

    def media_object(self):
        return self.media_template % self.video_id

scrapers = {'youtube.com': YoutubeScraper,
            'video.google.com': GootubeScraper}

youtube_in_google_rx = re.compile('.*<div class="original-text">.*href="(http://[^"]*youtube.com/watch[^"]+).*', re.S)

def make_scraper(url):
    scraper = scrapers.get(utils.domain(url), Scraper)
    
    #sometimes youtube scrapers masquerade as google scrapers
    if scraper == GootubeScraper:
        h = Scraper(url)
        h.download()
        m = youtube_in_google_rx.match(h.content)
        if m:
            youtube_url = m.groups()[0]
            log.debug('%s is really %s' % (url, youtube_url))
            url = youtube_url
            return make_scraper(url)
    return scraper(url)

def test():
    from r2.lib.pool2 import WorkQueue
    jobs = []
    f = open('/tmp/testurls.txt')
    for url in f:
        if url.startswith('#'):
            continue
        if url.startswith('/info'):
            continue
        
        def make_job(url):
            def fetch(url):
                print 'START', url
                url = url.strip()
                h = make_scraper(url)
                image_url = h.largest_image_url()
                print 'DONE', image_url
            return lambda: fetch(url)

        jobs.append(make_job(url))

    print jobs[0]()
    #wq = WorkQueue(jobs)
    #wq.start()            

if __name__ == '__main__':
    test()
