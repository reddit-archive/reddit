. tests/functions.sh

title "strikethrough"

rc=0
MARKDOWN_FLAGS=

try 'strikethrough' '~~deleted~~' '<p><del>deleted</del></p>'
try -fnodel '... with -fnodel' '~~deleted~~' '<p>~~deleted~~</p>'
try 'mismatched tildes' '~~~tick~~' '<p><del>~tick</del></p>'
try 'mismatched tildes(2)' '~~tick~~~' '<p>~~tick~~~</p>'
try 'single tildes' '~tick~' '<p>~tick~</p>'

summary $0
exit $rc
