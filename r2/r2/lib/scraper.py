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

from pylons import g
from r2.lib import utils
from r2.lib.memoize import memoize
import simplejson as json

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
    if not url.startswith(('http://', 'https://')):
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

class MediaEmbed(object):
    width     = None
    height    = None
    content   = None
    scrolling = False

    def __init__(self, height, width, content, scrolling = False):
        self.height    = int(height)
        self.width     = int(width)
        self.content   = content
        self.scrolling = scrolling

class Scraper:
    def __init__(self, url):
        self.url = url
        self.content = None
        self.content_type = None
        self.soup = None

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.url)

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

        if self.soup:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image['content']:
                log.debug("Using og:image")
                return og_image['content']
            thumbnail_spec = self.soup.find('link', rel = 'image_src')
            if thumbnail_spec and thumbnail_spec['href']:
                log.debug("Using image_src")
                return thumbnail_spec['href']

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
        for deepscraper in deepscrapers:
            ds = deepscraper()
            found = ds.find_media_object(self)
            if found:
                return found

    @classmethod
    def media_embed(cls):
        raise NotImplementedError

class MediaScraper(Scraper):
    media_template = ""
    thumbnail_template = ""
    video_id = None
    video_id_rx = None

    def __init__(self, url):
        Scraper.__init__(self, url)

        # first try the simple regex against the URL. If that fails,
        # see if the MediaScraper subclass has its own extraction
        # function
        if self.video_id_rx:
            m = self.video_id_rx.match(url)
            if m:
                self.video_id = m.groups()[0]
        if not self.video_id:
            video_id = self.video_id_extract()
            if video_id:
                self.video_id = video_id
        if not self.video_id:
            #if we still can't find the id just treat it like a normal page
            log.debug('reverting to regular scraper: %s' % url)
            self.__class__ = Scraper

    def video_id_extract(self):
        return None

    def largest_image_url(self):
        if self.thumbnail_template:
            return self.thumbnail_template.replace('$video_id', self.video_id)
        else:
            return Scraper.largest_image_url(self)

    def media_object(self):
        return dict(video_id = self.video_id,
                    type = self.domains[0])

    @classmethod
    def media_embed(cls, video_id = None, height = None, width = None, **kw):
        content = cls.media_template.replace('$video_id', video_id)
        return MediaEmbed(height = height or cls.height,
                          width = width or cls.width,
                          content = content)
    
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
    for suffix, clses in scrapers.iteritems():
        for cls in clses:
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

class YoutubeScraper(MediaScraper):
    domains = ['youtube.com']
    height = 295
    width = 480
    media_template = '<object width="490" height="295"><param name="movie" value="http://www.youtube.com/v/$video_id&fs=1"></param><param name="wmode" value="transparent"></param><param name="allowFullScreen" value="true"></param><embed src="http://www.youtube.com/v/$video_id&fs=1" type="application/x-shockwave-flash" wmode="transparent" allowFullScreen="true" width="480" height="295"></embed></object>'
    thumbnail_template = 'http://img.youtube.com/vi/$video_id/default.jpg'
    video_id_rx = re.compile('.*v=([A-Za-z0-9-_]+).*')
    video_deeplink_rx = re.compile('.*#t=(\d+)m(\d+)s.*')

    def video_id_extract(self):
        vid = self.video_id_rx.match(self.url)
        if(vid):
            video_id = vid.groups()[0]
        d = self.video_deeplink_rx.match(self.url)
        if(d):
            seconds = int(d.groups()[0])*60 + int(d.groups()[1])
            video_id += "&start=%d" % seconds
        return video_id

    def largest_image_url(self):
        # Remove the deeplink part from the video id
        return self.thumbnail_template.replace("$video_id",
                                               self.video_id.split("&")[0])

class TedScraper(MediaScraper):
    domains = ['ted.com']
    height = 326
    width = 446
    media_template = '<object width="446" height="326"><param name="movie" value="http://video.ted.com/assets/player/swf/EmbedPlayer.swf"></param><param name="allowFullScreen" value="true" /><param name="wmode" value="transparent"></param><param name="bgColor" value="#ffffff"></param> <param name="flashvars" value="$video_id" /><embed src="http://video.ted.com/assets/player/swf/EmbedPlayer.swf" pluginspace="http://www.macromedia.com/go/getflashplayer" type="application/x-shockwave-flash" wmode="transparent" bgColor="#ffffff" width="446" height="326" allowFullScreen="true" flashvars="$video_id"></embed></object>'
    flashvars_rx = re.compile('.*flashvars="(.*)".*')

    def video_id_extract(self):
        if "/talks/" in self.url:
            content_type, content = fetch_url(self.url.replace("/talks/","/talks/embed/"))
            if content:
                m = self.flashvars_rx.match(content)
                if m:
                    return m.groups()[0]
    def largest_image_url(self):
        if not self.soup:
            self.download()

        if self.soup:
            return self.soup.find('link', rel = 'image_src')['href']


class MetacafeScraper(MediaScraper):
    domains = ['metacafe.com']
    height = 345
    width  = 400
    media_template = '<embed src="$video_id" width="400" height="345" wmode="transparent" pluginspage="http://www.macromedia.com/go/getflashplayer" type="application/x-shockwave-flash"> </embed>'
    video_id_rx = re.compile('.*/watch/([^/]+)/.*')

    def media_object(self):
        if not self.soup:
            self.download()

        if self.soup:
            video_url =  self.soup.find('link', rel = 'video_src')['href']
            return dict(video_id = video_url,
                        type = self.domains[0])

class GootubeScraper(MediaScraper):
    domains = ['video.google.com']
    height = 326
    width  = 400
    media_template = '<embed style="width:400px; height:326px;" id="VideoPlayback" type="application/x-shockwave-flash" src="http://video.google.com/googleplayer.swf?docId=$video_id&hl=en" flashvars=""> </embed>'
    video_id_rx = re.compile('.*videoplay\?docid=([A-Za-z0-9-_]+).*')
    gootube_thumb_rx = re.compile(".*thumbnail:\s*\'(http://[^/]+/ThumbnailServer2[^\']+)\'.*", re.IGNORECASE | re.S)

    def largest_image_url(self):
        if not self.content:
            self.download()

        if not self.content:
            return None

        m = self.gootube_thumb_rx.match(self.content)
        if m:
            image_url = m.groups()[0]
            image_url = utils.safe_eval_str(image_url)
            return image_url

class VimeoScraper(MediaScraper):
    domains = ['vimeo.com']
    height = 448
    width = 520
    media_template = '<embed src="$video_id" width="520" height="448" wmode="transparent" pluginspage="http://www.macromedia.com/go/getflashplayer" type="application/x-shockwave-flash"> </embed>'
    video_id_rx = re.compile('.*/(.*)')

    def media_object(self):
        if not self.soup:
            self.download()

        if self.soup:
            video_url =  self.soup.find('link', rel = 'video_src')['href']
            return dict(video_id = video_url,
                        type = self.domains[0])

class BreakScraper(MediaScraper):
    domains = ['break.com']
    height = 421
    width = 520
    media_template = '<object width="520" height="421"><param name="movie" value="$video_id"></param><param name="allowScriptAccess" value="always"></param><embed src="$video_id" type="application/x-shockwave-flash" allowScriptAccess="always" width="520" height="421"></embed></object>'
    video_id_rx = re.compile('.*/index/([^/]+).*');

    def video_id_extract(self):
        if not self.soup:
            self.download()

        if self.soup:
            video_src = self.soup.find('link', rel = 'video_src')
            if video_src and video_src['href']:
                return video_src['href']

class TheOnionScraper(MediaScraper):
    domains = ['theonion.com']
    height = 430
    width = 480
    media_template = """<object width="480" height="430">
                          <param name="allowfullscreen" value="true" />
                          <param name="allowscriptaccess" value="always" />
                          <param name="movie" value="http://www.theonion.com/content/themes/common/assets/onn_embed/embedded_player.swf?&amp;videoid=$video_id" />
                          <param name="wmode" value="transparent" />

                          <embed src="http://www.theonion.com/content/themes/common/assets/onn_embed/embedded_player.swf"
                                 width="480" height="430"
                                 wmode="transparent"
                                 pluginspage="http://www.macromedia.com/go/getflashplayer"
                                 type="application/x-shockwave-flash"
                                 flashvars="videoid=$video_id" >
                          </embed>
                        </object>"""
    video_id_rx = re.compile('.*/video/([^/?#]+).*')

    def media_object(self):
        if not self.soup:
            self.download()

        if self.soup:
            video_url = self.soup.find('meta', attrs={'name': 'nid'})['content']
            return dict(video_id = video_url,
                        type = self.domains[0])

class CollegeHumorScraper(MediaScraper):
    domains = ['collegehumor.com']
    height = 390
    width = 520
    media_template = '<object type="application/x-shockwave-flash" data="http://www.collegehumor.com/moogaloop/moogaloop.swf?clip_id=$video_id&fullscreen=1" width="520" height="390" ><param name="allowfullscreen" value="true" /><param name="AllowScriptAccess" value="true" /><param name="movie" quality="best" value="http://www.collegehumor.com/moogaloop/moogaloop.swf?clip_id=$video_id&fullscreen=1" /></object>'
    video_id_rx = re.compile('.*video:(\d+).*');

class FunnyOrDieScraper(MediaScraper):
    domains = ['funnyordie.com']
    height = 438
    width = 464
    media_template = '<object width="464" height="438" classid="clsid:d27cdb6e-ae6d-11cf-96b8-444553540000" id="fodplayer"><param name="movie" value="http://player.ordienetworks.com/flash/fodplayer.swf?c79e63ac?key=$video_id" /><param name="flashvars" value="key=$video_id&autostart=true&internal=true" /><param name="allowfullscreen" value="true" /><embed width="464" height="438" flashvars="key=$video_id&autostart=true" allowfullscreen="true" quality="high" src="http://player.ordienetworks.com/flash/fodplayer.swf?c79e63ac" name="fodplayer" type="application/x-shockwave-flash"></embed></object>'
    thumbnail_template = 'http://assets1.ordienetworks.com/tmbs/$video_id/medium_2.jpg?c79e63ac'
    video_id_rx = re.compile('.*/videos/([^/]+)/.*')

class ComedyCentralScraper(MediaScraper):
    domains = ['comedycentral.com']
    height = 316
    width = 332
    media_template = '<embed FlashVars="videoId=$video_id" src="http://www.comedycentral.com/sitewide/video_player/view/default/swf.jhtml" quality="high" bgcolor="#cccccc" width="332" height="316" name="comedy_central_player" align="middle" allowScriptAccess="always" allownetworking="external" type="application/x-shockwave-flash" pluginspage="http://www.macromedia.com/go/getflashplayer"></embed>'
    video_id_rx = re.compile('.*videoId=(\d+).*')

class TheDailyShowScraper(MediaScraper):
    domains = ['thedailyshow.com']
    height = 353
    width = 360
    media_template = """<embed style='display:block' src='http://media.mtvnservices.com/mgid:cms:item:comedycentral.com:$video_id' width='360' height='301' type='application/x-shockwave-flash' wmode='window' allowFullscreen='true' flashvars='autoPlay=false' allowscriptaccess='always' allownetworking='all' bgcolor='#000000'></embed>"""

    def video_id_extract(self):
        "This is a bit of a hack"
        if not self.soup:
            self.download()

        if self.soup:
            embed_container = self.soup.find('div', {'class': 'videoplayerPromo module'})
            if embed_container:
                if embed_container['id'].startswith('promo_'):
                    video_id = embed_container['id'].split('_')[1]
                    return video_id

class ColbertNationScraper(ComedyCentralScraper):
    domains = ['colbertnation.com']
    video_id_rx = re.compile('.*videos/(\d+)/.*')

class LiveLeakScraper(MediaScraper):
    domains = ['liveleak.com']
    height = 370
    width = 450
    media_template = '<object width="450" height="370"><param name="movie" value="http://www.liveleak.com/e/$video_id"></param><param name="wmode" value="transparent"></param><embed src="http://www.liveleak.com/e/$video_id" type="application/x-shockwave-flash" wmode="transparent" width="450" height="370"></embed></object>'
    video_id_rx = re.compile('.*i=([a-zA-Z0-9_]+).*')

    def largest_image_url(self):
        if not self.soup:
            self.download()

        if self.soup:
            return self.soup.find('link', rel = 'videothumbnail')['href']

class DailyMotionScraper(MediaScraper):
    domains = ['dailymotion.com']
    height = 381
    width = 480
    media_template = '<object width="480" height="381"><param name="movie" value="$video_id"></param><param name="allowFullScreen" value="true"></param><param name="allowScriptAccess" value="always"></param><embed src="$video_id" type="application/x-shockwave-flash" width="480" height="381" allowFullScreen="true" allowScriptAccess="always"></embed></object>'
    video_id_rx = re.compile('.*/video/([a-zA-Z0-9]+)_.*')

    def media_object(self):
        if not self.soup:
            self.download()

        if self.soup:
            video_url =  self.soup.find('link', rel = 'video_src')['href']
            return dict(video_id = video_url,
                        type = self.domains[0])

class RevverScraper(MediaScraper):
    domains = ['revver.com']
    height = 392
    width = 480
    media_template = '<script src="http://flash.revver.com/player/1.0/player.js?mediaId:$video_id;width:480;height:392;" type="text/javascript"></script>'
    video_id_rx = re.compile('.*/video/([a-zA-Z0-9]+)/.*')

class EscapistScraper(MediaScraper):
    domains = ['escapistmagazine.com']
    height = 294
    width = 480
    media_template = """<script src="http://www.escapistmagazine.com/videos/embed/$video_id"></script>"""
    video_id_rx = re.compile('.*/videos/view/[A-Za-z-9-]+/([0-9]+).*')

class JustintvScraper(MediaScraper):
    """Can grab streams from justin.tv, but not clips"""
    domains = ['justin.tv']
    height = 295
    width = 353
    stream_media_template = """<object type="application/x-shockwave-flash" height="295" width="353" id="jtv_player_flash" data="http://www.justin.tv/widgets/jtv_player.swf?channel=$video_id" bgcolor="#000000"><param name="allowFullScreen" value="true" /><param name="allowScriptAccess" value="always" /><param name="allowNetworking" value="all" /><param name="movie" value="http://www.justin.tv/widgets/jtv_player.swf" /><param name="flashvars" value="channel=$video_id&auto_play=false&start_volume=25" /></object>"""
    video_id_rx = re.compile('^http://www.justin.tv/([a-zA-Z0-9_]+)[^/]*$')

    @classmethod
    def media_embed(cls, video_id, **kw):
        content = cls.stream_media_template.replace('$video_id', video_id)
        return MediaEmbed(height = cls.height,
                          width = cls.width,
                          content = content)

class SoundcloudScraper(MediaScraper):
    """soundcloud.com"""
    domains = ['soundcloud.com']
    height = 81
    width  = 400
    media_template = """<div style="font-size: 11px;">
                          <object height="81" width="100%">
                            <param name="movie"
                                   value="http://player.soundcloud.com/player.swf?track=$video_id">
                            </param>
                            <param name="allowscriptaccess" value="always"></param>
                            <embed allowscriptaccess="always" height="81"
                                   src="http://player.soundcloud.com/player.swf?track=$video_id"
                                   type="application/x-shockwave-flash"
                                   width="100%">
                            </embed>
                          </object>"""
    video_id_rx = re.compile('^http://soundcloud.com/[a-zA-Z0-9_-]+/([a-zA-Z0-9_-]+)')

class CraigslistScraper(MediaScraper):
    domains = ['craigslist.org']
    height = 480
    width  = 640
    max_size_kb = 50

    def video_id_extract(self):
        return self.url

    def media_object(self):
        if not self.soup:
            self.download()

        if self.soup:
            ub = self.soup.find('div', {'id': 'userbody'})
            if ub:
                ub = str(ub)
                if len(ub) <= self.max_size_kb * 1024:
                    return dict(content = ub,
                                type = self.domains[0])

    @classmethod
    def media_embed(cls, content, **kw):
        return MediaEmbed(height = cls.height,
                          width = cls.width,
                          content = content,
                          scrolling = True)

        
########## oembed rich-media scrapers ##########

class OEmbed(Scraper):
    """
    Oembed Scraper
    ==============
    Tries to use the oembed standard to create a media object.
    
    url_re: Regular Expression to match the incoming url against. 
    api_endpoint: Url of the api end point you are using. 
    api_params: Default Params to be sent with the outgoing request.
    """
    url_re = ''  
    api_endpoint = ''
    api_params = {}
    
    def __init__(self, url):
        Scraper.__init__(self, url)
        self.oembed = None
        
        #Fallback to the scraper if the url doesn't match
        if not self.url_re.match(self.url):
            self.__class__ = Scraper
        
    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.url)

    def utf8_encode(self, input):
        """UTF-8 encodes any strings in an object (from json.loads)"""
        if isinstance(input, dict):
            return {self.utf8_encode(key): self.utf8_encode(value)
                    for key, value in input.iteritems()}
        elif isinstance(input, list):
            return [self.utf8_encode(item)
                    for item in input]
        elif isinstance(input, unicode):
            return input.encode('utf-8')
        else:
            return input

    def download(self):
        self.api_params.update( { 'url':self.url})
        query = urllib.urlencode(self.api_params)      
        api_url = "%s?%s" % (self.api_endpoint, query)

        self.content_type, self.content = fetch_url(api_url)

        #Either a 404 or 500. 
        if not self.content:
            #raise ValueError('ISSUE CALLING %s' %api_url)
            log.warning('oEmbed call (%s) failed to return content for %s'
                    %(api_url, self.url))
            return None

        try:
            self.oembed = json.loads(self.content,
                                     object_hook=self.utf8_encode)
        except ValueError, e:
            log.error('oEmbed call (%s) return invalid json for %s' 
                      %(api_url, self.url))
            return None

    def image_urls(self):
        #if the original url was an image, use that
        if self.oembed and self.oembed.get('type') =='photo':
            yield self.oembed.get('url')
        elif self.oembed and self.oembed.get('thumbnail_url'):
            yield self.oembed.get('thumbnail_url')

    def largest_image_url(self):
        #Seems to be the default place to check if the download has happened.
        if not self.oembed:
            self.download()

        #if the original url was of the photo type
        if self.oembed and self.oembed.get('type') =='photo':
            return self.oembed.get('url')
        elif self.oembed and self.oembed.get('thumbnail_url'):
            return self.oembed.get('thumbnail_url')

    def media_object(self):
        #Seems to be the default place to check if the download has happened.
        if not self.oembed:
            self.download()

        if self.oembed and self.oembed.get('type') in ['video', 'rich']:
            for domain in self.domains:
                if self.url.find(domain) > -1:
                    return dict(type=domain, oembed=self.oembed)
        return None

    @classmethod
    def media_embed(cls, video_id = None, height = None, width = None, **kw):
        content = None
        oembed = kw.get('oembed')

        # check if oembed is there and has html
        if oembed and oembed.get('html'):
            content = oembed.get('html')
        if content and oembed.get('height') and oembed.get('width'):
            return MediaEmbed(height = oembed['height'],
                              width = oembed['width'],
                              content = content)

class EmbedlyOEmbed(OEmbed):
    """
    Embedly oEmbed Provider
    =======================
    documentation: http://api.embed.ly
    """
    domains = ['23hq.com', '5min.com', '99dollarmusicvideos.com',
        'abcnews.go.com', 'achewood.com', 'allthingsd.com', 'amazon.com',
        'aniboom.com', 'animoto.com', 'asofterworld.com', 'atom.com',
        'audioboo.com', 'bambuser.com', 'bandcamp.com', 'barelydigital.com',
        'barelypolitical.com', 'bigthink.com', 'blip.tv', 'bnter.com',
        'boston.com', 'brainbird.net', 'bravotv.com', 'break.com',
        'brizzly.com', 'cbsnews.com', 'channelfrederator.com', 'chart.ly',
        'cl.ly', 'clikthrough.com', 'clipfish.de', 'clipshack.com', 'cnbc.com',
        'cnn.com', 'colbertnation.com', 'collegehumor.com', 'color.com',
        'comedycentral.com', 'compete.com', 'confreaks.net', 'crackle.com',
        'craigslist.org', 'crocodoc.com', 'crunchbase.com', 'dailybooth.com',
        'dailymile.com', 'dailymotion.com', 'deviantart.com', 'digg.com',
        'dipdive.com', 'discovery.com', 'dotsub.com', 'dribbble.com',
        'edition.cnn.com', 'emberapp.com', 'escapistmagazine.com',
        'espn.go.com', 'facebook.com', 'fancast.com', 'flickr.com', 'fora.tv',
        'formspring.me', 'fotopedia.com', 'freemusicarchive.org',
        'funnyordie.com', 'gametrailers.com', 'gist.github.com',
        'globalpost.com', 'godtube.com', 'gogoyoko.com', 'google.com',
        'graphicly.com', 'grindtv.com', 'grooveshark.com', 'guardian.co.uk',
        'hark.com', 'howcast.com', 'huffduffer.com', 'hulu.com',
        'hungrynation.tv', 'ifood.tv', 'img.ly', 'imgur.com', 'indenti.ca',
        'indymogul.com', 'instagr.am', 'issuu.com', 'itunes.apple.com',
        'justin.tv', 'kickstarter.com', 'kinomap.com', 'kiva.org',
        'koldcast.tv', 'last.fm', 'lightbox.com', 'liveleak.com',
        'livestream.com', 'lockerz.com', 'logotv.com', 'lonelyplanet.com',
        'maps.google.com', 'meadd.com', 'mediamatters.org', 'meetup.com',
        'metacafe.com', 'metacdn.com', 'mixcloud.com', 'mixergy.com',
        'mlkshk.com', 'mobypicture.com', 'money.cnn.com', 'movies.yahoo.com',
        'msnbc.com', 'my.opera.com', 'myloc.me', 'myvideo.de',
        'nationalgeographic.com', 'nfb.ca', 'npr.org', 'nzonscreen.com',
        'overstream.net', 'ow.ly', 'pastebin.com', 'pastie.org',
        'phodroid.com', 'photobucket.com', 'photozou.jp',
        'picasaweb.google.com', 'picplz.com', 'pikchur.com', 'ping.fm',
        'polldaddy.com', 'polleverywhere.com', 'posterous.com', 'prezi.com',
        'qik.com', 'quantcast.com', 'questionablecontent.net', 'qwantz.com',
        'qwiki.com', 'radionomy.com', 'radioreddit.com', 'rdio.com',
        'recordsetter.com','redux.com', 'revision3.com', 'revver.com',
        'saynow.com', 'schooltube.com', 'sciencestage.com', 'scrapblog.com',
        'screencast.com', 'screenr.com', 'scribd.com', 'sendables.jibjab.com',
        'share.ovi.com', 'shitmydadsays.com', 'shopstyle.com', 'skitch.com',
        'slideshare.net', 'smugmug.com', 'snotr.com', 'socialcam.com',
        'someecards.com', 'soundcloud.com', 'speakerdeck.com', 'spike.com',
        'statsheet.com', 'status.net', 'storify.com', 'streetfire.net',
        'studivz.net', 'tangle.com', 'teachertube.com', 'techcrunch.tv',
        'ted.com', 'thedailyshow.com', 'theonion.com', 'threadbanger.com',
        'timetoast.com', 'tinypic.com', 'tmiweekly.com', 'traileraddict.com',
        'trailerspy.com', 'trooptube.tv', 'trutv.com', 'tumblr.com',
        'twitgoo.com', 'twitlonger.com', 'twitpic.com', 'twitrpix.com',
        'twitter.com', 'twitvid.com', 'ultrakawaii.com', 'urtak.com',
        'uservoice.com', 'ustream.com', 'viddler.com', 'video.forbes.com',
        'video.google.com', 'video.jardenberg.com', 'video.pbs.org',
        'video.yahoo.com', 'videos.nymag.com', 'vids.myspace.com', 'vimeo.com',
        'vodcars.com', 'washingtonpost.com', 'whitehouse.gov', 'whosay.com',
        'wikimedia.org', 'wikipedia.org', 'wistia.com', 'wordpress.tv',
        'worldstarhiphop.com', 'xiami.com', 'xkcd.com', 'xtranormal.com',
        'yfrog.com', 'youku.com', 'youtu.be', 'youtube.com', 'zapiks.com',
        'zero-inch.com']

    url_re = re.compile(
        'http:\\/\\/.*youtube\\.com\\/watch.*|' +
        'http:\\/\\/.*\\.youtube\\.com\\/v\\/.*|' +
        'https:\\/\\/.*youtube\\.com\\/watch.*|' +
        'https:\\/\\/.*\\.youtube\\.com\\/v\\/.*|' +
        'http:\\/\\/youtu\\.be\\/.*|' +
        'http:\\/\\/.*\\.youtube\\.com\\/user\\/.*|' +
        'http:\\/\\/.*\\.youtube\\.com\\/.*\\#.*\\/.*|' +
        'http:\\/\\/m\\.youtube\\.com\\/watch.*|' +
        'http:\\/\\/m\\.youtube\\.com\\/index.*|' +
        'http:\\/\\/.*\\.youtube\\.com\\/profile.*|' +
        'http:\\/\\/.*\\.youtube\\.com\\/view_play_list.*|' +
        'http:\\/\\/.*\\.youtube\\.com\\/playlist.*|' +
        'http:\\/\\/.*justin\\.tv\\/.*|' +
        'http:\\/\\/.*justin\\.tv\\/.*\\/b\\/.*|' +
        'http:\\/\\/.*justin\\.tv\\/.*\\/w\\/.*|' +
        'http:\\/\\/www\\.ustream\\.tv\\/recorded\\/.*|' +
        'http:\\/\\/www\\.ustream\\.tv\\/channel\\/.*|' +
        'http:\\/\\/www\\.ustream\\.tv\\/.*|' +
        'http:\\/\\/qik\\.com\\/video\\/.*|' +
        'http:\\/\\/qik\\.com\\/.*|' +
        'http:\\/\\/qik\\.ly\\/.*|' +
        'http:\\/\\/.*revision3\\.com\\/.*|' +
        'http:\\/\\/.*\\.dailymotion\\.com\\/video\\/.*|' +
        'http:\\/\\/.*\\.dailymotion\\.com\\/.*\\/video\\/.*|' +
        'http:\\/\\/collegehumor\\.com\\/video:.*|' +
        'http:\\/\\/collegehumor\\.com\\/video\\/.*|' +
        'http:\\/\\/www\\.collegehumor\\.com\\/video:.*|' +
        'http:\\/\\/www\\.collegehumor\\.com\\/video\\/.*|' +
        'http:\\/\\/.*twitvid\\.com\\/.*|' +
        'http:\\/\\/www\\.break\\.com\\/.*\\/.*|' +
        'http:\\/\\/vids\\.myspace\\.com\\/index\\.cfm\\?fuseaction=vids\\.individual&videoid.*|' +
        'http:\\/\\/www\\.myspace\\.com\\/index\\.cfm\\?fuseaction=.*&videoid.*|' +
        'http:\\/\\/www\\.metacafe\\.com\\/watch\\/.*|' +
        'http:\\/\\/www\\.metacafe\\.com\\/w\\/.*|' +
        'http:\\/\\/blip\\.tv\\/.*\\/.*|' +
        'http:\\/\\/.*\\.blip\\.tv\\/.*\\/.*|' +
        'http:\\/\\/video\\.google\\.com\\/videoplay\\?.*|' +
        'http:\\/\\/.*revver\\.com\\/video\\/.*|' +
        'http:\\/\\/video\\.yahoo\\.com\\/watch\\/.*\\/.*|' +
        'http:\\/\\/video\\.yahoo\\.com\\/network\\/.*|' +
        'http:\\/\\/.*viddler\\.com\\/explore\\/.*\\/videos\\/.*|' +
        'http:\\/\\/liveleak\\.com\\/view\\?.*|' +
        'http:\\/\\/www\\.liveleak\\.com\\/view\\?.*|' +
        'http:\\/\\/animoto\\.com\\/play\\/.*|' +
        'http:\\/\\/dotsub\\.com\\/view\\/.*|' +
        'http:\\/\\/www\\.overstream\\.net\\/view\\.php\\?oid=.*|' +
        'http:\\/\\/www\\.livestream\\.com\\/.*|' +
        'http:\\/\\/www\\.worldstarhiphop\\.com\\/videos\\/video.*\\.php\\?v=.*|' +
        'http:\\/\\/worldstarhiphop\\.com\\/videos\\/video.*\\.php\\?v=.*|' +
        'http:\\/\\/teachertube\\.com\\/viewVideo\\.php.*|' +
        'http:\\/\\/www\\.teachertube\\.com\\/viewVideo\\.php.*|' +
        'http:\\/\\/www1\\.teachertube\\.com\\/viewVideo\\.php.*|' +
        'http:\\/\\/www2\\.teachertube\\.com\\/viewVideo\\.php.*|' +
        'http:\\/\\/bambuser\\.com\\/v\\/.*|' +
        'http:\\/\\/bambuser\\.com\\/channel\\/.*|' +
        'http:\\/\\/bambuser\\.com\\/channel\\/.*\\/broadcast\\/.*|' +
        'http:\\/\\/www\\.schooltube\\.com\\/video\\/.*\\/.*|' +
        'http:\\/\\/bigthink\\.com\\/ideas\\/.*|' +
        'http:\\/\\/bigthink\\.com\\/series\\/.*|' +
        'http:\\/\\/sendables\\.jibjab\\.com\\/view\\/.*|' +
        'http:\\/\\/sendables\\.jibjab\\.com\\/originals\\/.*|' +
        'http:\\/\\/www\\.xtranormal\\.com\\/watch\\/.*|' +
        'http:\\/\\/socialcam\\.com\\/v\\/.*|' +
        'http:\\/\\/www\\.socialcam\\.com\\/v\\/.*|' +
        'http:\\/\\/dipdive\\.com\\/media\\/.*|' +
        'http:\\/\\/dipdive\\.com\\/member\\/.*\\/media\\/.*|' +
        'http:\\/\\/dipdive\\.com\\/v\\/.*|' +
        'http:\\/\\/.*\\.dipdive\\.com\\/media\\/.*|' +
        'http:\\/\\/.*\\.dipdive\\.com\\/v\\/.*|' +
        'http:\\/\\/v\\.youku\\.com\\/v_show\\/.*\\.html|' +
        'http:\\/\\/v\\.youku\\.com\\/v_playlist\\/.*\\.html|' +
        'http:\\/\\/www\\.snotr\\.com\\/video\\/.*|' +
        'http:\\/\\/snotr\\.com\\/video\\/.*|' +
        'http:\\/\\/video\\.jardenberg\\.se\\/.*|' +
        'http:\\/\\/www\\.clipfish\\.de\\/.*\\/.*\\/video\\/.*|' +
        'http:\\/\\/www\\.myvideo\\.de\\/watch\\/.*|' +
        'http:\\/\\/www\\.whitehouse\\.gov\\/photos-and-video\\/video\\/.*|' +
        'http:\\/\\/www\\.whitehouse\\.gov\\/video\\/.*|' +
        'http:\\/\\/wh\\.gov\\/photos-and-video\\/video\\/.*|' +
        'http:\\/\\/wh\\.gov\\/video\\/.*|' +
        'http:\\/\\/www\\.hulu\\.com\\/watch.*|' +
        'http:\\/\\/www\\.hulu\\.com\\/w\\/.*|' +
        'http:\\/\\/hulu\\.com\\/watch.*|' +
        'http:\\/\\/hulu\\.com\\/w\\/.*|' +
        'http:\\/\\/.*crackle\\.com\\/c\\/.*|' +
        'http:\\/\\/www\\.fancast\\.com\\/.*\\/videos|' +
        'http:\\/\\/www\\.funnyordie\\.com\\/videos\\/.*|' +
        'http:\\/\\/www\\.funnyordie\\.com\\/m\\/.*|' +
        'http:\\/\\/funnyordie\\.com\\/videos\\/.*|' +
        'http:\\/\\/funnyordie\\.com\\/m\\/.*|' +
        'http:\\/\\/www\\.vimeo\\.com\\/groups\\/.*\\/videos\\/.*|' +
        'http:\\/\\/www\\.vimeo\\.com\\/.*|' +
        'http:\\/\\/vimeo\\.com\\/groups\\/.*\\/videos\\/.*|' +
        'http:\\/\\/vimeo\\.com\\/.*|' +
        'http:\\/\\/vimeo\\.com\\/m\\/\\#\\/.*|' +
        'http:\\/\\/www\\.ted\\.com\\/talks\\/.*\\.html.*|' +
        'http:\\/\\/www\\.ted\\.com\\/talks\\/lang\\/.*\\/.*\\.html.*|' +
        'http:\\/\\/www\\.ted\\.com\\/index\\.php\\/talks\\/.*\\.html.*|' +
        'http:\\/\\/www\\.ted\\.com\\/index\\.php\\/talks\\/lang\\/.*\\/.*\\.html.*|' +
        'http:\\/\\/.*nfb\\.ca\\/film\\/.*|' +
        'http:\\/\\/www\\.thedailyshow\\.com\\/watch\\/.*|' +
        'http:\\/\\/www\\.thedailyshow\\.com\\/full-episodes\\/.*|' +
        'http:\\/\\/www\\.thedailyshow\\.com\\/collection\\/.*\\/.*\\/.*|' +
        'http:\\/\\/movies\\.yahoo\\.com\\/movie\\/.*\\/video\\/.*|' +
        'http:\\/\\/movies\\.yahoo\\.com\\/movie\\/.*\\/trailer|' +
        'http:\\/\\/movies\\.yahoo\\.com\\/movie\\/.*\\/video|' +
        'http:\\/\\/www\\.colbertnation\\.com\\/the-colbert-report-collections\\/.*|' +
        'http:\\/\\/www\\.colbertnation\\.com\\/full-episodes\\/.*|' +
        'http:\\/\\/www\\.colbertnation\\.com\\/the-colbert-report-videos\\/.*|' +
        'http:\\/\\/www\\.comedycentral\\.com\\/videos\\/index\\.jhtml\\?.*|' +
        'http:\\/\\/www\\.theonion\\.com\\/video\\/.*|' +
        'http:\\/\\/theonion\\.com\\/video\\/.*|' +
        'http:\\/\\/wordpress\\.tv\\/.*\\/.*\\/.*\\/.*\\/|' +
        'http:\\/\\/www\\.traileraddict\\.com\\/trailer\\/.*|' +
        'http:\\/\\/www\\.traileraddict\\.com\\/clip\\/.*|' +
        'http:\\/\\/www\\.traileraddict\\.com\\/poster\\/.*|' +
        'http:\\/\\/www\\.escapistmagazine\\.com\\/videos\\/.*|' +
        'http:\\/\\/www\\.trailerspy\\.com\\/trailer\\/.*\\/.*|' +
        'http:\\/\\/www\\.trailerspy\\.com\\/trailer\\/.*|' +
        'http:\\/\\/www\\.trailerspy\\.com\\/view_video\\.php.*|' +
        'http:\\/\\/www\\.atom\\.com\\/.*\\/.*\\/|' +
        'http:\\/\\/fora\\.tv\\/.*\\/.*\\/.*\\/.*|' +
        'http:\\/\\/www\\.spike\\.com\\/video\\/.*|' +
        'http:\\/\\/www\\.gametrailers\\.com\\/video\\/.*|' +
        'http:\\/\\/gametrailers\\.com\\/video\\/.*|' +
        'http:\\/\\/www\\.koldcast\\.tv\\/video\\/.*|' +
        'http:\\/\\/www\\.koldcast\\.tv\\/\\#video:.*|' +
        'http:\\/\\/techcrunch\\.tv\\/watch.*|' +
        'http:\\/\\/techcrunch\\.tv\\/.*\\/watch.*|' +
        'http:\\/\\/mixergy\\.com\\/.*|' +
        'http:\\/\\/video\\.pbs\\.org\\/video\\/.*|' +
        'http:\\/\\/www\\.zapiks\\.com\\/.*|' +
        'http:\\/\\/tv\\.digg\\.com\\/diggnation\\/.*|' +
        'http:\\/\\/tv\\.digg\\.com\\/diggreel\\/.*|' +
        'http:\\/\\/tv\\.digg\\.com\\/diggdialogg\\/.*|' +
        'http:\\/\\/www\\.trutv\\.com\\/video\\/.*|' +
        'http:\\/\\/www\\.nzonscreen\\.com\\/title\\/.*|' +
        'http:\\/\\/nzonscreen\\.com\\/title\\/.*|' +
        'http:\\/\\/app\\.wistia\\.com\\/embed\\/medias\\/.*|' +
        'https:\\/\\/app\\.wistia\\.com\\/embed\\/medias\\/.*|' +
        'http:\\/\\/hungrynation\\.tv\\/.*\\/episode\\/.*|' +
        'http:\\/\\/www\\.hungrynation\\.tv\\/.*\\/episode\\/.*|' +
        'http:\\/\\/hungrynation\\.tv\\/episode\\/.*|' +
        'http:\\/\\/www\\.hungrynation\\.tv\\/episode\\/.*|' +
        'http:\\/\\/indymogul\\.com\\/.*\\/episode\\/.*|' +
        'http:\\/\\/www\\.indymogul\\.com\\/.*\\/episode\\/.*|' +
        'http:\\/\\/indymogul\\.com\\/episode\\/.*|' +
        'http:\\/\\/www\\.indymogul\\.com\\/episode\\/.*|' +
        'http:\\/\\/channelfrederator\\.com\\/.*\\/episode\\/.*|' +
        'http:\\/\\/www\\.channelfrederator\\.com\\/.*\\/episode\\/.*|' +
        'http:\\/\\/channelfrederator\\.com\\/episode\\/.*|' +
        'http:\\/\\/www\\.channelfrederator\\.com\\/episode\\/.*|' +
        'http:\\/\\/tmiweekly\\.com\\/.*\\/episode\\/.*|' +
        'http:\\/\\/www\\.tmiweekly\\.com\\/.*\\/episode\\/.*|' +
        'http:\\/\\/tmiweekly\\.com\\/episode\\/.*|' +
        'http:\\/\\/www\\.tmiweekly\\.com\\/episode\\/.*|' +
        'http:\\/\\/99dollarmusicvideos\\.com\\/.*\\/episode\\/.*|' +
        'http:\\/\\/www\\.99dollarmusicvideos\\.com\\/.*\\/episode\\/.*|' +
        'http:\\/\\/99dollarmusicvideos\\.com\\/episode\\/.*|' +
        'http:\\/\\/www\\.99dollarmusicvideos\\.com\\/episode\\/.*|' +
        'http:\\/\\/ultrakawaii\\.com\\/.*\\/episode\\/.*|' +
        'http:\\/\\/www\\.ultrakawaii\\.com\\/.*\\/episode\\/.*|' +
        'http:\\/\\/ultrakawaii\\.com\\/episode\\/.*|' +
        'http:\\/\\/www\\.ultrakawaii\\.com\\/episode\\/.*|' +
        'http:\\/\\/barelypolitical\\.com\\/.*\\/episode\\/.*|' +
        'http:\\/\\/www\\.barelypolitical\\.com\\/.*\\/episode\\/.*|' +
        'http:\\/\\/barelypolitical\\.com\\/episode\\/.*|' +
        'http:\\/\\/www\\.barelypolitical\\.com\\/episode\\/.*|' +
        'http:\\/\\/barelydigital\\.com\\/.*\\/episode\\/.*|' +
        'http:\\/\\/www\\.barelydigital\\.com\\/.*\\/episode\\/.*|' +
        'http:\\/\\/barelydigital\\.com\\/episode\\/.*|' +
        'http:\\/\\/www\\.barelydigital\\.com\\/episode\\/.*|' +
        'http:\\/\\/threadbanger\\.com\\/.*\\/episode\\/.*|' +
        'http:\\/\\/www\\.threadbanger\\.com\\/.*\\/episode\\/.*|' +
        'http:\\/\\/threadbanger\\.com\\/episode\\/.*|' +
        'http:\\/\\/www\\.threadbanger\\.com\\/episode\\/.*|' +
        'http:\\/\\/vodcars\\.com\\/.*\\/episode\\/.*|' +
        'http:\\/\\/www\\.vodcars\\.com\\/.*\\/episode\\/.*|' +
        'http:\\/\\/vodcars\\.com\\/episode\\/.*|' +
        'http:\\/\\/www\\.vodcars\\.com\\/episode\\/.*|' +
        'http:\\/\\/confreaks\\.net\\/videos\\/.*|' +
        'http:\\/\\/www\\.confreaks\\.net\\/videos\\/.*|' +
        'http:\\/\\/video\\.allthingsd\\.com\\/video\\/.*|' +
        'http:\\/\\/videos\\.nymag\\.com\\/.*|' +
        'http:\\/\\/aniboom\\.com\\/animation-video\\/.*|' +
        'http:\\/\\/www\\.aniboom\\.com\\/animation-video\\/.*|' +
        'http:\\/\\/clipshack\\.com\\/Clip\\.aspx\\?.*|' +
        'http:\\/\\/www\\.clipshack\\.com\\/Clip\\.aspx\\?.*|' +
        'http:\\/\\/grindtv\\.com\\/.*\\/video\\/.*|' +
        'http:\\/\\/www\\.grindtv\\.com\\/.*\\/video\\/.*|' +
        'http:\\/\\/ifood\\.tv\\/recipe\\/.*|' +
        'http:\\/\\/ifood\\.tv\\/video\\/.*|' +
        'http:\\/\\/ifood\\.tv\\/channel\\/user\\/.*|' +
        'http:\\/\\/www\\.ifood\\.tv\\/recipe\\/.*|' +
        'http:\\/\\/www\\.ifood\\.tv\\/video\\/.*|' +
        'http:\\/\\/www\\.ifood\\.tv\\/channel\\/user\\/.*|' +
        'http:\\/\\/logotv\\.com\\/video\\/.*|' +
        'http:\\/\\/www\\.logotv\\.com\\/video\\/.*|' +
        'http:\\/\\/lonelyplanet\\.com\\/Clip\\.aspx\\?.*|' +
        'http:\\/\\/www\\.lonelyplanet\\.com\\/Clip\\.aspx\\?.*|' +
        'http:\\/\\/streetfire\\.net\\/video\\/.*\\.htm.*|' +
        'http:\\/\\/www\\.streetfire\\.net\\/video\\/.*\\.htm.*|' +
        'http:\\/\\/trooptube\\.tv\\/videos\\/.*|' +
        'http:\\/\\/www\\.trooptube\\.tv\\/videos\\/.*|' +
        'http:\\/\\/sciencestage\\.com\\/v\\/.*\\.html|' +
        'http:\\/\\/sciencestage\\.com\\/a\\/.*\\.html|' +
        'http:\\/\\/www\\.sciencestage\\.com\\/v\\/.*\\.html|' +
        'http:\\/\\/www\\.sciencestage\\.com\\/a\\/.*\\.html|' +
        'http:\\/\\/www\\.godtube\\.com\\/featured\\/video\\/.*|' +
        'http:\\/\\/godtube\\.com\\/featured\\/video\\/.*|' +
        'http:\\/\\/www\\.godtube\\.com\\/watch\\/.*|' +
        'http:\\/\\/godtube\\.com\\/watch\\/.*|' +
        'http:\\/\\/www\\.tangle\\.com\\/view_video.*|' +
        'http:\\/\\/mediamatters\\.org\\/mmtv\\/.*|' +
        'http:\\/\\/www\\.clikthrough\\.com\\/theater\\/video\\/.*|' +
        'http:\\/\\/gist\\.github\\.com\\/.*|' +
        'http:\\/\\/twitter\\.com\\/.*\\/status\\/.*|' +
        'http:\\/\\/twitter\\.com\\/.*\\/statuses\\/.*|' +
        'http:\\/\\/www\\.twitter\\.com\\/.*\\/status\\/.*|' +
        'http:\\/\\/www\\.twitter\\.com\\/.*\\/statuses\\/.*|' +
        'http:\\/\\/mobile\\.twitter\\.com\\/.*\\/status\\/.*|' +
        'http:\\/\\/mobile\\.twitter\\.com\\/.*\\/statuses\\/.*|' +
        'https:\\/\\/twitter\\.com\\/.*\\/status\\/.*|' +
        'https:\\/\\/twitter\\.com\\/.*\\/statuses\\/.*|' +
        'https:\\/\\/www\\.twitter\\.com\\/.*\\/status\\/.*|' +
        'https:\\/\\/www\\.twitter\\.com\\/.*\\/statuses\\/.*|' +
        'https:\\/\\/mobile\\.twitter\\.com\\/.*\\/status\\/.*|' +
        'https:\\/\\/mobile\\.twitter\\.com\\/.*\\/statuses\\/.*|' +
        'http:\\/\\/www\\.crunchbase\\.com\\/.*\\/.*|' +
        'http:\\/\\/crunchbase\\.com\\/.*\\/.*|' +
        'http:\\/\\/www\\.slideshare\\.net\\/.*\\/.*|' +
        'http:\\/\\/www\\.slideshare\\.net\\/mobile\\/.*\\/.*|' +
        'http:\\/\\/slidesha\\.re\\/.*|' +
        'http:\\/\\/scribd\\.com\\/doc\\/.*|' +
        'http:\\/\\/www\\.scribd\\.com\\/doc\\/.*|' +
        'http:\\/\\/scribd\\.com\\/mobile\\/documents\\/.*|' +
        'http:\\/\\/www\\.scribd\\.com\\/mobile\\/documents\\/.*|' +
        'http:\\/\\/screenr\\.com\\/.*|' +
        'http:\\/\\/polldaddy\\.com\\/community\\/poll\\/.*|' +
        'http:\\/\\/polldaddy\\.com\\/poll\\/.*|' +
        'http:\\/\\/answers\\.polldaddy\\.com\\/poll\\/.*|' +
        'http:\\/\\/www\\.5min\\.com\\/Video\\/.*|' +
        'http:\\/\\/www\\.howcast\\.com\\/videos\\/.*|' +
        'http:\\/\\/www\\.screencast\\.com\\/.*\\/media\\/.*|' +
        'http:\\/\\/screencast\\.com\\/.*\\/media\\/.*|' +
        'http:\\/\\/www\\.screencast\\.com\\/t\\/.*|' +
        'http:\\/\\/screencast\\.com\\/t\\/.*|' +
        'http:\\/\\/issuu\\.com\\/.*\\/docs\\/.*|' +
        'http:\\/\\/www\\.kickstarter\\.com\\/projects\\/.*\\/.*|' +
        'http:\\/\\/www\\.scrapblog\\.com\\/viewer\\/viewer\\.aspx.*|' +
        'http:\\/\\/ping\\.fm\\/p\\/.*|' +
        'http:\\/\\/chart\\.ly\\/symbols\\/.*|' +
        'http:\\/\\/chart\\.ly\\/.*|' +
        'http:\\/\\/maps\\.google\\.com\\/maps\\?.*|' +
        'http:\\/\\/maps\\.google\\.com\\/\\?.*|' +
        'http:\\/\\/maps\\.google\\.com\\/maps\\/ms\\?.*|' +
        'http:\\/\\/.*\\.craigslist\\.org\\/.*\\/.*|' +
        'http:\\/\\/my\\.opera\\.com\\/.*\\/albums\\/show\\.dml\\?id=.*|' +
        'http:\\/\\/my\\.opera\\.com\\/.*\\/albums\\/showpic\\.dml\\?album=.*&picture=.*|' +
        'http:\\/\\/tumblr\\.com\\/.*|' +
        'http:\\/\\/.*\\.tumblr\\.com\\/post\\/.*|' +
        'http:\\/\\/www\\.polleverywhere\\.com\\/polls\\/.*|' +
        'http:\\/\\/www\\.polleverywhere\\.com\\/multiple_choice_polls\\/.*|' +
        'http:\\/\\/www\\.polleverywhere\\.com\\/free_text_polls\\/.*|' +
        'http:\\/\\/www\\.quantcast\\.com\\/wd:.*|' +
        'http:\\/\\/www\\.quantcast\\.com\\/.*|' +
        'http:\\/\\/siteanalytics\\.compete\\.com\\/.*|' +
        'http:\\/\\/statsheet\\.com\\/statplot\\/charts\\/.*\\/.*\\/.*\\/.*|' +
        'http:\\/\\/statsheet\\.com\\/statplot\\/charts\\/e\\/.*|' +
        'http:\\/\\/statsheet\\.com\\/.*\\/teams\\/.*\\/.*|' +
        'http:\\/\\/statsheet\\.com\\/tools\\/chartlets\\?chart=.*|' +
        'http:\\/\\/.*\\.status\\.net\\/notice\\/.*|' +
        'http:\\/\\/identi\\.ca\\/notice\\/.*|' +
        'http:\\/\\/brainbird\\.net\\/notice\\/.*|' +
        'http:\\/\\/shitmydadsays\\.com\\/notice\\/.*|' +
        'http:\\/\\/www\\.studivz\\.net\\/Profile\\/.*|' +
        'http:\\/\\/www\\.studivz\\.net\\/l\\/.*|' +
        'http:\\/\\/www\\.studivz\\.net\\/Groups\\/Overview\\/.*|' +
        'http:\\/\\/www\\.studivz\\.net\\/Gadgets\\/Info\\/.*|' +
        'http:\\/\\/www\\.studivz\\.net\\/Gadgets\\/Install\\/.*|' +
        'http:\\/\\/www\\.studivz\\.net\\/.*|' +
        'http:\\/\\/www\\.meinvz\\.net\\/Profile\\/.*|' +
        'http:\\/\\/www\\.meinvz\\.net\\/l\\/.*|' +
        'http:\\/\\/www\\.meinvz\\.net\\/Groups\\/Overview\\/.*|' +
        'http:\\/\\/www\\.meinvz\\.net\\/Gadgets\\/Info\\/.*|' +
        'http:\\/\\/www\\.meinvz\\.net\\/Gadgets\\/Install\\/.*|' +
        'http:\\/\\/www\\.meinvz\\.net\\/.*|' +
        'http:\\/\\/www\\.schuelervz\\.net\\/Profile\\/.*|' +
        'http:\\/\\/www\\.schuelervz\\.net\\/l\\/.*|' +
        'http:\\/\\/www\\.schuelervz\\.net\\/Groups\\/Overview\\/.*|' +
        'http:\\/\\/www\\.schuelervz\\.net\\/Gadgets\\/Info\\/.*|' +
        'http:\\/\\/www\\.schuelervz\\.net\\/Gadgets\\/Install\\/.*|' +
        'http:\\/\\/www\\.schuelervz\\.net\\/.*|' +
        'http:\\/\\/myloc\\.me\\/.*|' +
        'http:\\/\\/pastebin\\.com\\/.*|' +
        'http:\\/\\/pastie\\.org\\/.*|' +
        'http:\\/\\/www\\.pastie\\.org\\/.*|' +
        'http:\\/\\/redux\\.com\\/stream\\/item\\/.*\\/.*|' +
        'http:\\/\\/redux\\.com\\/f\\/.*\\/.*|' +
        'http:\\/\\/www\\.redux\\.com\\/stream\\/item\\/.*\\/.*|' +
        'http:\\/\\/www\\.redux\\.com\\/f\\/.*\\/.*|' +
        'http:\\/\\/cl\\.ly\\/.*|' +
        'http:\\/\\/cl\\.ly\\/.*\\/content|' +
        'http:\\/\\/speakerdeck\\.com\\/u\\/.*\\/p\\/.*|' +
        'http:\\/\\/www\\.kiva\\.org\\/lend\\/.*|' +
        'http:\\/\\/www\\.timetoast\\.com\\/timelines\\/.*|' +
        'http:\\/\\/storify\\.com\\/.*\\/.*|' +
        'http:\\/\\/.*meetup\\.com\\/.*|' +
        'http:\\/\\/meetu\\.ps\\/.*|' +
        'http:\\/\\/www\\.dailymile\\.com\\/people\\/.*\\/entries\\/.*|' +
        'http:\\/\\/.*\\.kinomap\\.com\\/.*|' +
        'http:\\/\\/www\\.metacdn\\.com\\/api\\/users\\/.*\\/content\\/.*|' +
        'http:\\/\\/www\\.metacdn\\.com\\/api\\/users\\/.*\\/media\\/.*|' +
        'http:\\/\\/prezi\\.com\\/.*\\/.*|' +
        'http:\\/\\/.*\\.uservoice\\.com\\/.*\\/suggestions\\/.*|' +
        'http:\\/\\/formspring\\.me\\/.*|' +
        'http:\\/\\/www\\.formspring\\.me\\/.*|' +
        'http:\\/\\/formspring\\.me\\/.*\\/q\\/.*|' +
        'http:\\/\\/www\\.formspring\\.me\\/.*\\/q\\/.*|' +
        'http:\\/\\/twitlonger\\.com\\/show\\/.*|' +
        'http:\\/\\/www\\.twitlonger\\.com\\/show\\/.*|' +
        'http:\\/\\/tl\\.gd\\/.*|' +
        'http:\\/\\/www\\.qwiki\\.com\\/q\\/.*|' +
        'http:\\/\\/crocodoc\\.com\\/.*|' +
        'http:\\/\\/.*\\.crocodoc\\.com\\/.*|' +
        'https:\\/\\/crocodoc\\.com\\/.*|' +
        'https:\\/\\/.*\\.crocodoc\\.com\\/.*|' +
        'http:\\/\\/www\\.wikipedia\\.org\\/wiki\\/.*|' +
        'http:\\/\\/www\\.wikimedia\\.org\\/wiki\\/File.*|' +
        'https:\\/\\/urtak\\.com\\/u\\/.*|' +
        'https:\\/\\/urtak\\.com\\/clr\\/.*|' +
        'http:\\/\\/graphicly\\.com\\/.*\\/.*\\/.*|' +
        'http:\\/\\/.*yfrog\\..*\\/.*|' +
        'http:\\/\\/www\\.flickr\\.com\\/photos\\/.*|' +
        'http:\\/\\/flic\\.kr\\/.*|' +
        'http:\\/\\/twitpic\\.com\\/.*|' +
        'http:\\/\\/www\\.twitpic\\.com\\/.*|' +
        'http:\\/\\/twitpic\\.com\\/photos\\/.*|' +
        'http:\\/\\/www\\.twitpic\\.com\\/photos\\/.*|' +
        'http:\\/\\/.*imgur\\.com\\/.*|' +
        'http:\\/\\/.*\\.posterous\\.com\\/.*|' +
        'http:\\/\\/post\\.ly\\/.*|' +
        'http:\\/\\/twitgoo\\.com\\/.*|' +
        'http:\\/\\/i.*\\.photobucket\\.com\\/albums\\/.*|' +
        'http:\\/\\/s.*\\.photobucket\\.com\\/albums\\/.*|' +
        'http:\\/\\/phodroid\\.com\\/.*\\/.*\\/.*|' +
        'http:\\/\\/www\\.mobypicture\\.com\\/user\\/.*\\/view\\/.*|' +
        'http:\\/\\/moby\\.to\\/.*|' +
        'http:\\/\\/xkcd\\.com\\/.*|' +
        'http:\\/\\/www\\.xkcd\\.com\\/.*|' +
        'http:\\/\\/imgs\\.xkcd\\.com\\/.*|' +
        'http:\\/\\/www\\.asofterworld\\.com\\/index\\.php\\?id=.*|' +
        'http:\\/\\/www\\.asofterworld\\.com\\/.*\\.jpg|' +
        'http:\\/\\/asofterworld\\.com\\/.*\\.jpg|' +
        'http:\\/\\/www\\.qwantz\\.com\\/index\\.php\\?comic=.*|' +
        'http:\\/\\/23hq\\.com\\/.*\\/photo\\/.*|' +
        'http:\\/\\/www\\.23hq\\.com\\/.*\\/photo\\/.*|' +
        'http:\\/\\/.*dribbble\\.com\\/shots\\/.*|' +
        'http:\\/\\/drbl\\.in\\/.*|' +
        'http:\\/\\/.*\\.smugmug\\.com\\/.*|' +
        'http:\\/\\/.*\\.smugmug\\.com\\/.*\\#.*|' +
        'http:\\/\\/emberapp\\.com\\/.*\\/images\\/.*|' +
        'http:\\/\\/emberapp\\.com\\/.*\\/images\\/.*\\/sizes\\/.*|' +
        'http:\\/\\/emberapp\\.com\\/.*\\/collections\\/.*\\/.*|' +
        'http:\\/\\/emberapp\\.com\\/.*\\/categories\\/.*\\/.*\\/.*|' +
        'http:\\/\\/embr\\.it\\/.*|' +
        'http:\\/\\/picasaweb\\.google\\.com.*\\/.*\\/.*\\#.*|' +
        'http:\\/\\/picasaweb\\.google\\.com.*\\/lh\\/photo\\/.*|' +
        'http:\\/\\/picasaweb\\.google\\.com.*\\/.*\\/.*|' +
        'http:\\/\\/dailybooth\\.com\\/.*\\/.*|' +
        'http:\\/\\/brizzly\\.com\\/pic\\/.*|' +
        'http:\\/\\/pics\\.brizzly\\.com\\/.*\\.jpg|' +
        'http:\\/\\/img\\.ly\\/.*|' +
        'http:\\/\\/www\\.tinypic\\.com\\/view\\.php.*|' +
        'http:\\/\\/tinypic\\.com\\/view\\.php.*|' +
        'http:\\/\\/www\\.tinypic\\.com\\/player\\.php.*|' +
        'http:\\/\\/tinypic\\.com\\/player\\.php.*|' +
        'http:\\/\\/www\\.tinypic\\.com\\/r\\/.*\\/.*|' +
        'http:\\/\\/tinypic\\.com\\/r\\/.*\\/.*|' +
        'http:\\/\\/.*\\.tinypic\\.com\\/.*\\.jpg|' +
        'http:\\/\\/.*\\.tinypic\\.com\\/.*\\.png|' +
        'http:\\/\\/meadd\\.com\\/.*\\/.*|' +
        'http:\\/\\/meadd\\.com\\/.*|' +
        'http:\\/\\/.*\\.deviantart\\.com\\/art\\/.*|' +
        'http:\\/\\/.*\\.deviantart\\.com\\/gallery\\/.*|' +
        'http:\\/\\/.*\\.deviantart\\.com\\/\\#\\/.*|' +
        'http:\\/\\/fav\\.me\\/.*|' +
        'http:\\/\\/.*\\.deviantart\\.com|' +
        'http:\\/\\/.*\\.deviantart\\.com\\/gallery|' +
        'http:\\/\\/.*\\.deviantart\\.com\\/.*\\/.*\\.jpg|' +
        'http:\\/\\/.*\\.deviantart\\.com\\/.*\\/.*\\.gif|' +
        'http:\\/\\/.*\\.deviantart\\.net\\/.*\\/.*\\.jpg|' +
        'http:\\/\\/.*\\.deviantart\\.net\\/.*\\/.*\\.gif|' +
        'http:\\/\\/www\\.fotopedia\\.com\\/.*\\/.*|' +
        'http:\\/\\/fotopedia\\.com\\/.*\\/.*|' +
        'http:\\/\\/photozou\\.jp\\/photo\\/show\\/.*\\/.*|' +
        'http:\\/\\/photozou\\.jp\\/photo\\/photo_only\\/.*\\/.*|' +
        'http:\\/\\/instagr\\.am\\/p\\/.*|' +
        'http:\\/\\/instagram\\.com\\/p\\/.*|' +
        'http:\\/\\/skitch\\.com\\/.*\\/.*\\/.*|' +
        'http:\\/\\/img\\.skitch\\.com\\/.*|' +
        'https:\\/\\/skitch\\.com\\/.*\\/.*\\/.*|' +
        'https:\\/\\/img\\.skitch\\.com\\/.*|' +
        'http:\\/\\/share\\.ovi\\.com\\/media\\/.*\\/.*|' +
        'http:\\/\\/www\\.questionablecontent\\.net\\/|' +
        'http:\\/\\/questionablecontent\\.net\\/|' +
        'http:\\/\\/www\\.questionablecontent\\.net\\/view\\.php.*|' +
        'http:\\/\\/questionablecontent\\.net\\/view\\.php.*|' +
        'http:\\/\\/questionablecontent\\.net\\/comics\\/.*\\.png|' +
        'http:\\/\\/www\\.questionablecontent\\.net\\/comics\\/.*\\.png|' +
        'http:\\/\\/picplz\\.com\\/.*|' +
        'http:\\/\\/twitrpix\\.com\\/.*|' +
        'http:\\/\\/.*\\.twitrpix\\.com\\/.*|' +
        'http:\\/\\/www\\.someecards\\.com\\/.*\\/.*|' +
        'http:\\/\\/someecards\\.com\\/.*\\/.*|' +
        'http:\\/\\/some\\.ly\\/.*|' +
        'http:\\/\\/www\\.some\\.ly\\/.*|' +
        'http:\\/\\/pikchur\\.com\\/.*|' +
        'http:\\/\\/achewood\\.com\\/.*|' +
        'http:\\/\\/www\\.achewood\\.com\\/.*|' +
        'http:\\/\\/achewood\\.com\\/index\\.php.*|' +
        'http:\\/\\/www\\.achewood\\.com\\/index\\.php.*|' +
        'http:\\/\\/www\\.whosay\\.com\\/content\\/.*|' +
        'http:\\/\\/www\\.whosay\\.com\\/photos\\/.*|' +
        'http:\\/\\/www\\.whosay\\.com\\/videos\\/.*|' +
        'http:\\/\\/say\\.ly\\/.*|' +
        'http:\\/\\/ow\\.ly\\/i\\/.*|' +
        'http:\\/\\/color\\.com\\/s\\/.*|' +
        'http:\\/\\/bnter\\.com\\/convo\\/.*|' +
        'http:\\/\\/mlkshk\\.com\\/p\\/.*|' +
        'http:\\/\\/lockerz\\.com\\/s\\/.*|' +
        'http:\\/\\/lightbox\\.com\\/.*|' +
        'http:\\/\\/www\\.lightbox\\.com\\/.*|' +
        'http:\\/\\/.*amazon\\..*\\/gp\\/product\\/.*|' +
        'http:\\/\\/.*amazon\\..*\\/.*\\/dp\\/.*|' +
        'http:\\/\\/.*amazon\\..*\\/dp\\/.*|' +
        'http:\\/\\/.*amazon\\..*\\/o\\/ASIN\\/.*|' +
        'http:\\/\\/.*amazon\\..*\\/gp\\/offer-listing\\/.*|' +
        'http:\\/\\/.*amazon\\..*\\/.*\\/ASIN\\/.*|' +
        'http:\\/\\/.*amazon\\..*\\/gp\\/product\\/images\\/.*|' +
        'http:\\/\\/.*amazon\\..*\\/gp\\/aw\\/d\\/.*|' +
        'http:\\/\\/www\\.amzn\\.com\\/.*|' +
        'http:\\/\\/amzn\\.com\\/.*|' +
        'http:\\/\\/www\\.shopstyle\\.com\\/browse.*|' +
        'http:\\/\\/www\\.shopstyle\\.com\\/action\\/apiVisitRetailer.*|' +
        'http:\\/\\/api\\.shopstyle\\.com\\/action\\/apiVisitRetailer.*|' +
        'http:\\/\\/www\\.shopstyle\\.com\\/action\\/viewLook.*|' +
        'http:\\/\\/itunes\\.apple\\.com\\/.*|' +
        'https:\\/\\/itunes\\.apple\\.com\\/.*|' +
        'http:\\/\\/soundcloud\\.com\\/.*|' +
        'http:\\/\\/soundcloud\\.com\\/.*\\/.*|' +
        'http:\\/\\/soundcloud\\.com\\/.*\\/sets\\/.*|' +
        'http:\\/\\/soundcloud\\.com\\/groups\\/.*|' +
        'http:\\/\\/snd\\.sc\\/.*|' +
        'http:\\/\\/www\\.last\\.fm\\/music\\/.*|' +
        'http:\\/\\/www\\.last\\.fm\\/music\\/+videos\\/.*|' +
        'http:\\/\\/www\\.last\\.fm\\/music\\/+images\\/.*|' +
        'http:\\/\\/www\\.last\\.fm\\/music\\/.*\\/_\\/.*|' +
        'http:\\/\\/www\\.last\\.fm\\/music\\/.*\\/.*|' +
        'http:\\/\\/www\\.mixcloud\\.com\\/.*\\/.*\\/|' +
        'http:\\/\\/www\\.radionomy\\.com\\/.*\\/radio\\/.*|' +
        'http:\\/\\/radionomy\\.com\\/.*\\/radio\\/.*|' +
        'http:\\/\\/www\\.hark\\.com\\/clips\\/.*|' +
        'http:\\/\\/www\\.rdio\\.com\\/\\#\\/artist\\/.*\\/album\\/.*|' +
        'http:\\/\\/www\\.rdio\\.com\\/artist\\/.*\\/album\\/.*|' +
        'http:\\/\\/www\\.zero-inch\\.com\\/.*|' +
        'http:\\/\\/.*\\.bandcamp\\.com\\/|' +
        'http:\\/\\/.*\\.bandcamp\\.com\\/track\\/.*|' +
        'http:\\/\\/.*\\.bandcamp\\.com\\/album\\/.*|' +
        'http:\\/\\/freemusicarchive\\.org\\/music\\/.*|' +
        'http:\\/\\/www\\.freemusicarchive\\.org\\/music\\/.*|' +
        'http:\\/\\/freemusicarchive\\.org\\/curator\\/.*|' +
        'http:\\/\\/www\\.freemusicarchive\\.org\\/curator\\/.*|' +
        'http:\\/\\/www\\.npr\\.org\\/.*\\/.*\\/.*\\/.*\\/.*|' +
        'http:\\/\\/www\\.npr\\.org\\/.*\\/.*\\/.*\\/.*\\/.*\\/.*|' +
        'http:\\/\\/www\\.npr\\.org\\/.*\\/.*\\/.*\\/.*\\/.*\\/.*\\/.*|' +
        'http:\\/\\/www\\.npr\\.org\\/templates\\/story\\/story\\.php.*|' +
        'http:\\/\\/huffduffer\\.com\\/.*\\/.*|' +
        'http:\\/\\/www\\.audioboo\\.fm\\/boos\\/.*|' +
        'http:\\/\\/audioboo\\.fm\\/boos\\/.*|' +
        'http:\\/\\/boo\\.fm\\/b.*|' +
        'http:\\/\\/www\\.xiami\\.com\\/song\\/.*|' +
        'http:\\/\\/xiami\\.com\\/song\\/.*|' +
        'http:\\/\\/www\\.saynow\\.com\\/playMsg\\.html.*|' +
        'http:\\/\\/www\\.saynow\\.com\\/playMsg\\.html.*|' +
        'http:\\/\\/grooveshark\\.com\\/.*|' +
        'http:\\/\\/radioreddit\\.com\\/songs.*|' +
        'http:\\/\\/www\\.radioreddit\\.com\\/songs.*|' +
        'http:\\/\\/radioreddit\\.com\\/\\?q=songs.*|' +
        'http:\\/\\/www\\.radioreddit\\.com\\/\\?q=songs.*|' +
        'http:\\/\\/www\\.gogoyoko\\.com\\/song\\/.*|' +
        'http:\\/\\/espn\\.go\\.com\\/video\\/clip.*|' +
        'http:\\/\\/espn\\.go\\.com\\/.*\\/story.*|' +
        'http:\\/\\/abcnews\\.com\\/.*\\/video\\/.*|' +
        'http:\\/\\/abcnews\\.com\\/video\\/playerIndex.*|' +
        'http:\\/\\/washingtonpost\\.com\\/wp-dyn\\/.*\\/video\\/.*\\/.*\\/.*\\/.*|' +
        'http:\\/\\/www\\.washingtonpost\\.com\\/wp-dyn\\/.*\\/video\\/.*\\/.*\\/.*\\/.*|' +
        'http:\\/\\/www\\.boston\\.com\\/video.*|' +
        'http:\\/\\/boston\\.com\\/video.*|' +
        'http:\\/\\/www\\.facebook\\.com\\/photo\\.php.*|' +
        'http:\\/\\/www\\.facebook\\.com\\/video\\/video\\.php.*|' +
        'http:\\/\\/www\\.facebook\\.com\\/v\\/.*|' +
        'https:\\/\\/www\\.facebook\\.com\\/photo\\.php.*|' +
        'https:\\/\\/www\\.facebook\\.com\\/video\\/video\\.php.*|' +
        'https:\\/\\/www\\.facebook\\.com\\/v\\/.*|' +
        'http:\\/\\/cnbc\\.com\\/id\\/.*\\?.*video.*|' +
        'http:\\/\\/www\\.cnbc\\.com\\/id\\/.*\\?.*video.*|' +
        'http:\\/\\/cnbc\\.com\\/id\\/.*\\/play\\/1\\/video\\/.*|' +
        'http:\\/\\/www\\.cnbc\\.com\\/id\\/.*\\/play\\/1\\/video\\/.*|' +
        'http:\\/\\/cbsnews\\.com\\/video\\/watch\\/.*|' +
        'http:\\/\\/www\\.google\\.com\\/buzz\\/.*\\/.*\\/.*|' +
        'http:\\/\\/www\\.google\\.com\\/buzz\\/.*|' +
        'http:\\/\\/www\\.google\\.com\\/profiles\\/.*|' +
        'http:\\/\\/google\\.com\\/buzz\\/.*\\/.*\\/.*|' +
        'http:\\/\\/google\\.com\\/buzz\\/.*|' +
        'http:\\/\\/google\\.com\\/profiles\\/.*|' +
        'http:\\/\\/www\\.cnn\\.com\\/video\\/.*|' +
        'http:\\/\\/edition\\.cnn\\.com\\/video\\/.*|' +
        'http:\\/\\/money\\.cnn\\.com\\/video\\/.*|' +
        'http:\\/\\/today\\.msnbc\\.msn\\.com\\/id\\/.*\\/vp\\/.*|' +
        'http:\\/\\/www\\.msnbc\\.msn\\.com\\/id\\/.*\\/vp\\/.*|' +
        'http:\\/\\/www\\.msnbc\\.msn\\.com\\/id\\/.*\\/ns\\/.*|' +
        'http:\\/\\/today\\.msnbc\\.msn\\.com\\/id\\/.*\\/ns\\/.*|' +
        'http:\\/\\/www\\.globalpost\\.com\\/video\\/.*|' +
        'http:\\/\\/www\\.globalpost\\.com\\/dispatch\\/.*|' +
        'http:\\/\\/guardian\\.co\\.uk\\/.*\\/video\\/.*\\/.*\\/.*\\/.*|' +
        'http:\\/\\/www\\.guardian\\.co\\.uk\\/.*\\/video\\/.*\\/.*\\/.*\\/.*|' +
        'http:\\/\\/bravotv\\.com\\/.*\\/.*\\/videos\\/.*|' +
        'http:\\/\\/www\\.bravotv\\.com\\/.*\\/.*\\/videos\\/.*|' +
        'http:\\/\\/video\\.nationalgeographic\\.com\\/.*\\/.*\\/.*\\.html|' +
        'http:\\/\\/dsc\\.discovery\\.com\\/videos\\/.*|' +
        'http:\\/\\/animal\\.discovery\\.com\\/videos\\/.*|' +
        'http:\\/\\/health\\.discovery\\.com\\/videos\\/.*|' +
        'http:\\/\\/investigation\\.discovery\\.com\\/videos\\/.*|' +
        'http:\\/\\/military\\.discovery\\.com\\/videos\\/.*|' +
        'http:\\/\\/planetgreen\\.discovery\\.com\\/videos\\/.*|' +
        'http:\\/\\/science\\.discovery\\.com\\/videos\\/.*|' +
        'http:\\/\\/tlc\\.discovery\\.com\\/videos\\/.*|' +
        'http:\\/\\/video\\.forbes\\.com\\/fvn\\/.*|' + 
        'http:\\/\\/recordsetter\\.com\\/*\\/*\\/*'
        , re.I
    )
    
    api_endpoint = 'http://api.embed.ly/1/oembed'
    api_params = {'format':'json', 'maxwidth':600, 'key' : g.embedly_api_key }
 
class GenericScraper(MediaScraper):
    """a special scrapper not associated with any domains, used to
       write media objects to links by hand"""
    domains = ['*']
    height = 480
    width = 640

    @classmethod
    def media_embed(cls, content, height = None, width = None, scrolling = False, **kw):
        return MediaEmbed(height = height or cls.height,
                          width = width or cls.width,
                          scrolling = scrolling,
                          content = content)

class DeepScraper(object):
    """Subclasses of DeepScraper attempt to dive into generic pages
       for embeds of other types (like YouTube videos on blog
       sites)."""

    def find_media_object(self, scraper):
        return None

class YoutubeEmbedDeepScraper(DeepScraper):
    youtube_url_re = re.compile('^(http://www.youtube.com/v/([_a-zA-Z0-9-]+)).*')

    def find_media_object(self, scraper):
        # try to find very simple youtube embeds
        if not scraper.soup:
            scraper.download()

        if scraper.soup:
            movie_embed = scraper.soup.find('embed',
                                            attrs={'src': lambda x: self.youtube_url_re.match(x)})
            if movie_embed:
                youtube_id = self.youtube_url_re.match(movie_embed['src']).group(2)
                youtube_url = 'http://www.youtube.com/watch?v=%s"' % youtube_id
                log.debug('found youtube embed %s' % youtube_url)
                mo = make_scraper(youtube_url).media_object()
                mo['deep'] = scraper.url
                return mo

#scrapers =:= dict(domain -> ScraperClass)
scrapers = {}
for scraper in [ EmbedlyOEmbed,
                 YoutubeScraper,
                 MetacafeScraper,
                 GootubeScraper,
                 VimeoScraper,
                 BreakScraper,
                 TheOnionScraper,
                 CollegeHumorScraper,
                 FunnyOrDieScraper,
                 ComedyCentralScraper,
                 ColbertNationScraper,
                 TheDailyShowScraper,
                 TedScraper,
                 LiveLeakScraper,
                 DailyMotionScraper,
                 RevverScraper,
                 EscapistScraper,
                 JustintvScraper,
                 SoundcloudScraper,
                 CraigslistScraper,
                 GenericScraper,
                 ]:
    for domain in scraper.domains:
        scrapers.setdefault(domain, []).append(scraper)

deepscrapers = [YoutubeEmbedDeepScraper]

def get_media_embed(media_object):
    for scraper in scrapers.get(media_object['type'], []):
        res = scraper.media_embed(**media_object)
        if res:
            return res
    if 'content' in media_object:
        return GenericScraper.media_embed(**media_object)

def convert_old_media_objects():
    q = Link._query(Link.c.media_object is not None,
                    Link.c._date > whenever,
                    data = True)
    for link in utils.fetch_things2(q):
        if not getattr(link, 'media_object', None):
            continue

        if 'youtube' in link.media_object:
            # we can rewrite this one without scraping
            video_id = YoutubeScraper.video_id_rx.match(link.url)
            link.media_object = dict(type='youtube.com',
                                     video_id = video_id.group(1))
        elif ('video.google.com' in link.media_object
              or 'metacafe' in link.media_object):
            scraper = make_scraper(link.url)
            if not scraper:
                continue
            mo = scraper.media_object()
            if not mo:
                continue

            link.media_object = mo

        else:
            print "skipping %s because it confuses me" % link._fullname
            continue

        link._commit()

test_urls = [
    'http://www.facebook.com/pages/Rick-Astley/5807213510?sid=c99aaf3888171e73668a38e0749ae12d', # regular thumbnail finder
    'http://www.flickr.com/photos/septuagesima/317819584/', # thumbnail with image_src

    #'http://www.youtube.com/watch?v=Yu_moia-oVI',
    'http://www.metacafe.com/watch/sy-1473689248/rick_astley_never_gonna_give_you_up_official_music_video/',
    'http://video.google.com/videoplay?docid=5908758151704698048',
    #'http://vimeo.com/4495451',
    'http://www.break.com/usercontent/2008/11/Macy-s-Thankgiving-Day-Parade-Rick-Roll-611965.html',
    'http://www.theonion.com/content/video/sony_releases_new_stupid_piece_of',
    'http://www.collegehumor.com/video:1823712',
    'http://www.funnyordie.com/videos/7f2a184755/macys-thanksgiving-day-parade-gets-rick-rolled-from-that-happened',
    'http://www.comedycentral.com/videos/index.jhtml?videoId=178342&title=ultimate-fighting-vs.-bloggers',

    # old style
    'http://www.thedailyshow.com/video/index.jhtml?videoId=175244&title=Photoshop-of-Horrors',
    # new style
    'http://www.thedailyshow.com/watch/wed-july-22-2009/the-born-identity',

    'http://www.colbertnation.com/the-colbert-report-videos/63549/may-01-2006/sign-off---spam',
    'http://www.liveleak.com/view?i=e09_1207983531',
    'http://www.dailymotion.com/relevance/search/rick+roll/video/x5l8e6_rickroll_fun',
    'http://revver.com/video/1199591/rick-rolld-at-work/',
    'http://www.escapistmagazine.com/videos/view/zero-punctuation/10-The-Orange-Box',
    'http://www.escapistmagazine.com/videos/view/unskippable/736-Lost-Odyssey',

    # justin.tv has two media types that we care about, streams, which
    # we can scrape, and clips, which we can't
    'http://www.justin.tv/help', # stream
    'http://www.justin.tv/clip/c07a333f94e5716b', # clip, which we can't currently scrape, and shouldn't try

    'http://soundcloud.com/kalhonaaho01/never-gonna-stand-you-up-rick-astley-vs-ludacris-album-version',

    'http://www.craigslist.org/about/best/sea/240705630.html',

    'http://listen.grooveshark.com/#/song/Never_Gonna_Give_You_Up/12616328',
    'http://tinysong.com/2WOJ', # also Grooveshark
    'http://www.slideshare.net/doina/happy-easter-from-holland-slideshare',
    'http://www.slideshare.net/stinson/easter-1284190',
    'http://www.slideshare.net/angelspascual/easter-events',
    'http://www.slideshare.net/sirrods/happy-easter-3626014',
    'http://www.slideshare.net/sirrods/happy-easter-wide-screen',
    'http://www.slideshare.net/carmen_serbanescu/easter-holiday',
    'http://www.slideshare.net/Lithuaniabook/easter-1255880',
    'http://www.slideshare.net/hues/easter-plants',
    'http://www.slideshare.net/Gospelman/passover-week',
    'http://www.slideshare.net/angelspascual/easter-around-the-world-1327542',
    'http://www.scribd.com/doc/13994900/Easter',
    'http://www.scribd.com/doc/27425714/Celebrating-Easter-ideas-for-adults-and-children',
    'http://www.scribd.com/doc/28010101/Easter-Foods-No-Name',
    'http://www.scribd.com/doc/28452730/Easter-Cards',
    'http://www.scribd.com/doc/19026714/The-Easter-Season',
    'http://www.scribd.com/doc/29183659/History-of-Easter',
    'http://www.scribd.com/doc/15632842/The-Last-Easter',
    'http://www.scribd.com/doc/28741860/The-Plain-Truth-About-Easter',
    'http://www.scribd.com/doc/23616250/4-27-08-ITS-EASTER-AGAIN-ORTHODOX-EASTER-by-vanderKOK',
    'http://screenr.com/t9d',
    'http://screenr.com/yLS',
    'http://screenr.com/gzS',
    'http://screenr.com/IwU',
    'http://screenr.com/FM7',
    'http://screenr.com/Ejg',
    'http://screenr.com/u4h',
    'http://screenr.com/QiN',
    'http://screenr.com/zts',
    'http://www.5min.com/Video/How-to-Decorate-Easter-Eggs-with-Decoupage-142076462',
    'http://www.5min.com/Video/How-to-Color-Easter-Eggs-Dye-142076281',
    'http://www.5min.com/Video/How-to-Make-an-Easter-Egg-Diorama-142076482',
    'http://www.5min.com/Video/How-to-Make-Sequined-Easter-Eggs-142076512',
    'http://www.5min.com/Video/How-to-Decorate-Wooden-Easter-Eggs-142076558',
    'http://www.5min.com/Video/How-to-Blow-out-an-Easter-Egg-142076367',
    'http://www.5min.com/Video/Learn-About-Easter-38363995',
    'http://www.howcast.com/videos/368909-Easter-Egg-Dying-How-To-Make-Ukrainian-Easter-Eggs',
    'http://www.howcast.com/videos/368911-Easter-Egg-Dying-How-To-Color-Easter-Eggs-With-Food-Dyes',
    'http://www.howcast.com/videos/368913-Easter-Egg-Dying-How-To-Make-Homemade-Easter-Egg-Dye',
    'http://www.howcast.com/videos/220110-The-Meaning-Of-Easter',
    'http://my.opera.com/nirvanka/albums/show.dml?id=519866',
    'http://img402.yfrog.com/i/mfe.jpg/',
    'http://img20.yfrog.com/i/dy6.jpg/',
    'http://img145.yfrog.com/i/4mu.mp4/',
    'http://img15.yfrog.com/i/mygreatmovie.mp4/',
    'http://img159.yfrog.com/i/500x5000401.jpg/',
    'http://tweetphoto.com/14784358',
    'http://tweetphoto.com/16044847',
    'http://tweetphoto.com/16718883',
    'http://tweetphoto.com/16451148',
    'http://tweetphoto.com/16133984',
    'http://tweetphoto.com/8069529',
    'http://tweetphoto.com/16207556',
    'http://tweetphoto.com/7448361',
    'http://tweetphoto.com/16069325',
    'http://tweetphoto.com/4791033',
    'http://www.flickr.com/photos/10349896@N08/4490293418/',
    'http://www.flickr.com/photos/mneylon/4483279051/',
    'http://www.flickr.com/photos/xstartxtodayx/4488996521/',
    'http://www.flickr.com/photos/mommyknows/4485313917/',
    'http://www.flickr.com/photos/29988430@N06/4487127638/',
    'http://www.flickr.com/photos/excomedia/4484159563/',
    'http://www.flickr.com/photos/sunnybrook100/4471526636/',
    'http://www.flickr.com/photos/jaimewalsh/4489497178/',
    'http://www.flickr.com/photos/29988430@N06/4486475549/',
    'http://www.flickr.com/photos/22695183@N08/4488681694/',
    'http://twitpic.com/1cnsf6',
    'http://twitpic.com/1cgtti',
    'http://twitpic.com/1coc0n',
    'http://twitpic.com/1cm8us',
    'http://twitpic.com/1cgks4',
    'http://imgur.com/6pLoN',
    'http://onegoodpenguin.posterous.com/golden-tee-live-2010-easter-egg',
    'http://adland.posterous.com/?tag=royaleastershowauckland',
    'http://apartmentliving.posterous.com/biggest-easter-egg-hunts-in-the-dc-area',
    'http://twitgoo.com/1as',
    'http://twitgoo.com/1p94',
    'http://twitgoo.com/4kg2',
    'http://twitgoo.com/6c9',
    'http://twitgoo.com/1w5',
    'http://twitgoo.com/6mu',
    'http://twitgoo.com/1w3',
    'http://twitgoo.com/1om',
    'http://twitgoo.com/1mh',
    'http://www.qwantz.com/index.php?comic=1686',
    'http://www.qwantz.com/index.php?comic=773',
    'http://www.qwantz.com/index.php?comic=1018',
    'http://www.qwantz.com/index.php?comic=1019',
    'http://www.23hq.com/mhg/photo/5498347',
    'http://www.23hq.com/Greetingdesignstudio/photo/5464607',
    'http://www.23hq.com/Greetingdesignstudio/photo/5464590',
    'http://www.23hq.com/Greetingdesignstudio/photo/5464605',
    'http://www.23hq.com/Greetingdesignstudio/photo/5464604',
    'http://www.23hq.com/dvilles2/photo/5443192',
    'http://www.23hq.com/Greetingdesignstudio/photo/5464606',
    'http://www.youtube.com/watch?v=gghKdx558Qg',
    'http://www.youtube.com/watch?v=yPid9BLQQcg',
    'http://www.youtube.com/watch?v=uEo2vboUYUk',
    'http://www.youtube.com/watch?v=geUhtoHbLu4',
    'http://www.youtube.com/watch?v=Zk7dDekYej0',
    'http://www.youtube.com/watch?v=Q3tgMosx_tI',
    'http://www.youtube.com/watch?v=s9P8_vgmLfs',
    'http://www.youtube.com/watch?v=1cmtN1meMmk',
    'http://www.youtube.com/watch?v=AVzj-U5Ihm0',
    'http://www.veoh.com/collection/easycookvideos/watch/v366931kcdgj7Hd',
    'http://www.veoh.com/collection/easycookvideos/watch/v366991zjpANrqc',
    'http://www.veoh.com/browse/videos/category/educational/watch/v7054535EZGFJqyX',
    'http://www.veoh.com/browse/videos/category/lifestyle/watch/v18155013XBBtnYwq',
    'http://www.justin.tv/easter7presents',
    'http://www.justin.tv/easterfraud',
    'http://www.justin.tv/cccog27909',
    'http://www.justin.tv/clip/6e8c18f7050',
    'http://www.justin.tv/venom24',
    'http://qik.com/video/1622287',
    'http://qik.com/video/1503735',
    'http://qik.com/video/40504',
    'http://qik.com/video/1445763',
    'http://qik.com/video/743285',
    'http://qik.com/video/1445299',
    'http://qik.com/video/1443200',
    'http://qik.com/video/1445889',
    'http://qik.com/video/174242',
    'http://qik.com/video/1444897',
    'http://revision3.com/hak5/DualCore',
    'http://revision3.com/popsiren/charm',
    'http://revision3.com/tekzilla/eyefinity',
    'http://revision3.com/diggnation/2005-10-06',
    'http://revision3.com/hak5/netcat-virtualization-wordpress/',
    'http://revision3.com/infected/forsaken',
    'http://revision3.com/hak5/purepwnage',
    'http://revision3.com/tekzilla/wowheadset',
    'http://www.dailymotion.com/video/xcstzd_greek-wallets-tighten-during-easter_news',
    'http://www.dailymotion.com/video/xcso4y_exclusive-easter-eggs-easter-basket_lifestyle',
    'http://www.dailymotion.com/video/x2sgkt_evil-easter-bunny',
    'http://www.dailymotion.com/video/xco7oc_invitation-to-2010-easter-services_news',
    'http://www.dailymotion.com/video/xcss6b_big-cat-easter_animals',
    'http://www.dailymotion.com/video/xcszw1_easter-bunny-visits-buenos-aires-zo_news',
    'http://www.dailymotion.com/video/xcsfvs_forecasters-warn-of-easter-misery_news',
    'http://www.collegehumor.com/video:1682246',
    'http://www.twitvid.com/D9997',
    'http://www.twitvid.com/902B9',
    'http://www.twitvid.com/C33F8',
    'http://www.twitvid.com/63F73',
    'http://www.twitvid.com/BC0BA',
    'http://www.twitvid.com/1C33C',
    'http://www.twitvid.com/8A8E2',
    'http://www.twitvid.com/51035',
    'http://www.twitvid.com/5C733',
    'http://www.break.com/game-trailers/game/just-cause-2/just-cause-2-lost-easter-egg?res=1',
    'http://www.break.com/usercontent/2010/3/10/easter-holiday-2009-slideshow-1775624',
    'http://www.break.com/index/a-very-sexy-easter-video.html',
    'http://www.break.com/usercontent/2010/3/11/this-video-features-gizzi-erskine-making-easter-cookies-1776089',
    'http://www.break.com/usercontent/2007/4/4/happy-easter-265717',
    'http://www.break.com/usercontent/2007/4/17/extreme-easter-egg-hunting-276064',
    'http://www.break.com/usercontent/2006/11/18/the-evil-easter-bunny-184789',
    'http://www.break.com/usercontent/2006/4/16/hoppy-easter-kitty-91040',
    'http://vids.myspace.com/index.cfm?fuseaction=vids.individual&videoid=104063637',
    'http://vids.myspace.com/index.cfm?fuseaction=vids.individual&videoid=104004674',
    'http://vids.myspace.com/index.cfm?fuseaction=vids.individual&videoid=103928002',
    'http://vids.myspace.com/index.cfm?fuseaction=vids.individual&videoid=103999188',
    'http://vids.myspace.com/index.cfm?fuseaction=vids.individual&videoid=103920940',
    'http://vids.myspace.com/index.cfm?fuseaction=vids.individual&videoid=103981831',
    'http://vids.myspace.com/index.cfm?fuseaction=vids.individual&videoid=104004673',
    'http://vids.myspace.com/index.cfm?fuseaction=vids.individual&videoid=104046456',
    'http://www.metacafe.com/watch/105023/the_easter_bunny/',
    'http://www.metacafe.com/watch/4376131/easter_lay/',
    'http://www.metacafe.com/watch/2245996/how_to_make_ukraine_easter_eggs/',
    'http://www.metacafe.com/watch/4374339/easter_eggs/',
    'http://www.metacafe.com/watch/2605860/filled_easter_baskets/',
    'http://www.metacafe.com/watch/2372088/easter_eggs/',
    'http://www.metacafe.com/watch/3043671/www_goodnews_ws_easter_island/',
    'http://www.metacafe.com/watch/1652057/easter_eggs/',
    'http://www.metacafe.com/watch/1173632/ultra_kawaii_easter_bunny_party/',
    'http://celluloidremix.blip.tv/file/3378272/',
    'http://blip.tv/file/449469',
    'http://blip.tv/file/199776',
    'http://blip.tv/file/766967',
    'http://blip.tv/file/770127',
    'http://blip.tv/file/854925',
    'http://www.blip.tv/file/22695?filename=Uncle_dale-THEEASTERBUNNYHATESYOU395.flv',
    'http://iofa.blip.tv/file/3412333/',
    'http://blip.tv/file/190393',
    'http://blip.tv/file/83152',
    'http://video.google.com/videoplay?docid=-5427138374898988918&q=easter+bunny&pl=true',
    'http://video.google.com/videoplay?docid=7785441737970480237',
    'http://video.google.com/videoplay?docid=2320995867449957036',
    'http://video.google.com/videoplay?docid=-2586684490991458032&q=peeps&pl=true',
    'http://video.google.com/videoplay?docid=5621139047118918034',
    'http://video.google.com/videoplay?docid=4232304376070958848',
    'http://video.google.com/videoplay?docid=-6612726032157145299',
    'http://video.google.com/videoplay?docid=4478549130377875994&hl=en',
    'http://video.google.com/videoplay?docid=9169278170240080877',
    'http://video.google.com/videoplay?docid=2551240967354893096',
    'http://video.yahoo.com/watch/7268801/18963438',
    'http://video.yahoo.com/watch/2224892/7014048',
    'http://video.yahoo.com/watch/7244748/18886014',
    'http://video.yahoo.com/watch/4656845/12448951',
    'http://video.yahoo.com/watch/363942/2249254',
    'http://video.yahoo.com/watch/2232968/7046348',
    'http://video.yahoo.com/watch/4530253/12135472',
    'http://video.yahoo.com/watch/2237137/7062908',
    'http://video.yahoo.com/watch/952841/3706424',
    'http://www.viddler.com/explore/BigAppleChannel/videos/113/',
    'http://www.viddler.com/explore/cheezburger/videos/379/',
    'http://www.viddler.com/explore/warnerbros/videos/350/',
    'http://www.viddler.com/explore/tvcgroup/videos/169/',
    'http://www.viddler.com/explore/thebrickshow/videos/12/',
    'http://www.liveleak.com/view?i=e0b_1239827917',
    'http://www.liveleak.com/view?i=715_1239490211',
    'http://www.liveleak.com/view?i=d30_1206233786&p=1',
    'http://www.liveleak.com/view?i=d91_1239548947',
    'http://www.liveleak.com/view?i=f58_1190741182',
    'http://www.liveleak.com/view?i=44e_1179885621&c=1',
    'http://www.liveleak.com/view?i=451_1188059885',
    'http://www.liveleak.com/view?i=3f5_1267456341&c=1',
    'http://www.hulu.com/watch/67313/howcast-how-to-make-braided-easter-bread',
    'http://www.hulu.com/watch/133583/access-hollywood-glees-matthew-morrison-on-touring-and-performing-for-president-obama',
    'http://www.hulu.com/watch/66319/saturday-night-live-easter-album',
    'http://www.hulu.com/watch/80229/explorer-end-of-easter-island',
    'http://www.hulu.com/watch/139020/nbc-today-show-lamb-and-ham-create-easter-feast',
    'http://www.hulu.com/watch/84272/rex-the-runt-easter-island',
    'http://www.hulu.com/watch/132203/everyday-italian-easter-pie',
    'http://www.hulu.com/watch/23349/nova-secrets-of-lost-empires-ii-easter-island',
    'http://movieclips.com/watch/dirty_harry_1971/do_you_feel_lucky_punk/',
    'http://movieclips.com/watch/napoleon_dynamite_2004/chatting_online_with_babes/',
    'http://movieclips.com/watch/dumb__dumber_1994/the_toilet_doesnt_flush/',
    'http://movieclips.com/watch/jaws_1975/youre_gonna_need_a_bigger_boat/',
    'http://movieclips.com/watch/napoleon_dynamite_2004/chatting_online_with_babes/61.495/75.413',
    'http://movieclips.com/watch/super_troopers_2001/the_cat_game/12.838/93.018',
    'http://movieclips.com/watch/this_is_spinal_tap_1984/these_go_to_eleven/79.703/129.713',
    'http://crackle.com/c/Originals/What_s_the_deal_with_Easter_candy_/2303243',
    'http://crackle.com/c/How_To/Dryer_Lint_Easter_Bunny_Trailer_Park_Craft/2223902',
    'http://crackle.com/c/How_To/Pagan_Origin_of_Easter_Easter_Egg_Rabbit_Playb_/2225124',
    'http://crackle.com/c/Funny/Happy_Easter/2225363',
    'http://crackle.com/c/Funny/Crazy_and_Hilarious_Easter_Egg_Hunt/2225737',
    'http://crackle.com/c/How_To/Learn_About_Greek_Orthodox_Easter/2262294',
    'http://crackle.com/c/How_To/How_to_Make_Ukraine_Easter_Eggs/2262274',
    'http://crackle.com/c/How_To/Symbolism_Of_Ukrainian_Easter_Eggs/2262267',
    'http://crackle.com/c/Funny/Easter_Retard/931976',
    'http://www.fancast.com/tv/It-s-the-Easter-Beagle,-Charlie-Brown/74789/1078053475/Peanuts:-Specials:-It-s-the-Easter-Beagle,-Charlie-Brown/videos',
    'http://www.fancast.com/movies/Easter-Parade/97802/687440525/Easter-Parade/videos',
    'http://www.fancast.com/tv/Saturday-Night-Live/10009/1083396482/Easter-Album/videos',
    'http://www.fancast.com/movies/The-Proposal/147176/1140660489/The-Proposal:-Easter-Egg-Hunt/videos',
    'http://www.funnyordie.com/videos/f6883f54ae/the-unsettling-ritualistic-origin-of-the-easter-bunny',
    'http://www.funnyordie.com/videos/3ccb03863e/easter-tail-keaster-bunny',
    'http://www.funnyordie.com/videos/17b1d36ad0/easter-bunny-from-leatherfink',
    'http://www.funnyordie.com/videos/0c55aa116d/easter-exposed-from-bryan-erwin',
    'http://www.funnyordie.com/videos/040dac4eff/easter-eggs',
    'http://vimeo.com/10446922',
    'http://vimeo.com/10642542',
    'http://www.vimeo.com/10664068',
    'http://vimeo.com/819176',
    'http://www.vimeo.com/10525353',
    'http://vimeo.com/10429123',
    'http://www.vimeo.com/10652053',
    'http://vimeo.com/10572216',
    'http://www.ted.com/talks/jared_diamond_on_why_societies_collapse.html',
    'http://www.ted.com/talks/nathan_myhrvold_on_archeology_animal_photography_bbq.html',
    'http://www.ted.com/talks/johnny_lee_demos_wii_remote_hacks.html',
    'http://www.ted.com/talks/robert_ballard_on_exploring_the_oceans.html',
    'http://www.omnisio.com/v/Z3QxbTUdjhG/wall-e-collection-of-videos',
    'http://www.omnisio.com/v/3ND6LTvdjhG/php-tutorial-4-login-form-updated',
    'http://www.thedailyshow.com/watch/thu-december-14-2000/intro---easter',
    'http://www.thedailyshow.com/watch/tue-april-18-2006/headlines---easter-charade',
    'http://www.thedailyshow.com/watch/tue-april-18-2006/egg-beaters',
    'http://www.thedailyshow.com/watch/tue-april-18-2006/moment-of-zen---scuba-diver-hiding-easter-eggs',
    'http://www.thedailyshow.com/watch/tue-april-7-2009/easter---passover-highlights',
    'http://www.thedailyshow.com/watch/tue-february-29-2000/headlines---leap-impact',
    'http://www.thedailyshow.com/watch/thu-march-1-2007/tomb-with-a-jew',
    'http://www.thedailyshow.com/watch/mon-april-24-2000/the-meaning-of-passover',
    'http://www.colbertnation.com/the-colbert-report-videos/268800/march-31-2010/easter-under-attack---peeps-display-update',
    'http://www.colbertnation.com/the-colbert-report-videos/268797/march-31-2010/intro---03-31-10',
    'http://www.colbertnation.com/full-episodes/wed-march-31-2010-craig-mullaney',
    'http://www.colbertnation.com/the-colbert-report-videos/60902/march-28-2006/the-word---easter-under-attack---marketing',
    'http://www.colbertnation.com/the-colbert-report-videos/83362/march-07-2007/easter-under-attack---bunny',
    'http://www.colbertnation.com/the-colbert-report-videos/61404/april-06-2006/easter-under-attack---recalled-eggs?videoId=61404',
    'http://www.colbertnation.com/the-colbert-report-videos/223957/april-06-2009/colbert-s-easter-parade',
    'http://www.colbertnation.com/the-colbert-report-videos/181772/march-28-2006/intro---3-28-06',
    'http://www.traileraddict.com/trailer/despicable-me/easter-greeting',
    'http://www.traileraddict.com/trailer/easter-parade/trailer',
    'http://www.traileraddict.com/clip/the-proposal/easter-egg-hunt',
    'http://www.traileraddict.com/trailer/despicable-me/international-teaser-trailer',
    'http://www.traileraddict.com/trailer/despicable-me/today-show-minions',   
    'http://revver.com/video/263817/happy-easter/',
    'http://www.revver.com/video/1574939/easter-bunny-house/',
    'http://revver.com/video/771140/easter-08/',
    ]

def submit_all():
    from r2.models import Subreddit, Account, Link, NotFound
    from r2.lib.media import set_media
    from r2.lib.db import queries
    sr = Subreddit._by_name('testmedia')
    author = Account._by_name('testmedia')
    links = []
    for url in test_urls:
        try:
            # delete any existing version of the link
            l = Link._by_url(url, sr)
            print "Deleting %s" % l
            l._deleted = True
            l._commit()
        except NotFound:
            pass

        l = Link._submit(url, url, author, sr, '0.0.0.0')

        try:
            set_media(l)
        except Exception, e:
            print e

        queries.new_link(l)

        links.append(l)

    return links

def test_real(nlinks):
    from r2.models import Link, desc
    from r2.lib.utils import fetch_things2

    counter = 0
    q = Link._query(sort = desc("_date"))

    print "<html><body><table border=\"1\">"
    for l in fetch_things2(q):
        if counter > nlinks:
            break
        if not l.is_self:
            h = make_scraper(l.url)
            mo = h.media_object()
            print "scraper: %s" % mo
            if mo:
                print get_media_embed(mo).content
        counter +=1
    print "</table></body></html>"

def test_url(url):
    import sys
    from r2.lib.filters import websafe
    sys.stderr.write("%s\n" % url)
    print "<tr>"
    h = make_scraper(url)
    print "<td>"
    print "<b>", websafe(url), "</b>"
    print "<br />"
    print websafe(repr(h))
    img = h.largest_image_url()
    if img:
        print "<td><img src=\"%s\" /></td>" % img
    else:
        print "<td>(no image)</td>"
    mo = h.media_object()
    print "<td>"
    if mo:
        print get_media_embed(mo).content
    else:
        print "None"
    print "</td>"
    print "</tr>"

def test():
    """Take some example URLs and print out a nice pretty HTML table
       of their extracted thubmnails and media objects"""
    print "<html><body><table border=\"1\">"
    for url in test_urls:
        test_url(url)
    print "</table></body></html>"

