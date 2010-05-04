./echo "xml output with MKD_CDATA"

rc=0
MARKDOWN_FLAGS=

try() {
    unset FLAGS
    case "$1" in
    -*) FLAGS=$1
	shift ;;
    esac
    
    ./echo -n "  $1" '..................................' | ./cols 36

    case "$2" in
    -t*) Q=`./markdown $FLAGS "$2"` ;;
    *)   Q=`./echo "$2" | ./markdown $FLAGS` ;;
    esac

    if [ "$3" = "$Q" ]; then
	./echo " ok"
    else
	./echo " FAILED"
	./echo "wanted: $3"
	./echo "got   : $Q"
	rc=1
    fi
}

try -fcdata 'xml output from markdown()' 'hello,sailor' '&lt;p&gt;hello,sailor&lt;/p&gt;'
try -fcdata 'from mkd_generateline()' -t'"hello,sailor"' '&amp;ldquo;hello,sailor&amp;rdquo;'
try -fnocdata 'html output from markdown()' '"hello,sailor"' '<p>&ldquo;hello,sailor&rdquo;</p>'
try -fnocdata '... from mkd_generateline()' -t'"hello,sailor"' '&ldquo;hello,sailor&rdquo;'

try -fcdata 'xml output with multibyte utf-8' \
    'tecnología y servicios más confiables' \
    '&lt;p&gt;tecnología y servicios más confiables&lt;/p&gt;'

exit $rc
