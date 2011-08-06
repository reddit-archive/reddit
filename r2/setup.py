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

from setuptools import find_packages
from distutils.core import setup, Extension
import os

commands = {}
try:
    from babel.messages import frontend as babel
    commands.update({
        'compile_catalog': babel.compile_catalog,
        'extract_messages': babel.extract_messages,
        'init_catalog': babel.init_catalog,
        'update_catalog': babel.update_catalog,
    })
except ImportError:
    pass

filtermod = Extension('Cfilters',
                      sources = ['r2/lib/c/filters.c'])

discount_path = "r2/lib/contrib/discount"
discountmod = Extension('reddit-discount',
                        include_dirs = [discount_path],
                        define_macros = [("VERSION", '"1.6.8"')],
                        sources = ([ "r2/lib/c/reddit-discount-wrapper.c" ]
                                   + map(lambda x: os.path.join(discount_path, x),
                                      ["Csio.c",
                                       "css.c",
                                       "docheader.c",
                                       "dumptree.c",
                                       "generate.c",
                                       "main.c",
                                       "markdown.c",
                                       "mkdio.c",
                                       "resource.c",
                                       "html5.c",
                                       "tags.c",
                                       "toc.c",
                                       "version.c",
                                       "emmatch.c",
                                       "basename.c",
                                       "xml.c",
                                       "xmlpage.c"])))
ext_modules = [filtermod, discountmod]

setup(
    name='r2',
    version="",
    install_requires=["Routes<=1.8",
                      "Pylons==0.9.6.2",
                      "webhelpers==0.6.4",
                      "boto >= 1.9b",
                      "pytz",
                      "pycrypto",
                      "Babel>=0.9.1",
                      "cython>=0.14",
                      "SQLAlchemy==0.5.3",
                      "BeautifulSoup",
                      "cssutils==0.9.5.1",
                      "chardet",
                      "psycopg2",
                      "pycountry",
                      "pycassa==1.1.0",
                      "PIL",
                      "pycaptcha",
                      "amqplib",
                      "pylibmc==1.1.1"
                      ],
    packages=find_packages(exclude=['ez_setup']),
    include_package_data=True,
    test_suite = 'nose.collector',
    package_data={'r2': ['i18n/*/LC_MESSAGES/*.mo']},
    cmdclass = commands,
    ext_modules = ext_modules,
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
