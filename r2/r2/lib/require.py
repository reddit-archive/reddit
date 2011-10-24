class RequirementException(Exception):
    pass

def require(val):
    """A safe version of assert

    Assert can be stripped out if python is run in an optimized
    mode. This function implements assertions in a way that is
    guaranteed to execute.
    """
    if not val:
        raise RequirementException
    return val

def require_split(s, length, sep=None):
    require(s)
    res = s.split(sep)
    require(len(res) == length)
    return res
