./echo "footnotes inside reparse sections"

rc=0

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


try 'footnote inside [] section' \
    '[![foo][]](bar)

[foo]: bar2' \
    '<p><a href="bar"><img src="bar2" alt="foo" /></a></p>'

exit $rc
