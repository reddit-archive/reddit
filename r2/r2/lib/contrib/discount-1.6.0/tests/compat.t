./echo "markdown 1.0 compatability"

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

LINKY='[this] is a test

[this]: /this'

try 'implicit reference links' "$LINKY" '<p><a href="/this">this</a> is a test</p>'
try -f1.0 'implicit reference links (-f1.0)' "$LINKY" '<p>[this] is a test</p>'

WSP=' '
WHITESPACE="
    white space$WSP
    and more"

try 'trailing whitespace' "$WHITESPACE" '<pre><code>white space ''
and more
</code></pre>'

try -f1.0 'trailing whitespace (-f1.0)' "$WHITESPACE" '<pre><code>white space''
and more
</code></pre>'

exit $rc
