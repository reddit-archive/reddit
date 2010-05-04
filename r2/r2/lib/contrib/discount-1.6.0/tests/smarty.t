./echo "smarty pants"

rc=0
MARKDOWN_FLAGS=0x0; export MARKDOWN_FLAGS

try() {
    unset FLAGS
    case "$1" in
    -*) FLAGS="$1"
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


try '(c) -> &copy;' '(c)' '<p>&copy;</p>'
try '(r) -> &reg;' '(r)' '<p>&reg;</p>'
try '(tm) -> &trade;' '(tm)' '<p>&trade;</p>'
try '... -> &hellip;' '...' '<p>&hellip;</p>'

try '"--" -> &mdash;' '--' '<p>&mdash;</p>'

try '"-" -> &ndash;' 'regular -' '<p>regular &ndash;</p>'
try 'A-B -> A-B' 'A-B' '<p>A-B</p>'
try '"fancy" -> &ldquo;fancy&rdquo;' '"fancy"' '<p>&ldquo;fancy&rdquo;</p>'
try "'fancy'" "'fancy'" '<p>&lsquo;fancy&rsquo;</p>'
try "don<b>'t -> don<b>&rsquo;t" "don<b>'t" '<p>don<b>&rsquo;t</p>'
try "don't -> don&rsquo;t" "don't" '<p>don&rsquo;t</p>'
try "it's -> it&rsquo;s" "it's" '<p>it&rsquo;s</p>'

if ./markdown -V | grep SUPERSCRIPT >/dev/null; then
    try -frelax  'A^B -> A<sup>B</sup> (-frelax)' 'A^B' '<p>A<sup>B</sup></p>'
    try -fstrict 'A^B != A<sup>B</sup> (-fstrict)' 'A^B' '<p>A^B</p>'
    try -frelax 'A^B in link title' '[link](here "A^B")' '<p><a href="here" title="A^B">link</a></p>'
fi

exit $rc
