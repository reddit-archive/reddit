./echo "html blocks"

rc=0
MARKDOWN_FLAGS=

try() {
    unset FLAGS
    case "$1" in
    -*) FLAGS=$1
	shift ;;
    esac
    
    ./echo -n "  $1" '..................................' | ./cols 36

    Q=`./echo "$2" | ./markdown $FLAGS`

    if [ "$3" = "$Q" ]; then
	./echo " ok"
    else
	./echo " FAILED"
	./echo "wanted: $3"
	./echo "got   : $Q"
	rc=1
    fi
}

try 'self-closing block tags (hr)' \
    '<hr>

text' \
    '<hr>


<p>text</p>'

try 'self-closing block tags (hr/)' \
    '<hr/>

text' \
    '<hr/>


<p>text</p>'

try 'self-closing block tags (br)' \
    '<br>

text' \
    '<br>


<p>text</p>'

try 'html comments' \
    '<!--
**hi**
-->' \
    '<!--
**hi**
-->'
    
try 'no smartypants inside tags (#1)' \
    '<img src="linky">' \
    '<p><img src="linky"></p>'

try 'no smartypants inside tags (#2)' \
    '<img src="linky" alt=":)" />' \
    '<p><img src="linky" alt=":)" /></p>'

try -fnohtml 'block html with -fnohtml' '<b>hi!</b>' '<p>&lt;b>hi!&lt;/b></p>'
try -fnohtml 'malformed tag injection' '<x <script>' '<p>&lt;x &lt;script></p>'
try -fhtml 'allow html with -fhtml' '<b>hi!</b>' '<p><b>hi!</b></p>'


# check that nested raw html blocks terminate properly.
#
BLOCK1SRC='Markdown works fine *here*.

*And* here.

<div><pre>
</pre></div>

Markdown here is *not* parsed by RDiscount.

Nor in *this* paragraph, and there are no paragraph breaks.'

BLOCK1OUT='<p>Markdown works fine <em>here</em>.</p>

<p><em>And</em> here.</p>

<div><pre>
</pre></div>


<p>Markdown here is <em>not</em> parsed by RDiscount.</p>

<p>Nor in <em>this</em> paragraph, and there are no paragraph breaks.</p>'

try 'nested html blocks (1)' "$BLOCK1SRC" "$BLOCK1OUT"

try 'nested html blocks (2)' \
    '<div>This is inside a html block
<div>This is, too</div>and
so is this</div>' \
    '<div>This is inside a html block
<div>This is, too</div>and
so is this</div>'

try 'unfinished tags' '<foo bar' '<p>&lt;foo bar</p>'

exit $rc
