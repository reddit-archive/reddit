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
# All portions of the code written by CondeNet are Copyright (c) 2006-2010
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

class MediaEmbed(object):
    width     = None
    height    = None
    content   = None
    scrolling = False

    def __init__(self, height, width, content, scrolling = False):
        self.height    = height
        self.width     = width
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
                mo = YoutubeScraper(youtube_url).media_object()
                mo['deep'] = scraper.url
                return mo

#scrapers =:= dict(domain -> ScraperClass)
scrapers = {}
for scraper in [ YoutubeScraper,
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
                 #CraigslistScraper,
                 GenericScraper,
                 ]:
    for domain in scraper.domains:
        scrapers[domain] = scraper

deepscrapers = [YoutubeEmbedDeepScraper]

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

    'http://www.youtube.com/watch?v=Yu_moia-oVI',
    'http://www.metacafe.com/watch/sy-1473689248/rick_astley_never_gonna_give_you_up_official_music_video/',
    'http://video.google.com/videoplay?docid=5908758151704698048',
    'http://vimeo.com/4495451',
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

    'http://www.rickrolled.com/videos/video/rickrolld' # test the DeepScraper
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

        if g.write_query_queue:
            queries.new_link(l)

        links.append(l)

    return links

def test():
    """Take some example URLs and print out a nice pretty HTML table
       of their extracted thubmnails and media objects"""
    import sys
    from r2.lib.filters import websafe

    print "<html><body><table border=\"1\">"
    for url in test_urls:
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
            s = scrapers[mo['type']]
            print websafe(repr(mo))
            print "<br />"
            print s.media_embed(**mo).content
        else:
            print "None"
        print "</td>"
        print "</tr>"
    print "</table></body></html>"

