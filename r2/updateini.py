#!/usr/bin/env python
from ConfigParser import RawConfigParser as Parser
from ConfigParser import MissingSectionHeaderError
from StringIO import StringIO
import sys

HEADER = '''
# YOU DO NOT NEED TO EDIT THIS FILE
# This is a generated file. To update the configuration,
# edit the *.update file of the same name, and then
# run 'make ini'
# Configuration settings in the *.update file will override
# or be added to the base 'example.ini' file.
'''

def main(source_ini, update_ini):
    parser = Parser()
    # By default, the parser is case insensitve and rewrites config
    # keys to lowercase. reddit is case sensitive, however
    # See: http://docs.python.org/library/configparser.html#ConfigParser.RawConfigParser.optionxform
    parser.optionxform = str
    # parser.read() will "fail" silently if the file is
    # not found; use open() and parser.readfp() to fail
    # on missing (or unreadable, etc.) file
    parser.readfp(open(source_ini))
    with open(update_ini) as f:
        updates = f.read()
    try:
        # Existing *.update files don't include section
        # headers; inject a [DEFAULT] header if the parsing
        # fails
        parser.readfp(StringIO(updates))
    except MissingSectionHeaderError:
        updates = "[DEFAULT]\n" + updates
        parser.readfp(StringIO(updates))
    print HEADER
    parser.write(sys.stdout)

if __name__ == '__main__':
    args = sys.argv
    if len(args) != 3:
        print 'usage: %s [source] [update]' % sys.argv[0]
        sys.exit(1)
    else:
        main(sys.argv[1], sys.argv[2])
