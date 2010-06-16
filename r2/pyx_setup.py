#!/usr/bin/env python

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

from ez_setup import use_setuptools
use_setuptools()
from setuptools import find_packages#, setup
from distutils.core import setup, Extension
from Cython.Distutils import build_ext
import os, sys
import shutil

def build_so(pyx_file):
    if not pyx_file.endswith(".pyx"):
        raise ValueError, "expected a pyx file, got %s" % pyx_file
    if not os.path.exists(pyx_file):
        raise ValueError, "pyx file does not exist: %s" % pyx_file
    lib = pyx_file[:-4].replace('/', '.').lstrip(".")
    name = lib.split('.')[-1]
    ext_modules = [ Extension(lib, [pyx_file]) ]
    setup(
        name=name,
        version="",
        packages=find_packages(),
        include_package_data=True,
        test_suite = 'nose.collector',
        cmdclass = {'build_ext': build_ext},
        ext_modules = ext_modules,
        )
    shutil.rmtree(name + '.egg-info')


if __name__ == "__main__":
    build_so(sys.argv.pop())
