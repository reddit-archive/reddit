. tests/functions.sh

title "paranoia"

rc=0
MARKDOWN_FLAGS=

try -fsafelink 'bogus url (-fsafelink)' '[test](bad:protocol)' '<p>[test](bad:protocol)</p>'
try -fnosafelink 'bogus url (-fnosafelink)' '[test](bad:protocol)' '<p><a href="bad:protocol">test</a></p>'

summary $0
exit $rc
