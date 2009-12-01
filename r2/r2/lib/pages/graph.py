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
# All portions of the code written by CondeNet are Copyright (c) 2006-2009
# CondeNet, Inc. All Rights Reserved.
################################################################################
import math, datetime, locale

def google_extended(n):
    """Computes the google extended encoding of an int in [0, 4096)"""
    numerals = ("ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                "abcdefghijklmnopqrstuvwxyz"
                "0123456789-.")
    base = len(numerals)
    assert(0 <= n <= base ** 2)
    q, r = divmod(int(n), base)
    return numerals[q] + numerals[r]

def make_date_axis_labels(series):
    """
    assuming a uniform date series, generate a suitable axis label 
    """
    _max = max(series)
    _min = min(series)
    delta = _max - _min
    if delta < datetime.timedelta(0, 0.5 * 86400):
        test   = lambda cur, prev: cur.hour != prev.hour and cur.hour % 3 == 0
        format = "%H:00"
    elif delta < datetime.timedelta(2):
        test   = lambda cur, prev: cur.hour != prev.hour and cur.hour % 6 == 0
        format = "%H:00"
    elif delta < datetime.timedelta(7):
        test = lambda cur, prev: cur.day != prev.day
        format = "%d %b"
    elif delta < datetime.timedelta(14):
        test = lambda cur, prev: cur.day != prev.day  and cur.day % 2 == 0 
        format = "%d %b"
    elif delta < datetime.timedelta(30):
        test = lambda cur, prev: (cur.day != prev.day) and cur.weekday() == 6
        format = "%d %b"
    else:
        test = lambda cur, prev: (cur.month != prev.month)
        format = "%b"
    new_series = []
    prev = None
    for s in series:
        if prev and test(s, prev):
            new_series.append(s.strftime(format))
        else:
            new_series.append("")
        prev = s
    return new_series
   

class DataSeries(list):
    def __init__(self, data):
        list.__init__(self, data)

    def low_precision_max(self, precision = 2):
        """
        Compute the max of the data set, including at most 'precision'
        units of decimal precision in the result (e.g., 9893 -> 9900 if
        precision = 2)
        """
        _max = float(max(self))
        if _max == 0:
            return 0
        scale = math.log10(_max)
        scale = 10 ** (math.ceil(scale) - precision)
        return math.ceil(_max / scale) * scale

    def normalize(self, norm_max = 100, precision = 2, _max = None):
        _min = min(self)
        _max = _max or max(self)
        if _min == _max:
            return DataSeries(int(norm_max)/2. 
                              for i in xrange(len(self)))
        else:
            return DataSeries(min(int(x * float(norm_max) / _max), norm_max -1)
                                  for x in self)
        
    def toBarY(self):
        data = []
        for i in xrange(len(self)):
            data += [self[i], self[i]]
        return DataSeries(data)

    def toBarX(self):
        if len(self) > 1:
            delta = self[-1] - self[-2]
        else:
            delta = 0
        data = self.toBarY()
        return DataSeries(data[1:] + [data[-1] + delta])

    def is_regular(self):
        return all(self[i] - self[i-1] == self[1] - self[0] 
                   for i in xrange(1, len(self)))

    def to_google_extended(self, precision = 1, _max = None):
        if _max is None:
            _max = self.low_precision_max(precision = precision)
        norm_max = 4096
        new = self.normalize(norm_max = norm_max, precision = precision,
                             _max = _max)
        return _max, "".join(map(google_extended, new))

class LineGraph(object):
    """
    General line chart class for plotting xy line graphs.

    data is passed in as a series of tuples of the form (x, y_1, ...,
    y_n) and converted to a single xdata DataSeries, and a list of
    ydata DataSeries elements.  The intention of this class is to be
    able to handle multiple final plot representations, thought
    currenly only google charts is available.

    At some point, it also might make sense to connect this more
    closely with numpy.

    """
    google_api = "http://chart.apis.google.com/chart"

    def __init__(self, xydata, colors = ("FF4500", "336699"),
                 width = 300, height = 175):

        series = zip(*xydata)

        self.xdata = DataSeries(series[0])
        self.ydata = map(DataSeries, series[1:])
        self.width = width
        self.height = height
        self.colors = colors

    def google_chart(self, multiy = True, ylabels = [], title = "", 
                     bar_fmt = True):
        xdata, ydata = self.xdata, self.ydata

        # Bar format makes the line chart look like it is a series of
        # contiguous bars without the boundary line between each bar.
        if bar_fmt:
            xdata = DataSeries(range(len(self.xdata))).toBarX()
            ydata = [y.toBarY() for y in self.ydata]

        # TODO: currently we are only supporting time series.  Make general
        xaxis = make_date_axis_labels(self.xdata)

        # Convert x data into google extended text format
        xmax, xdata = xdata.to_google_extended(_max = max(xdata))
        ymax0 = None

        # multiy <=> 2 y axes with independent scaling.  not multiy
        # means we need to know what the global max is over all y data
        multiy = multiy and len(ydata) == 2
        if not multiy:
            ymax0 = max(y.low_precision_max() for y in ydata)

        def make_labels(i, m, p = 4):
            return (("%d:|" % i) + 
                    '|'.join(locale.format('%d', i * m / p, True)
                             for i in range(p+1)))
        
        # data stores a list of xy data strings in google's format
        data = []
        labels = []
        for i in range(len(ydata)):
            ymax, y = ydata[i].to_google_extended(_max = ymax0)
            data.append(xdata + ',' + y)
            if multiy:
                labels.append(make_labels(i,ymax))
        if not multiy:
            labels.append(make_labels(0,ymax0))

        if multiy:
            labels.append('2:|' + '|'.join(xaxis))
            axes = 'y,r,x'
            if len(self.colors) > 1:
                ycolor = "0,%s|1,%s" % (self.colors[0], self.colors[1])
            else:
                ycolor = ""
        else: 
            labels.append('1:|' + '|'.join(xaxis))
            axes = 'y,x'
            ycolor="",
        if ylabels:
            axes += ',t'
            labels.append('%d:|' % (len(axes)/2) +
                          ('|' if multiy else ', ').join(ylabels))
        if title:
            axes += ',t'
            labels.append('%d:||%s|' % (len(axes)/2, title))
            
        if len(self.colors) >= len(self.ydata):
            colors = ",".join(self.colors[:len(self.ydata)])
        else:
            colors = ""
        args = dict(# chart type is xy
                    cht = 'lxy',
                    # chart size
                    chs = "%sx%s" % (self.width, self.height),
                    # which axes are labeled
                    chxt= axes,
                    # axis labels
                    chxl = '|'.join(labels),
                    # chart data is in extended format
                    chd = 'e:' + ','.join(data),
                    chco = colors,
                    chxs = ycolor
                    )

        return (self.google_api +
                '?' + '&'.join('%s=%s' % (k, v) for k, v in args.iteritems()))
        

