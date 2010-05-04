./echo "embedded links"

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

try 'url contains &' '[hehehe](u&rl)' '<p><a href="u&amp;rl">hehehe</a></p>'
try 'url contains +' '[hehehe](u+rl)' '<p><a href="u+rl">hehehe</a></p>'
try 'url contains "' '[hehehe](u"rl)' '<p><a href="u%22rl">hehehe</a></p>'
try 'url contains <' '[hehehe](u<rl)' '<p><a href="u&lt;rl">hehehe</a></p>'
try 'url contains whitespace' '[ha](r u)' '<p><a href="r%20u">ha</a></p>'

try 'url contains whitespace & title' \
    '[hehehe](r u "there")' \
    '<p><a href="r%20u" title="there">hehehe</a></p>'

try 'url contains escaped )' \
    '[hehehe](u\))' \
    '<p><a href="u)">hehehe</a></p>'

try 'image label contains <' \
    '![he<he<he](url)' \
    '<p><img src="url" alt="he&lt;he&lt;he" /></p>'

try 'image label contains >' \
    '![he>he>he](url)' \
    '<p><img src="url" alt="he&gt;he&gt;he" /></p>'

try 'sloppy context link' \
    '[heh]( url "how about it?" )' \
    '<p><a href="url" title="how about it?">heh</a></p>'

try 'footnote urls formed properly' \
    '[hehehe]: hohoho "ha ha"

[hehehe][]' \
    '<p><a href="hohoho" title="ha ha">hehehe</a></p>'

try 'linky-like []s work' \
    '[foo]' \
    '<p>[foo]</p>'

try 'pseudo-protocol "id:"'\
    '[foo](id:bar)' \
    '<p><a id="bar">foo</a></p>'

try 'pseudo-protocol "class:"' \
    '[foo](class:bar)' \
    '<p><span class="bar">foo</span></p>'

try 'pseudo-protocol "abbr:"'\
    '[foo](abbr:bar)' \
    '<p><abbr title="bar">foo</abbr></p>'

try 'nested [][]s' \
    '[[z](y)](x)' \
    '<p><a href="x">[z](y)</a></p>'

try 'empty [][] tags' \
    '[![][1]][2]

[1]: image1
[2]: image2' \
    '<p><a href="image2"><img src="image1" alt="" /></a></p>'

try 'footnote cuddled up to text' \
'foo
[bar]:bar' \
    '<p>foo</p>'

try 'mid-paragraph footnote' \
'talk talk talk talk
[bar]: bar
talk talk talk talk' \
'<p>talk talk talk talk
talk talk talk talk</p>'

try 'mid-blockquote footnote' \
'>blockquote!
[footnote]: here!
>blockquote!' \
'<blockquote><p>blockquote!
blockquote!</p></blockquote>'

try 'end-blockquote footnote' \
'>blockquote!
>blockquote!
[footnote]: here!' \
'<blockquote><p>blockquote!
blockquote!</p></blockquote>'

try 'start-blockquote footnote' \
'[footnote]: here!
>blockquote!
>blockquote!' \
'<blockquote><p>blockquote!
blockquote!</p></blockquote>'

try '[text] (text) not a link' \
'[test] (me)' \
'<p>[test] (me)</p>'

exit $rc
