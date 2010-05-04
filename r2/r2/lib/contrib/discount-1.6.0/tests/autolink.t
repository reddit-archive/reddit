./echo 'Reddit-style automatic links'
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

try -fautolink 'single link' \
    'http://www.pell.portland.or.us/~orc/Code/discount' \
    '<p><a href="http://www.pell.portland.or.us/~orc/Code/discount">http://www.pell.portland.or.us/~orc/Code/discount</a></p>'

try -fautolink '[!](http://a.com "http://b.com")' \
    '[!](http://a.com "http://b.com")' \
    '<p><a href="http://a.com" title="http://b.com">!</a></p>'

try -fautolink 'link surrounded by text' \
    'here http://it is?' \
    '<p>here <a href="http://it">http://it</a> is?</p>'

try -fautolink 'naked @' '@' '<p>@</p>'

try -fautolink 'parenthesised (url)' \
    '(http://here)' \
    '<p>(<a href="http://here">http://here</a>)</p>'

try -fautolink 'token with trailing @' 'orc@' '<p>orc@</p>'

exit $rc
