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

try 'nested lists and a header' \
    '- A list item
That goes over multiple lines

     and paragraphs

- Another list item

    + with a
    + sublist

## AND THEN A HEADER' \
'<ul>
<li><p>A list item
That goes over multiple lines</p>

<p>   and paragraphs</p></li>
<li><p>Another list item</p>

<ul>
<li>with a</li>
<li>sublist</li>
</ul>
</li>
</ul>


<h2>AND THEN A HEADER</h2>'

try 'forcing a <br/>' 'this  
is' '<p>this<br/>
is</p>'

try 'trimming single spaces' 'this ' '<p>this</p>'
try -fnohtml 'markdown <br/> with -fnohtml' 'foo  
is'  '<p>foo<br/>
is</p>'

summary $0
exit $rc
