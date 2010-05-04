./markdown -V | grep DIV >/dev/null || exit 0

./echo "%div% blocks"

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

try 'simple >%div% block' \
'>%this%
this this' \
'<div class="this"><p>this this</p></div>'

try 'two >%div% blocks in a row' \
'>%this%
this this

>%that%
that that' \
'<div class="this"><p>this this</p></div>

<div class="that"><p>that that</p></div>'

try '>%class:div%' \
'>%class:this%
this this' \
'<div class="this"><p>this this</p></div>'

try '>%id:div%' \
'>%id:this%
this this' \
'<div id="this"><p>this this</p></div>'

try 'nested >%div%' \
'>%this%
>>%that%
>>that

>%more%
more' \
'<div class="this"><div class="that"><p>that</p></div></div>

<div class="more"><p>more</p></div>'


exit $rc
