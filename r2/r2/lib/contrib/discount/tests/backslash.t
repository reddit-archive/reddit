. tests/functions.sh

title "backslash escapes"

rc=0
MARKDOWN_FLAGS=

try 'backslashes in []()' '[foo](http://\this\is\.a\test\(here\))' \
'<p><a href="http://\this\is.a\test(here)">foo</a></p>'

try -fautolink 'autolink url with trailing \' \
    'http://a.com/\' \
    '<p><a href="http://a.com/\">http://a.com/\</a></p>'

summary $0
exit $rc
