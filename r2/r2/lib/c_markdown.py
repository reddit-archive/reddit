from ctypes import cdll, c_int, c_void_p, byref, string_at
from r2.lib.filters import _force_utf8
from pylons import g

libmd = cdll.LoadLibrary(g.paths['root'] + '/../reddit-discount.so')

def c_markdown(text, nofollow=False, target=None):
    u8 = _force_utf8(text)
    size = c_int(len(u8))
    nofollow = 1 if nofollow else 0
    doc = c_void_p()
    html = c_void_p()

    libmd.reddit_discount_wrap(u8, nofollow, target,
                               byref(doc), byref(html), byref(size))
    r = string_at(html, size)
    libmd.reddit_discount_cleanup(doc)

    return r
