./echo "misc"

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

try 'single paragraph' 'AAA' '<p>AAA</p>'
try '< -> &lt;' '<' '<p>&lt;</p>'
try '`>` -> <code>&gt;</code>' '`>`' '<p><code>&gt;</code></p>'
try '`` ` `` -> <code>`</code>' '`` ` ``' '<p><code>`</code></p>'

exit $rc
