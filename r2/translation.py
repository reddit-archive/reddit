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
from distutils.cmd import Command
from babel.messages.frontend import new_catalog as _new_catalog, \
     extract_messages as _extract_messages
from distutils.cmd import Command
from distutils.errors import DistutilsOptionError
from babel import Locale
import os, shutil, re



class extract_messages(_extract_messages):
    def initialize_options(self):
        _extract_messages.initialize_options(self)
        self.output_file = 'r2/i18n/r2.pot'
        self.mapping_file = 'babel.cfg'

class new_catalog(_new_catalog):
    def initialize_options(self):
        _new_catalog.initialize_options(self)
        self.output_dir = 'r2/i18n'
        self.input_file = 'r2/i18n/r2.pot'
        self.domain = 'r2'

    def finalize_options(self):
        _new_catalog.finalize_options(self)
        if os.path.exists(self.output_file):
            file2 = self.output_file + "-sav"
            print " --> backing up existing PO file to '%s'" % file2
            shutil.copyfile(self.output_file, file2)

class commit_translation(Command):
    description = 'Turns PO into MO files'
    user_options = [('locale=', 'l',
                     'locale for the new localized catalog'), ]

    def initialize_options(self):
        self.locale = None
        self.output_dir = 'r2/i18n'
        self.domain = 'r2'
        self.string = '_what_'

    def finalize_options(self):
        if not self.locale:
            raise DistutilsOptionError('you must provide a locale for the '
                                       'catalog')

        self.input_file = os.path.join(self.output_dir, self.locale,
                                       'LC_MESSAGES', self.domain + '.po')
        self.output_file = os.path.join(self.output_dir, self.locale,
                                        'LC_MESSAGES', self.domain + '.mo')
    def run(self):
        cmd = 'msgfmt -o "%s" "%s"' % (self.output_file, self.input_file)
        handle = os.popen(cmd)
        print handle.read(),
        handle.close()

class test_translation(new_catalog):
    description = 'makes a mock-up PO and MO file for testing and sets to en'
    user_options = [('locale=', 'l',
                     'locale for the new localized catalog'),
                    ('string=', 's',
                     'global string substitution on translation'),
                    ]

    def initialize_options(self):
        new_catalog.initialize_options(self)
        self.locale = 'en'
        self.string = '_what_'

    def finalize_options(self):
        self.output_file = os.path.join(self.output_dir, self.locale,
                                        'LC_MESSAGES', self.domain + '.po')
        self.output_file_mo = os.path.join(self.output_dir, self.locale,
                                        'LC_MESSAGES', self.domain + '.mo')

        if not os.path.exists(os.path.dirname(self.output_file)):
            os.makedirs(os.path.dirname(self.output_file))

        self._locale = Locale.parse('en')
        self._locale.language = self.locale

    def run(self):
        new_catalog.run(self)
        handle = open(self.output_file)
        res = ''
        counter = 0
        formatting_string = False
        for line in handle:
            if not ('""' in line):
                strlen = len(re.findall(r"\S+", line)) - 1
            if "%" in line:
                formatting_string = re.findall(r"%\S+", line)
                strlen -= len(formatting_string)
                formatting_string = (', '.join(formatting_string)).strip('"')
            if '""' in line and not("msgid" in line):
                strlen = 1 if strlen < 1 else strlen
                string = ' '.join([self.string for x in range(0, strlen)])
                if formatting_string:
                    string = '%s [%s]' %(string, formatting_string)
                    formatting_string = ''
                string = '"%s"' % string
                res += line if counter < 1 else line.replace('""', string)
                counter += 1
            elif line.startswith('"Last-Translator:'):
                res += line.replace("FULL NAME", "Babel Phish")
            else:
                res += line
        handle.close()
        handle = open(self.output_file, 'w')
        handle.write(res)
        handle.close()
        cmd = 'msgfmt -o "%s" "%s"' % (self.output_file_mo, self.output_file)
        handle = os.popen(cmd)
        print "converting to MO file..."
        print handle.read(),
        handle.close()

