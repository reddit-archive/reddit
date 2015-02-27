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
# All portions of the code written by reddit are Copyright (c) 2006-2015 reddit
# Inc. All Rights Reserved.
###############################################################################

import os
import fnmatch
import sys


try:
    import pkg_resources
except ImportError:
    print "Distribute >= 0.6.16 is required to run this."
    sys.exit(1)
else:
    pkg_resources.require("distribute>=0.6.16")


from setuptools import setup, find_packages, Extension


commands = {}


try:
    from Cython.Build import cythonize
except ImportError:
    print "Cannot find Cython. Skipping Cython build."
    pyx_extensions = []
else:
    pyx_files = []
    for root, directories, files in os.walk('.'):
        for f in fnmatch.filter(files, '*.pyx'):
            pyx_files.append(os.path.join(root, f))
    pyx_extensions = cythonize(pyx_files)


setup(
    name="r2",
    version="",
    install_requires=[
        "webob==1.0.8",
        "webtest<=1.4.3",  # anything newer requires WebOb>=1.2.0
        "Pylons==0.9.7",
        "Routes==1.11",
        "mako>=0.5",
        "boto >= 2.0",
        "pytz",
        "pycrypto",
        "Babel>=1.0",
        "cython>=0.14",
        "SQLAlchemy==0.7.4",
        "BeautifulSoup",
        "chardet",
        "psycopg2",
        "pycassa>=1.7.0",
        "PIL",
        "pycaptcha",
        "amqplib",
        "pylibmc>=1.2.1",
        "py-bcrypt",
        "snudown>=1.1.0",
        "l2cs>=2.0.2",
        "lxml",
        "kazoo",
        "stripe",
        "requests<1.0.0",
        "tinycss2",
        "unidecode",
        "PyYAML",
    ],
    # Extra dependencies that aren't needed for running the app.
    # * https://pythonhosted.org/setuptools/setuptools.html#declaring-extras-optional-features-with-their-own-dependencies
    # * https://github.com/pypa/sampleproject/blob/300f04dc44df51492deb859ac98ba521d2c7a17a/setup.py#L71-L77
    extras_require = {
        'test': ['mock'],
    },
    dependency_links=[
        "https://github.com/reddit/snudown/archive/v1.1.3.tar.gz#egg=snudown-1.1.3",
        "https://s3.amazonaws.com/code.reddit.com/pycaptcha-0.4.tar.gz#egg=pycaptcha-0.4",
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
    [paste.paster_command]
    run = r2.commands:RunCommand
    shell = pylons.commands:ShellCommand
    [paste.filter_app_factory]
    gzip = r2.lib.gzipper:make_gzip_middleware
    [r2.provider.media]
    s3 = r2.lib.providers.media.s3:S3MediaProvider
    filesystem = r2.lib.providers.media.filesystem:FileSystemMediaProvider
    [r2.provider.cdn]
    cloudflare = r2.lib.providers.cdn.cloudflare:CloudFlareCdnProvider
    null = r2.lib.providers.cdn.null:NullCdnProvider
    [r2.provider.auth]
    cookie = r2.lib.providers.auth.cookie:CookieAuthenticationProvider
    http = r2.lib.providers.auth.http:HttpAuthenticationProvider
    [r2.provider.support]
    zendesk = r2.lib.providers.support.zendesk:ZenDeskProvider
    [r2.provider.search]
    cloudsearch = r2.lib.providers.search.cloudsearch:CloudSearchProvider
    solr = r2.lib.providers.search.solr:SolrSearchProvider
    [r2.provider.image_resizing]
    imgix = r2.lib.providers.image_resizing.imgix:ImgixImageResizingProvider
    no_op = r2.lib.providers.image_resizing.no_op:NoOpImageResizingProvider
    unsplashit = r2.lib.providers.image_resizing.unsplashit:UnsplashitImageResizingProvider
    """,
)
