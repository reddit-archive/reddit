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
# All portions of the code written by reddit are Copyright (c) 2006-2012 reddit
# Inc. All Rights Reserved.
###############################################################################

from base64 import standard_b64decode as b64dec, \
     standard_b64encode as b64enc
from pylons import request
from Crypto.Cipher import AES
from random import choice
from pylons import g, c
from urllib import quote_plus, unquote_plus
import hashlib
import urllib

key_len = 16
pad_len = 32

def pkcs5pad(text, padlen = 8):
    '''Insures the string is an integer multiple of padlen by appending to its end
    N characters which are chr(N).'''
    l = (padlen - len(text) % padlen) or padlen
    padding = ''.join([chr(l) for x in xrange(0,l)])
    return text + padding

def pkcs5unpad(text, padlen = 8):
    '''Undoes padding of pkcs5pad'''
    if text:
        key = ord(text[-1])
        if (key <= padlen and key > 0 and
            all(ord(x) == key for x in text[-key:])):
            text = text[:-key]
    return text

def cipher(lv):
    '''returns a pycrypto object used by encrypt and decrypt, with the key based on g.tracking_secret'''
    key = g.tracking_secret
    return AES.new(key[:key_len], AES.MODE_CBC, lv[:key_len])

def encrypt(text):
    '''generates an encrypted version of text.  The encryption is salted using the pad_len characters
    that randomly make up the front of the resulting string.  The string is base64 encoded, and url escaped
    so as to be suitable to be used as a GET parameter'''
    randstr = ''.join(choice('1234567890abcdefghijklmnopqrstuvwxyz' +
                             'ABCDEFGHIJKLMNOPQRSTUVWXYZ+/')
                      for x in xrange(pad_len))
    cip = cipher(randstr)
    text = b64enc(cip.encrypt(pkcs5pad(text, key_len)))
    return quote_plus(randstr + text, safe='')

def decrypt(text):
    '''Inverts encrypt'''
    # we can unquote even if text is not quoted.  
    text = unquote_plus(text)
    # grab salt
    randstr = text[:pad_len]
    # grab message
    text = text[pad_len:]
    cip = cipher(randstr)
    return pkcs5unpad(cip.decrypt(b64dec(text)), key_len)


def safe_str(text):
    '''That pesky function always needed to make sure nothing breaks if text is unicode.  if it is,
    it returns the utf8 transcode of it and returns a python str.'''
    try:
        if isinstance(text, unicode):
            return text.encode('utf8')
    except:
        g.log.error("unicode encoding exception in safe_str")
        return ''
    return str(text)

class Info(object): 
    '''Class for generating and reading user tracker information.'''
    _tracked = []
    tracker_url = ""

    def __init__(self, text = '', **kw):
        for s in self._tracked:
            setattr(self, s, '')
            
        if text:
            try:
                data = decrypt(text).split('|')
            except:
                g.log.error("decryption failure on '%s'" % text)
                data = []
            for i, d in enumerate(data):
                if i < len(self._tracked):
                    setattr(self, self._tracked[i], d)
        else:
            self.init_defaults(**kw)
            
    def init_defaults(self, **kw):
        raise NotImplementedError
    
    def tracking_url(self):
        data = '|'.join(getattr(self, s) for s in self._tracked)
        data = encrypt(data)
        return "%s?v=%s" % (self.tracker_url, data)

    @classmethod
    def gen_url(cls, **kw):
        try:
            return cls(**kw).tracking_url()

        except Exception,e:
            g.log.error(e)
            try:
                randstr = ''.join(choice('1234567890abcdefghijklmnopqrstuvwxyz' +
                                         'ABCDEFGHIJKLMNOPQRSTUVWXYZ+')
                                  for x in xrange(pad_len))
                return "%s?v=%s" % (cls.tracker_url, randstr)
            except:
                g.log.error("fallback rendering failed as well")
                return ""

class UserInfo(Info):
    '''Class for generating and reading user tracker information.'''
    _tracked = ['name', 'site', 'lang', 'cname']
    tracker_url = g.tracker_url

    @staticmethod
    def get_site():
        return safe_str(c.site.name if c.site else '')

    @staticmethod
    def get_srpath():
        name = UserInfo.get_site()

        action = None
        if c.render_style in ("mobile", "compact"):
            action = c.render_style
        else:
            try:
                action = request.environ['pylons.routes_dict'].get('action')
            except Exception,e:
                g.log.error(e)

        if not action:
            return name
        return '-'.join((name, action))

    @staticmethod
    def get_usertype():
        return "loggedin" if c.user_is_loggedin else "guest"

    def init_defaults(self):
        self.name = safe_str(c.user.name if c.user_is_loggedin else '')
        self.site = UserInfo.get_srpath()
        self.lang = safe_str(c.lang if c.lang else '')
        self.cname = safe_str(c.cname)

class PromotedLinkInfo(Info):
    _tracked = []
    tracker_url = g.adtracker_url

    def __init__(self, text = "", ip = "0.0.0.0", **kw):
        self.ip = ip
        Info.__init__(self, text = text, **kw)

    def init_defaults(self, fullname):
        self.fullname = fullname

    @classmethod
    def make_hash(cls, ip, fullname):
        return hashlib.sha1("%s%s%s" % (ip, fullname,
                                        g.tracking_secret)).hexdigest()

    def tracking_url(self):
        return (self.tracker_url + "?hash=" +
                self.make_hash(self.ip, self.fullname)
                + "&id=" + self.fullname)

class PromotedLinkClickInfo(PromotedLinkInfo):
    _tracked = []
    tracker_url = g.clicktracker_url

    def init_defaults(self, dest, **kw):
        self.dest = dest

        return PromotedLinkInfo.init_defaults(self, **kw)

    def tracking_url(self):
        s = (PromotedLinkInfo.tracking_url(self) + '&url=' +
             urllib.quote_plus(self.dest))
        return s

class AdframeInfo(PromotedLinkInfo):
    tracker_url = g.adframetracker_url

    @classmethod
    def make_hash(cls, ip, fullname):
        return hashlib.sha1("%s%s" % (fullname,
                                      g.tracking_secret)).hexdigest()



def benchmark(n = 10000):
    """on my humble desktop machine, this gives ~150 microseconds per gen_url"""
    import time
    t = time.time()
    for x in xrange(n):
        gen_url()
    t = time.time() - t
    print ("%d generations in %5.3f seconds (%5.3f us/gen)" % 
           (n, t, 10**6 * t/n))
