./echo "pseudo-protocols"

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

try '[](id:) links' '[foo](id:bar)' '<p><a id="bar">foo</a></p>'
try -fnoext  '[](id:) links with -fnoext' '[foo](id:bar)' '<p>[foo](id:bar)</p>'
try '[](class:) links' '[foo](class:bar)' '<p><span class="bar">foo</span></p>'
try -fnoext '[](class:) links with -fnoext' '[foo](class:bar)' '<p>[foo](class:bar)</p>'
try '[](raw:) links' '[foo](raw:bar)' '<p>bar</p>'
try -fnoext '[](raw:) links with -fnoext' '[foo](raw:bar)' '<p>[foo](raw:bar)</p>'

exit $rc
