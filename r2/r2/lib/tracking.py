# "The contents of this file are subject to the Common Public Attribution
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
from base64 import standard_b64decode as b64dec, \
     standard_b64encode as b64enc
from Crypto.Cipher import AES
from random import choice
from pylons import g, c
from urllib import quote_plus, unquote_plus

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
    '''returns a pycrypto object used by encrypt and decrypt, with the key based on g.SECRET'''
    key = g.SECRET
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
        print "unicode encoding exception in safe_str"
        return ''
    return text

class UserInfo():
    '''Class for generating and reading user tracker information.'''
    __slots__ = ['name', 'site', 'lang']
    
    def __init__(self, text = ''):
        for s in self.__slots__:
            setattr(self, s, '')
            
        if text:
            try:
                data = decrypt(text).split('|')
            except:
                print "decryption failure on '%s'" % text
                data = []
            for i, d in enumerate(data):
                if i < len(self.__slots__):
                    setattr(self, self.__slots__[i], d)
        else:
            self.name = safe_str(c.user.name if c.user_is_loggedin else '')
            self.site = safe_str(c.site.name if c.site else '')
            self.lang = safe_str(c.lang if c.lang else '')
            
    def tracking_url(self):
        data = '|'.join(getattr(self, s) for s in self.__slots__)
        data = encrypt(data)
        return "%s?v=%s" % (g.tracker_url, data)
        

def gen_url():
    """function for safely creating a tracking url, trapping exceptions so as not to interfere with
    the app"""
    try:
        return UserInfo().tracking_url()
    except Exception, e:
        print "error in gen_url!!!!!"
        print e
        try:
            randstr = ''.join(choice('1234567890abcdefghijklmnopqrstuvwxyz' +
                                     'ABCDEFGHIJKLMNOPQRSTUVWXYZ+')
                              for x in xrange(pad_len))
            return "%s?v=%s" % (g.tracker_url, randstr)
        except:
            print "fallback rendering failed as well"
            return ""


def benchmark(n = 10000):
    """on my humble desktop machine, this gives ~150 microseconds per gen_url"""
    import time
    t = time.time()
    for x in xrange(n):
        gen_url()
    t = time.time() - t
    print ("%d generations in %5.3f seconds (%5.3f us/gen)" % 
           (n, t, 10**6 * t/n))
