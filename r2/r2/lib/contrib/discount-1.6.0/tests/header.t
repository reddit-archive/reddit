./echo "headers"

rc=0
MARKDOWN_FLAGS=

try() {
    unset FLAGS
    case "$1" in
    -*) FLAGS=$1
	shift ;;
    esac
    
    S=`./echo -n "$1" '..................................' | ./cols 34`
    ./echo -n "  $S "

    Q=`./echo "$2" | ./markdown $FLAGS`


    if [ "$3" = "$Q" ]; then
	./echo "ok"
    else
	./echo "FAILED"
	./echo "wanted: $3"
	./echo "got   : $Q"
	rc=1
    fi
}

try 'single #' '#' '<p>#</p>'
try 'empty ETX' '##' '<h1>#</h1>'
try 'single-char ETX (##W)' '##W' '<h2>W</h2>'
try 'single-char ETX (##W )' '##W  ' '<h2>W</h2>'
try 'single-char ETX (## W)' '## W' '<h2>W</h2>'
try 'single-char ETX (## W )' '## W ' '<h2>W</h2>'
try 'single-char ETX (##W##)' '##W##' '<h2>W</h2>'
try 'single-char ETX (##W ##)' '##W ##' '<h2>W</h2>'
try 'single-char ETX (## W##)' '## W##' '<h2>W</h2>'
try 'single-char ETX (## W ##)' '## W ##' '<h2>W</h2>'

try 'multiple-char ETX (##Hello##)' '##Hello##' '<h2>Hello</h2>'

try 'SETEXT with trailing whitespace' \
'hello
=====  ' '<h1>hello</h1>'

exit $rc
