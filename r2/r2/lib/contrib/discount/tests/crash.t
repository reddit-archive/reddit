. tests/functions.sh

title "crashes"

rc=0
MARKDOWN_FLAGS=

try 'zero-length input' '' ''

try 'hanging quote in list' \
' * > this should not die

no.' \
'<ul>
<li><blockquote><p>this should not die</p></blockquote></li>
</ul>


<p>no.</p>'

try 'dangling list item' ' - ' \
'<ul>
<li></li>
</ul>'

try -bHOHO 'empty []() with baseurl' '[]()' '<p><a href=""></a></p>'
try 'unclosed html block' '<table></table' '<table></table'

summary $0
exit $rc
