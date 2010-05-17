. tests/functions.sh

title "markup peculiarities"

rc=0
MARKDOWN_FLAGS=

try 'list followed by header .......... ' \
    "
- AAA
- BBB
-" \
    '<ul>
<li>AAA

<h2>&ndash; BBB</h2></li>
</ul>'

try 'ul with mixed item prefixes' \
    '
-  A
1. B' \
    '<ul>
<li>A</li>
<li>B</li>
</ul>'

try 'ol with mixed item prefixes' \
    '
1. A
-  B
' \
    '<ol>
<li>A</li>
<li>B</li>
</ol>'

try 'forcing a <br/>' 'this  
is' '<p>this<br/>
is</p>'

try 'trimming single spaces' 'this ' '<p>this</p>'
try -fnohtml 'markdown <br/> with -fnohtml' 'foo  
is'  '<p>foo<br/>
is</p>'

summary $0
exit $rc
