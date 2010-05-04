./echo "footnotes"

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

try 'a line with multiple []s' '[a][] [b][]:' '<p>[a][] [b][]:</p>'
try 'a valid footnote' \
    '[alink][]

[alink]: link_me' \
    '<p><a href="link_me">alink</a></p>'

exit $rc
