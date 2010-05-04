./echo "paranoia"

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

try -fsafelink 'bogus url (-fsafelink)' '[test](bad:protocol)' '<p>[test](bad:protocol)</p>'
try -fnosafelink 'bogus url (-fnosafelink)' '[test](bad:protocol)' '<p><a href="bad:protocol">test</a></p>'

exit $rc
