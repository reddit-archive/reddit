. tests/functions.sh

title "callbacks"

rc=0
MARKDOWN_FLAGS=

try -bZZZ 'url modification' \
'[a](/b)' \
'<p><a href="ZZZ/b">a</a></p>'

try -EZZZ 'additional flags' \
'[a](/b)' \
'<p><a href="/b" ZZZ>a</a></p>'

summary $0
exit $rc
