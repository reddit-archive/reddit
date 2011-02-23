from datetime import datetime
from utils import tup
import pytz

def make_last_modified():
    last_modified = datetime.now(pytz.timezone('GMT'))
    last_modified = last_modified.replace(microsecond = 0)
    return last_modified

def last_modified_key(thing, action):
    return 'last_%s_%s' % (str(action), thing._fullname)

def last_modified_date(thing, action, set_if_empty = True):
    """Returns the date that should be sent as the last-modified header."""
    from pylons import g
    cache = g.permacache

    key = last_modified_key(thing, action)
    last_modified = cache.get(key)
    if not last_modified and set_if_empty:
        #if there is no last_modified, add one
        last_modified = make_last_modified()
        cache.set(key, last_modified)
    return last_modified

def set_last_modified(thing, action):
    from pylons import g
    key = last_modified_key(thing, action)
    g.permacache.set(key, make_last_modified())


def set_last_modified_for_cls(user, cls_type_name):
    if cls_type_name != "vote_account_link":
        set_last_modified(user, "cls_" + cls_type_name)

def get_last_modified_for_cls(user, cls_type_name):
    # vote times are already stored in the permacache and updated by the
    # query queue
    if cls_type_name == "vote_account_link":
        return max(last_modified_date(user, "liked"),
                   last_modified_date(user, "disliked"))
    # other types are not -- special key for them
    elif cls_type_name in ("vote_account_comment", "savehide"):
        return last_modified_date(user, "cls_" + cls_type_name)

def last_modified_multi(things, action):
    from pylons import g
    cache = g.permacache

    things = tup(things)
    keys = dict((last_modified_key(thing, action), thing) for thing in things)

    last_modified = cache.get_multi(keys.keys())
    return dict((keys[k], v) for k, v in last_modified.iteritems())


def set_last_visit(thing):
    from pylons import g
    from r2.lib.cache import CL_ONE
    key = last_modified_key(thing, "visit")
    g.permacache.set(key, make_last_modified())

def last_visit(thing):
    from pylons import g
    res = last_modified_date(thing, "visit", False)
    if res is None:
        res = getattr(thing, "last_visit", None)
        if res:
            g.permacache.set(last_modified_key(thing, "visit"), res)
    return res

def last_visit_multi(things):
    return last_modified_multi(things, "visit")


