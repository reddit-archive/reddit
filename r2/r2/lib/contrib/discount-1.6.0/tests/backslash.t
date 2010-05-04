./echo "backslash escapes"

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
	./echo "got:    $Q"
	rc=1
    fi
}

try 'backslashes in []()' '[foo](http://\this\is\.a\test\(here\))' \
'<p><a href="http://\this\is.a\test(here)">foo</a></p>'

try -fautolink 'autolink url with trailing \' \
    'http://a.com/\' \
    '<p><a href="http://a.com/\">http://a.com/\</a></p>'


exit $rc
