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

try:
    from babel.messages import frontend as babel
except:
    class null(): pass
    babel = null()
    babel.compile_catalog = None
    babel.extract_messages = None
    babel.init_catalog = None
    babel.update_catalog = None

from distutils.core import setup, Extension

from setuptools.command.easy_install import main as easy_install
import os

# check the PIL is installed; since its package name isn't the same as
# the distribution name, setuptools can't manage it as a dependency
try:
    import Image
except ImportError:
    print "Installing the Python Imaging Library"
    easy_install(["http://effbot.org/downloads/Imaging-1.1.6.tar.gz"])

# same with the captcha library
try:
    import Captcha
except ImportError:
    print "Installing the PyCaptcha Module"
    easy_install(["http://svn.navi.cx/misc/trunk/pycaptcha"])

# ditto for pylons
try:
    import pylons
    vers = pylons.__version__
    assert vers.startswith('0.9.6.') or vers == '0.9.6', \
           ("reddit is only compatible with pylons 0.9.6, not '%s'" % vers)
except ImportError:
    print "Installing Pylons 0.9.6.2 from the cheese shop"
    easy_install(["http://pypi.python.org/packages/source/P/Pylons/Pylons-0.9.6.2.tar.gz"])

# Install our special version of paste that dies on first zombie sighting
try:
    import paste
    vers = getattr(paste, "__version__", "(undefined)")
    assert vers == '1.7.2-reddit-0.1', \
           ("reddit is only compatible with its own magical version of paste, not '%s'" % vers)
except (ImportError, AssertionError):
    print "Installing reddit's magical version of paste"
    easy_install(["http://addons.reddit.com/paste/Paste-1.7.2-reddit-0.1.tar.gz"])

#install the devel version of py-amqplib until the cheeseshop version is updated
try:
    import amqplib
except ImportError:
    print "Installing the py-amqplib"
    easy_install(["http://addons.reddit.com/amqp/py-amqplib-0.6.1-devel.tgz"])

# we're using a custom build of pylibmc at the moment, so we need to
# be sure that we have the right version
pylibmc_version = '1.0-reddit-04'
try:
    import pylibmc
    assert pylibmc.__version__ == pylibmc_version
except (ImportError, AssertionError):
    print "Installing pylibmc"
    easy_install(["http://github.com/downloads/ketralnis/pylibmc/pylibmc-1.0-reddit-04.tar.gz"])

filtermod = Extension('Cfilters',
                      sources = ['r2/lib/c/filters.c'])

discount_path = "r2/lib/contrib/discount"
discountmod = Extension('reddit-discount',
                        include_dirs = [discount_path],
                        define_macros = [("VERSION", '"1.6.4"')],
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
    #description="",
    #author="",
    #author_email="",
    #url="",
    install_requires=["Routes<=1.8",
                      "Pylons<=0.9.6.2",
                      "boto >= 1.9b",
                      "pytz",
                      "pycrypto",
                      "Babel>=0.9.1",
                      "flup",
                      "cython==0.12.1",
                      "simplejson", 
                      "SQLAlchemy==0.5.3",
                      "BeautifulSoup == 3.0.8.1", # last version to use the good parser
                      "cssutils==0.9.5.1",
                      "chardet",
                      "psycopg2",
                      "py_interface",
                      "pycountry",
                      "thrift" # required by Cassandra
                      ],
    packages=find_packages(),
    include_package_data=True,
    test_suite = 'nose.collector',
    package_data={'r2': ['i18n/*/LC_MESSAGES/*.mo']},
    cmdclass = {'compile_catalog':      babel.compile_catalog,
                'extract_messages':     babel.extract_messages,
                'init_catalog':         babel.init_catalog,
                'update_catalog':       babel.update_catalog,
                },
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


# the cassandra stuff we'll need. down here because it needs to be
# done *after* thrift is installed
try:
    import cassandra, pycassa
except ImportError:
    # we'll need thrift too, but that is done by install_depends below
    easy_install(['http://github.com/downloads/ieure/python-cassandra/Cassandra-0.5.0.tar.gz', # required by pycassa
                  'http://github.com/downloads/ketralnis/pycassa/pycassa-0.1.1.tar.gz',
                  ])

# running setup.py always fucks up the build directory, which we don't
# need anyway.
import shutil
shutil.rmtree("build")
