. tests/functions.sh

title "footnotes inside reparse sections"

rc=0

try 'footnote inside [] section' \
    '[![foo][]](bar)

[foo]: bar2' \
    '<p><a href="bar"><img src="bar2" alt="foo" /></a></p>'

summary $0
exit $rc
