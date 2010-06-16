from datetime import datetime, timedelta
from pylons import g

cdef extern from "math.h":
    double log10(double)
    double sqrt(double)

epoch = datetime(1970, 1, 1, tzinfo = g.tz)

cpdef double epoch_seconds(date):
    """Returns the number of seconds from the epoch to date. Should
       match the number returned by the equivalent function in
       postgres."""
    td = date - epoch
    return td.days * 86400 + td.seconds + (float(td.microseconds) / 1000000)

cpdef long score(long ups, long downs):
    return ups - downs

cpdef double hot(long ups, long downs, date):
    return _hot(ups, downs, epoch_seconds(date))

cpdef double _hot(long ups, long downs, double date):
    """The hot formula. Should match the equivalent function in postgres."""
    s = score(ups, downs)
    order = log10(max(abs(s), 1))
    if s > 0:
        sign = 1
    elif s < 0:
        sign = -1
    else:
        sign = 0
    seconds = date - 1134028003
    return round(order + sign * seconds / 45000, 7)

cpdef double controversy(long ups, long downs):
    """The controversy sort."""
    return float(ups + downs) / max(abs(score(ups, downs)), 1)

cpdef double _confidence(int ups, int downs):
    """The confidence sort.
       http://www.evanmiller.org/how-not-to-sort-by-average-rating.html"""
    cdef float n = ups + downs
    cdef float z
    cdef float phat

    if n == 0:
        return 0

    z = 1.0 #1.0 = 85%, 1.6 = 95%
    phat = float(ups) / n
    return sqrt(phat+z*z/(2*n)-z*((phat*(1-phat)+z*z/(4*n))/n))/(1+z*z/n)

cdef int up_range = 400
cdef int down_range = 100
cdef list _confidences = []
for ups in xrange(up_range):
    for downs in xrange(down_range):
        _confidences.append(_confidence(ups, downs))
def confidence(int ups, int downs):
    if ups + downs == 0:
        return 0
    elif ups < up_range and downs < down_range:
        return _confidences[downs + ups * down_range]
    else:
        return _confidence(ups, downs)
