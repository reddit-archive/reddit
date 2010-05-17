. tests/functions.sh
title "lists"

rc=0
MARKDOWN_FLAGS=

try 'two separated items' \
    ' * A

* B' \
    '<ul>
<li><p>A</p></li>
<li><p>B</p></li>
</ul>'

try 'two adjacent items' \
    ' * A
 * B' \
    '<ul>
<li>A</li>
<li>B</li>
</ul>'


try 'two adjacent items, then space' \
    ' * A
* B

space, the final frontier' \
    '<ul>
<li>A</li>
<li>B</li>
</ul>


<p>space, the final frontier</p>'

try 'nested lists (1)' \
    ' *   1. Sub (list)
     2. Two (items)
     3. Here' \
    '<ul>
<li><ol>
<li>Sub (list)</li>
<li>Two (items)</li>
<li>Here</li>
</ol>
</li>
</ul>'

try 'nested lists (2)' \
    ' * A (list)

     1. Sub (list)
     2. Two (items)
     3. Here

     Here
 * B (list)' \
    '<ul>
<li><p>A (list)</p>

<ol>
<li>Sub (list)</li>
<li>Two (items)</li>
<li>Here</li>
</ol>


<p>  Here</p></li>
<li>B (list)</li>
</ul>'

try 'list inside blockquote' \
    '>A (list)
>
>1. Sub (list)
>2. Two (items)
>3. Here' \
    '<blockquote><p>A (list)</p>

<ol>
<li>Sub (list)</li>
<li>Two (items)</li>
<li>Here</li>
</ol>
</blockquote>'
    
try 'blockquote inside list' \
    ' *  A (list)
   
    > quote
    > me

    dont quote me' \
    '<ul>
<li><p>A (list)</p>

<blockquote><p>quote
me</p></blockquote>

<p>dont quote me</p></li>
</ul>'

try 'empty list' \
'
- 

- 
' \
'<ul>
<li></li>
<li></li>
</ul>'


try 'blockquote inside a list' \
'   * This is a list item.

      > This is a quote insde a list item. ' \
'<ul>
<li><p> This is a list item.</p>

<blockquote><p>This is a quote insde a list item.</p></blockquote></li>
</ul>'

if ./markdown -V | grep DL_TAG >/dev/null; then

    try 'dl followed by non-dl' \
    '=a=
    test
2. here' \
'<dl>
<dt>a</dt>
<dd>test</dd>
</dl>

<ol>
<li>here</li>
</ol>'

    try 'non-dl followed by dl' \
    '1. hello
=sailor=
    hi!' \
'<ol>
<li>hello</li>
</ol>


<dl>
<dt>sailor</dt>
<dd>hi!</dd>
</dl>'

fi

summary $0
exit $rc
