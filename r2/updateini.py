#!/usr/bin/env python

import re, sys

line_rx = re.compile('\A([-_a-zA-Z0-9 ]*[-_a-zA-Z0-9]+)\s*=\s*(.*)')

def parse_line(line):
    m = line_rx.match(line)
    if m:
        return m.groups()

def main(source_ini, update_ini):
    #read in update file
    update_parts = {}
    for line in open(update_ini):
        m = parse_line(line)
        if m:
            update_parts[m[0]] = m[1]

    #pass through main file
    m = None
    for line in open(source_ini):
        line = line.strip()
        m = parse_line(line)
        if m and update_parts.has_key(m[0]):
            line = '%s = %s' % (m[0], update_parts[m[0]])
        print line

if __name__ == '__main__':
    args = sys.argv
    if len(args) != 3:
        print 'usage: iniupdate.py [source] [update]'
        sys.exit(1)
    else:
        main(sys.argv[1], sys.argv[2])
