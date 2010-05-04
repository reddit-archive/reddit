./echo "deeply nested lists"

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

LIST='
 *  top-level list ( list 1)
     +  second-level list (list 2)
        * first item third-level list (list 3)
     +  * second item, third-level list, first item. (list 4)
        * second item, third-level list, second item.
 *  top-level list again.'

RSLT='<ul>
<li>top-level list ( list 1)

<ul>
<li>second-level list (list 2)

<ul>
<li>first item third-level list (list 3)</li>
</ul>
</li>
<li><ul>
<li>second item, third-level list, first item. (list 4)</li>
<li>second item, third-level list, second item.</li>
</ul>
</li>
</ul>
</li>
<li>top-level list again.</li>
</ul>'

try 'thrice-nested lists' "$LIST" "$RSLT"

exit $rc
