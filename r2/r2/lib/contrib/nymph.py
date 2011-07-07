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
import re, sys, Image, os, hashlib, StringIO

def optimize_png(fname, optimizer = "/usr/bin/env optipng"):
    if os.path.exists(fname):
        os.popen("%s %s" % (optimizer, fname))
    return fname


class Spriter(object):
    spritable = re.compile(r" *background-image: *url\((.*)\) *.*/\* *SPRITE *\*/")

    def __init__(self, padding = (4, 4),
                 css_path = '/static/', actual_path = "r2/public/static/"):
        self.images = []
        self.im_lookup = {}
        self.ypos = [0]
        self.padding = padding

        self.css_path = css_path
        self.actual_path = actual_path

    def make_sprite(self, line):
        path, = self.spritable.findall(line)
        path = re.sub("^" + self.css_path, self.actual_path, path)
        if os.path.exists(path):
            if path in self.im_lookup:
                i = self.im_lookup[path]
            else:
                im = Image.open(path)
                self.images.append(im)
                self.im_lookup[path] = len(self.images) - 1
                self.ypos.append(self.ypos[-1] + im.size[1] +
                                 2 * self.padding[1])
                i = len(self.images) - 1
            return "\n".join([" background-image: url(%(sprite)s);",
                              " background-position: %dpx %spx;" %
                              (-self.padding[0], "%(pos_" + str(i) + ")s"),
                              ""])
        return line

    def finish(self, out_file, out_string):
        width = 2 * self.padding[0] + max(i.size[0] for i in self.images)
        height = sum((i.size[1] + 2 * self.padding[1]) for i in self.images)

        master = Image.new(mode = "RGBA", size = (width, height),
                           color = (0,0,0,0))

        for i, image in enumerate(self.images):
            master.paste(image,
                         (self.padding[0], self.padding[1] + self.ypos[i]))

        f = os.path.join(self.actual_path, out_file)
        master.save(f)

        # optimize the file
        optimize_png(f)

        d = dict(('pos_' + str(i), -self.padding[1] - y)
                 for i, y in enumerate(self.ypos))

        # md5 the final contents
        with open(f) as handle:
            h = hashlib.md5(handle.read()).hexdigest()

        d['sprite'] = os.path.join(self.css_path, "%s?v=%s" % (out_file, h))

        return out_string % d

def process_css(incss, out_file = 'sprite.png', css_path = "/static/"):
    s = Spriter(css_path = css_path)
    out = StringIO.StringIO()

    with open(incss, 'r') as handle:
        for line in handle:
            if s.spritable.match(line):
                out.write(s.make_sprite(line))
            else:
                out.write(line.replace('%', '%%'))

    return s.finish(out_file, out.getvalue())

if __name__ == '__main__':
    import sys
    print process_css(sys.argv[-1], sys.argv[-2])
