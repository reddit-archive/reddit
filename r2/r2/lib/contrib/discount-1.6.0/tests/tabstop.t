rc=0
unset MARKDOWN_FLAGS
unset MKD_TABSTOP

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

eval `./markdown -V | tr ' ' '\n' | grep TAB`

if [ "${TAB:-4}" -eq 8 ]; then
    ./echo "dealing with tabstop derangement"

    LIST='
 *  A
     *  B
	 *  C'

    try 'markdown with TAB=8' \
	"$LIST" \
	'<ul>
<li>A

<ul>
<li>B

<ul>
<li>C</li>
</ul>
</li>
</ul>
</li>
</ul>'

    try -F0x0200 'markdown with TAB=4' \
	"$LIST" \
	'<ul>
<li>A

<ul>
<li>B</li>
<li>C</li>
</ul>
</li>
</ul>'

fi

exit $rc
