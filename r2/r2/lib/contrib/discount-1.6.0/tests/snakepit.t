./echo "The snakepit of Markdown.pl compatability"

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

try '[](single quote) text (quote)' \
    "[foo](http://Poe's law) will make this fail ('no, it won't!') here."\
    '<p><a href="http://Poe" title="s law) will make this fail ('"'no, it won't!"'">foo</a> here.</p>'

try '[](unclosed <url)' '[foo](<http://no trailing gt)' \
			'<p><a href="http://no%20trailing%20gt">foo</a></p>'

try '<unfinished <tags> (1)' \
'<foo [bar](foo)  <s>hi</s>' \
'<p><foo [bar](foo)  <s>hi</s></p>'
    
try '<unfinished &<tags> (2)' \
'<foo [bar](foo)  &<s>hi</s>' \
'<p><foo [bar](foo)  &<s>hi</s></p>'

try 'paragraph <br/> oddity' 'EOF  ' '<p>EOF</p>'
    
exit $rc
