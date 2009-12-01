from pylons import g, c
import sha, base64, time, re, urllib, socket
import ImageFont
from r2.lib.wrapped import Templated
from r2.lib.pages import LinkInfoPage
from r2.models import *
from httplib import HTTPConnection
from urlparse import urlparse
from BeautifulSoup import BeautifulStoneSoup

colors = (("black",2), ("white", 1), ("navy",4), ("heather",231), ("red",5))
sizes  = (("small",2), ("medium",3), ("large",4), ("xlarge", 5), ("xxlarge",6))

articles = {"women": 
            dict(black = 4604645, 
                 heather = 4604654,
                 navy = 4737035,
                 red  = 4604670,
                 white = 4604694,
                 ),
            "men" :
            dict(black = 4589785, 
                 heather = 4599883,
                 navy = 4737029,
                 red  = 4589762,
                 white = 4589259,
                 ) }
                

spreadshirt_url = urlparse(g.spreadshirt_url)
try:
    test_font = ImageFont.truetype(g.spreadshirt_test_font,
                                   int(g.spreadshirt_min_font))
except IOError:
    test_font = None

word_re = re.compile(r"\w*\W*", re.UNICODE)
def layout_text(text, max_width = None):
    if test_font:
        words = list(reversed(word_re.findall(text)))
        lines = [""]
        while words:
            word = words.pop()
            w = test_font.getsize(lines[-1] + word)[0]
            if w < max_width:
                lines[-1] += word
            else:
                lines.append(word)
        lines = [x.strip() for x in filter(None, lines)]
        return all(test_font.getsize(x)[0] < max_width for x in lines), lines
    return None, []
    
def spreadshirt_validation(s):
    t = str(int(time.time()))
    return t, base64.b64encode(sha.new(s+t+g.spreadshirt_vendor_id).digest())

def shirt_request(link, color, style, size, quantity):
    article = articles.get(style, {}).get(color)
    size  = dict(sizes).get(size)
    color = dict(colors).get(color)

    # load up previous session id (if there was one)
    sessionid = c.cookies.get("spreadshirt")
    sessionid = sessionid.value if sessionid else ""
    
    if link and color and size and quantity and article:
        # try to layout the text
        text = ShirtPane.make_text(link)
        if text:
            author = Account._byID(link.author_id)
            request_dict = dict(color = color, 
                                quantity = quantity, 
                                sessionId = sessionid, 
                                size = size, 
                                article_id = article)
            for i, t in enumerate(text):
                request_dict["textrow_%d" % (i+1)] = t
            request_dict["textrow_6"] = "submitted by %s" % author.name
            request_dict["textrow_7"] = link._date.strftime("%B %e, %Y")
            text.extend([request_dict["textrow_6"], request_dict["textrow_7"]])

            t, code = spreadshirt_validation("".join(text))
            request_dict['timestamp'] = t
            request_dict['hash'] = code

            params = urllib.urlencode(request_dict)
            headers = {"Content-type": "application/x-www-form-urlencoded",
                       "Accept": "text/plain"}
            data = None
            try:
                conn = HTTPConnection(spreadshirt_url.hostname)
                conn.request("POST", spreadshirt_url.path, params, headers)
                response = conn.getresponse()
                if int(response.status) == 200:
                    data = BeautifulStoneSoup(response.read())
                conn.close()
            except socket.error:
                return 

            if data:
                if not data.find("error"):
                    session_id = data.sessionid.contents[0]
                    data = data.basketurl.contents[0]
                    # set session id before redirecting
                    c.cookies.add("spreadshirt", session_id)
                else: 
                    g.log.error("Spreadshirt Error:\n" )
                    g.log.error(data.prettify() + '\n')
                    g.log.error("POST and params: " + g.spreadshirt_url) 
                    g.log.error(params)
                    data = None
            
            return data


class ShirtPage(LinkInfoPage):
    extension_handling= False
    additional_css = "spreadshirt.css"
    def __init__(self, *a, **kw):
        kw['show_sidebar'] = False
        LinkInfoPage.__init__(self, *a, **kw)

    def content(self):
        return self.content_stack((self.link_listing,
                                   ShirtPane(self.link)))

class ShirtPane(Templated):
    default_color = "black"
    default_size = "large"
    default_style = "men"

    colors = [x for x, y in colors]
    styles = ("men", "women")
    sizes  = [x for x, y in sizes]

    def __init__(self, link, **kw):
        Templated.__init__(self, link = link, text = self.make_text(link),  **kw)

    @classmethod
    def make_text(cls, link):
        fit, text = layout_text(link.title, 
                                int(g.spreadshirt_max_width))
        if len(text) > 5 or not fit:
            text = []
        return text
