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

from pylons import g
from r2.lib import utils
from r2.lib.memoize import memoize

from urllib2 import Request, HTTPError, URLError, urlopen
from httplib import InvalidURL
import urlparse, re, urllib, logging, StringIO, logging
import Image, ImageFile, math
from BeautifulSoup import BeautifulSoup

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

def prepare_image(image):
    image = square_image(image)
    image.thumbnail(thumbnail_size, Image.ANTIALIAS)
    return image

def image_entropy(img):
    """calculate the entropy of an image"""
    hist = img.histogram()
    hist_size = sum(hist)
    hist = [float(h) / hist_size for h in hist]

    return -sum([p * math.log(p, 2) for p in hist if p != 0])

def square_image(img):
    """if the image is taller than it is wide, square it off. determine
    which pieces to cut off based on the entropy pieces."""
    x,y = img.size
    while y > x:
        #slice 10px at a time until square
        slice_height = min(y - x, 10)

        bottom = img.crop((0, y - slice_height, x, y))
        top = img.crop((0, 0, x, slice_height))

        #remove the slice with the least entropy
        if image_entropy(bottom) < image_entropy(top):
            img = img.crop((0, 0, x, y - slice_height))
        else:
            img = img.crop((0, slice_height, x, y))

        x,y = img.size

    return img

def clean_url(url):
    """url quotes unicode data out of urls"""
    s = url
    url = url.encode('utf8')
    url = ''.join([urllib.quote(c) if ord(c) >= 127 else c for c in url])
    return url

def fetch_url(url, referer = None, retries = 1, dimension = False):
    cur_try = 0
    log.debug('fetching: %s' % url)
    nothing = None if dimension else (None, None)
    url = clean_url(url)
    #just basic urls
    if not url.startswith('http://'):
        return nothing
    while True:
        try:
            req = Request(url)
            if useragent:
                req.add_header('User-Agent', useragent)
            if referer:
                req.add_header('Referer', referer)

            open_req = urlopen(req)

            #if we only need the dimension of the image, we may not
            #need to download the entire thing
            if dimension:
                content = open_req.read(chunk_size)
            else:
                content = open_req.read()
            content_type = open_req.headers.get('content-type')

            if not content_type:
                return nothing

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

        except (URLError, HTTPError, InvalidURL), e:
            cur_try += 1
            if cur_try >= retries:
                log.debug('error while fetching: %s referer: %s' % (url, referer))
                log.debug(e)
                return nothing
        finally:
            if 'open_req' in locals():
                open_req.close()

@memoize('media.fetch_size')
def fetch_size(url, referer = None, retries = 1):
    return fetch_url(url, referer, retries, dimension = True)

class Scraper:
    def __init__(self, url):
        self.url = url
        self.content = None
        self.content_type = None
        self.soup = None

    def download(self):
        self.content_type, self.content = fetch_url(self.url)
        if self.content_type and 'html' in self.content_type and self.content:
            self.soup = BeautifulSoup(self.content)

    def image_urls(self):
        #if the original url was an image, use that
        if 'image' in self.content_type:
            yield self.url
        elif self.soup:
            images = self.soup.findAll('img', src = True)
            for i in images:
                image_url = urlparse.urljoin(self.url, i['src'])
                yield image_url

    def largest_image_url(self):
        if not self.content:
            self.download()

        #if download didn't work
        if not self.content or not self.content_type:
            return None

        max_area = 0
        max_url = None

        for image_url in self.image_urls():
            size = fetch_size(image_url, referer = self.url)
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

            #penalize images with "sprite" in their name
            if 'sprite' in image_url.lower():
                log.debug('penalizing sprite %s' % image_url)
                area /= 10

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
                try:
                    image = prepare_image(image)
                except IOError, e:
                    #can't read interlaced PNGs, ignore
                    if 'interlaced' in e.message:
                        return
                    raise
                return image

    def media_object(self):
        return None

class MediaScraper(Scraper):
    media_template = ""
    thumbnail_template = ""
    video_id_rx = None
    
    def __init__(self, url):
        m = self.video_id_rx.match(url)
        if m:
            self.video_id = m.groups()[0]
        else:
            #if we can't find the id just treat it like a normal page
            log.debug('reverting to regular scraper: %s' % url)
            self.__class__ = Scraper
        Scraper.__init__(self, url)

    def largest_image_url(self):
        return self.thumbnail_template.replace('$video_id', self.video_id)

    def media_object(self):
        return self.media_template.replace('$video_id', self.video_id)
    
def youtube_in_google(google_url):
    h = Scraper(google_url)
    h.download()
    try:
        youtube_url = h.soup.find('div', 'original-text').findNext('a')['href']
        log.debug('%s is really %s' % (google_url, youtube_url))
        return youtube_url
    except AttributeError, KeyError:
        pass

def make_scraper(url):
    domain = utils.domain(url)
    scraper = Scraper
    for suffix, cls in scrapers.iteritems():
        if domain.endswith(suffix):
            scraper = cls
            break
    
    #sometimes youtube scrapers masquerade as google scrapers
    if scraper == GootubeScraper:
        youtube_url = youtube_in_google(url)
        if youtube_url:
            return make_scraper(youtube_url)
    return scraper(url)


########## site-specific video scrapers ##########

#Youtube
class YoutubeScraper(MediaScraper):
    media_template = '<object width="425" height="350"><param name="movie" value="http://www.youtube.com/v/$video_id"></param><param name="wmode" value="transparent"></param><embed src="http://www.youtube.com/v/$video_id" type="application/x-shockwave-flash" wmode="transparent" width="425" height="350"></embed></object>'
    thumbnail_template = 'http://img.youtube.com/vi/$video_id/default.jpg'
    video_id_rx = re.compile('.*v=([A-Za-z0-9-_]+).*')

#Metacage
class MetacafeScraper(MediaScraper):
    media_template = '<embed src="$video_id" width="400" height="345" wmode="transparent" pluginspage="http://www.macromedia.com/go/getflashplayer" type="application/x-shockwave-flash"> </embed>'
    video_id_rx = re.compile('.*/watch/([^/]+)/.*')

    def media_object(self):
        if not self.soup:
            self.download()

        if self.soup:
            video_url =  self.soup.find('link', rel = 'video_src')['href']
            return self.media_template.replace('$video_id', video_url)

    def largest_image_url(self):
        if not self.soup:
            self.download()

        if self.soup:
            return self.soup.find('link', rel = 'image_src')['href']

#Google Video
gootube_thumb_rx = re.compile(".*thumbnail:\s*\'(http://[^/]+/ThumbnailServer2[^\']+)\'.*", re.IGNORECASE | re.S)
class GootubeScraper(MediaScraper):
    media_template = '<embed style="width:400px; height:326px;" id="VideoPlayback" type="application/x-shockwave-flash" src="http://video.google.com/googleplayer.swf?docId=$video_id&hl=en" flashvars=""> </embed>'
    video_id_rx = re.compile('.*videoplay\?docid=([A-Za-z0-9-_]+).*')    

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

scrapers = {'youtube.com': YoutubeScraper,
            'video.google.com': GootubeScraper,
            'metacafe.com': MetacafeScraper}

def test():
    #from r2.lib.pool2 import WorkQueue
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
