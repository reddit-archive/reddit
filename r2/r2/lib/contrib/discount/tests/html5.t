. tests/functions.sh

title "html5 blocks (mkd_with_html5_tags)"

rc=0
MARKDOWN_FLAGS=

try -5 'html5 block elements enabled' \
       '<aside>html5 does not suck</aside>' \
       '<aside>html5 does not suck</aside>'

try    'html5 block elements disabled' \
       '<aside>html5 sucks</aside>' \
       '<p><aside>html5 sucks</aside></p>'

summary $0
exit $rc
