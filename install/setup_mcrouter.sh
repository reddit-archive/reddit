#!/bin/bash
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

###############################################################################
# Configure mcrouter
###############################################################################
if [ ! -d /etc/mcrouter ]; then
    mkdir -p /etc/mcrouter
fi

if [ ! -f /etc/mcrouter/global.conf ]; then
    cat > /etc/mcrouter/global.conf <<MCROUTER
{
  // route all valid prefixes to the local memcached
  "pools": {
    "local": {
      "servers": [
        "127.0.0.1:11211",
      ],
      "protocol": "ascii",
      "keep_routing_prefix": false,
    },
  },
  "route": {
    "type": "PrefixSelectorRoute",
    "policies": {
      "rend:": {
        "type": "PoolRoute",
        "pool": "local",
      },
      "page:": {
        "type": "PoolRoute",
        "pool": "local",
      },
      "pane:": {
        "type": "PoolRoute",
        "pool": "local",
      },
      "sr:": {
        "type": "PoolRoute",
        "pool": "local",
      },
      "account:": {
        "type": "PoolRoute",
        "pool": "local",
      },
      "link:": {
        "type": "PoolRoute",
        "pool": "local",
      },
      "comment:": {
        "type": "PoolRoute",
        "pool": "local",
      },
      "message:": {
        "type": "PoolRoute",
        "pool": "local",
      },
      "campaign:": {
        "type": "PoolRoute",
        "pool": "local",
      },
    },
    "wildcard": {
      "type": "PoolRoute",
      "pool": "local",
    },
  },
}
MCROUTER
fi
