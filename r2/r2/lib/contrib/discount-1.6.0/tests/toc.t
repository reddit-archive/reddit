./echo "table-of-contents support"

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


try '-T -ftoc' 'table of contents' \
'#H1
hi' \
'
 <ul>
 <li><a href="#H1">H1</a> </li>
 </ul>
<h1 id="H1">H1</h1>

<p>hi</p>'
  

exit $rc
