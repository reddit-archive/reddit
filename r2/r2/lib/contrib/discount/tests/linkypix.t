. tests/functions.sh

title "embedded images"

rc=0
MARKDOWN_FLAGS=

try 'image with size extension' \
    '![picture](pic =200x200)' \
    '<p><img src="pic" height="200" width="200" alt="picture" /></p>'

try 'image with height' \
    '![picture](pic =x200)' \
    '<p><img src="pic" height="200" alt="picture" /></p>'

try 'image with width' \
    '![picture](pic =200x)' \
    '<p><img src="pic" width="200" alt="picture" /></p>'

summary $0
exit $rc
