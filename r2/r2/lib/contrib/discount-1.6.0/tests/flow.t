./echo "paragraph flow"

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

try 'header followed by paragraph' \
    '###Hello, sailor###
And how are you today?' \
    '<h3>Hello, sailor</h3>

<p>And how are you today?</p>'

try 'two lists punctuated with a HR' \
    '* A
* * *
* B
* C' \
    '<ul>
<li>A</li>
</ul>


<hr />

<ul>
<li>B</li>
<li>C</li>
</ul>'

exit $rc
