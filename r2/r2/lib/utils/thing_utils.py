from datetime import datetime
import pytz

def make_last_modified():
    last_modified = datetime.now(pytz.timezone('GMT'))
    last_modified = last_modified.replace(microsecond = 0)
    return last_modified

def is_modified_since(thing, action, date):
    """Returns true if the date is older than the last_[action] date,
    which means a 304 should be returned. Otherwise returns the date
    that should be sent as the last-modified header."""
    from pylons import g
    
    prop = 'last_' + action
    if not hasattr(thing, prop):
        last_modified = make_last_modified()
        setattr(thing, prop, last_modified)
        thing._commit()
    else:
        last_modified = getattr(thing, prop)

    if not date or date < last_modified:
        return last_modified
    
    #if a date was passed in and it's equal to last modified
    return True

def set_last_modified(thing, action):
    from pylons import g
    setattr(thing, 'last_' + action, make_last_modified())
    thing._commit()
