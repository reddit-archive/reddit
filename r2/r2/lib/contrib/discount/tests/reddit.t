. tests/functions.sh

title "bugs & misfeatures found during the Reddit rollout"

rc=0
MARKDOWN_FLAGS=

try 'smiley faces?' '[8-9] <]:-( x ---> [4]' \
		    '<p>[8-9] &lt;]:&ndash;( x &mdash;&ndash;> [4]</p>'

try 'really long ETX headers' \
    '#####################################################hi' \
    '<h6>###############################################hi</h6>'

try 'unescaping "  " inside `code`' \
'`foo  
bar`' \
'<p><code>foo  
bar</code></p>'

try 'unescaping "  " inside []()' \
'[foo](bar  
bar)' \
'<p><a href="bar  %0Abar">foo</a></p>'

summary $0
exit $rc
