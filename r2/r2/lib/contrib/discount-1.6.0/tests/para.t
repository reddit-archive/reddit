./echo "paragraph blocking"

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

try 'paragraph followed by code' \
    'a
    b' \
    '<p>a</p>

<pre><code>b
</code></pre>'

try 'single-line paragraph' 'a' '<p>a</p>'

exit $rc
