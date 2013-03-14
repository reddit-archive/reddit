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
# All portions of the code written by reddit are Copyright (c) 2006-2013 reddit
# Inc. All Rights Reserved.
###############################################################################

import json


def get_countries_and_codes():
    """Return a dict of ISO Alpha2 country codes to country names."""

    # avoid importing this until this function is called since we're going to
    # try our best to not import this at all in the app. it takes a tonne of
    # memory!
    import pycountry

    return {x.alpha2: x.name for x in pycountry.countries}


if __name__ == "__main__":
    # Print out the country dict in JSON format for use in the Makefile.
    print json.dumps(get_countries_and_codes(), indent=2, sort_keys=True)
