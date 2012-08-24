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
# The Original Code is reddit.
#
# The Original Developer is the Initial Developer.  The Initial Developer of
# the Original Code is reddit Inc.
#
# All portions of the code written by reddit are Copyright (c) 2006-2012 reddit
# Inc. All Rights Reserved.
###############################################################################

from ez_setup import use_setuptools
use_setuptools()

from setuptools import find_packages
from distutils.core import setup, Extension
import os
import fnmatch


commands = {}


try:
    from Cython.Distutils import build_ext
except ImportError:
    pass
else:
    commands.update({
        "build_ext": build_ext
    })


try:
    from babel.messages import frontend as babel
    commands.update({
        "compile_catalog": babel.compile_catalog,
        "extract_messages": babel.extract_messages,
        "init_catalog": babel.init_catalog,
        "update_catalog": babel.update_catalog,
    })
except ImportError:
    pass


# add the cython modules
pyx_extensions = []
for root, directories, files in os.walk('.'):
    for f in fnmatch.filter(files, '*.pyx'):
        path = os.path.join(root, f)
        module_name, _ = os.path.splitext(path)
        module_name = os.path.normpath(module_name)
        module_name = module_name.replace(os.sep, '.')
        pyx_extensions.append(Extension(module_name, [path]))


discount_path = "r2/lib/contrib/discount"

setup(
    name="r2",
    version="",
    install_requires=[
        "Routes<=1.8",
        "Pylons==0.9.6.2",
        "webhelpers==0.6.4",
        "boto >= 2.0",
        "pytz",
        "pycrypto",
        "Babel>=0.9.1",
        "cython>=0.14",
        "SQLAlchemy==0.7.4",
        "BeautifulSoup",
        "cssutils==0.9.5.1",
        "chardet",
        "psycopg2",
        "pycountry",
        "pycassa>=1.7.0",
        "PIL",
        "pycaptcha",
        "amqplib",
        "pylibmc==1.2.1-dev",
        "py-bcrypt",
        "python-statsd",
        "snudown>=1.1.0",
        "l2cs",
        "lxml",
        "kazoo",
    ],
    dependency_links=[
        "https://github.com/downloads/reddit/pylibmc/pylibmc-1.2.1-dev.tar.gz#egg=pylibmc-1.2.1-dev",
        "https://nodeload.github.com/reddit/snudown/tarball/v1.1.0#egg=snudown-1.1.0",
        "https://nodeload.github.com/reddit/pycassa/zipball/master#egg=pycassa-1.7.0",
    ],
    packages=find_packages(exclude=["ez_setup"]),
    cmdclass=commands,
    ext_modules=pyx_extensions + [
        Extension(
            "Cfilters",
            sources=[
                "r2/lib/c/filters.c",
            ]
        ),
    ],
    entry_points="""
    [paste.app_factory]
    main=r2:make_app
    [paste.app_install]
    main=pylons.util:PylonsInstaller
    [paste.paster_command]
    run = r2.commands:RunCommand
    shell = pylons.commands:ShellCommand
    controller = pylons.commands:ControllerCommand
    restcontroller = pylons.commands:RestControllerCommand
    """,
)
