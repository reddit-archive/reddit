./echo "code blocks"

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

try 'format for code block html' \
'    this is
    code' \
    '<pre><code>this is
code
</code></pre>'

try 'unclosed single backtick' '`hi there' '<p>`hi there</p>'
try 'unclosed double backtick' '``hi there' '<p>``hi there</p>'
try 'remove space around code' '`` hi there ``' '<p><code>hi there</code></p>'

exit $rc
