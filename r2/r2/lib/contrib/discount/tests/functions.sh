__tests=0
__passed=0
__failed=0
__title=

title() {
    __title="$*"
    if [ "$VERBOSE" ]; then
	./echo "$__title"
    else
	./echo -n "$__title" \
'.................................................................' | ./cols 54
    fi
}


summary() {
    if [ -z "$VERBOSE" ]; then
	if [ $__failed -eq 0 ]; then
	    ./echo " OK"
	else
	    ./echo
	    ./echo "$1: $__tests tests; $__failed failed/$__passed passed"
	    ./echo
	fi
    fi
}


try() {
    unset FLAGS
    case "$1" in
    -*) FLAGS=$1
	shift ;;
    esac

    testcase=`./echo -n "  $1" '..................................' | ./cols 36`
    __tests=`expr $__tests + 1`


    test "$VERBOSE" && ./echo -n "$testcase"

    case "$2" in
    -t*) Q=`./markdown $FLAGS "$2"` ;;
    *)   Q=`./echo "$2" | ./markdown $FLAGS` ;;
    esac

    if [ "$3" = "$Q" ]; then
	__passed=`expr $__passed + 1`
	test $VERBOSE && ./echo " ok"
    else
	__failed=`expr $__failed + 1`
	if [ -z  "$VERBOSE" ]; then
	    ./echo
	    ./echo "$1"
	fi
	./echo "wanted: $3"
	./echo "got   : $Q"
	rc=1
    fi
}

match() {
    testcase=`./echo -n "  $1" '..................................' | ./cols 36`

    test $VERBOSE && ./echo -n "$testcase"

    if ./echo "$2" | ./markdown | grep "$3" >/dev/null; then
	test $VERBOSE && ./echo " ok"
    else
	if [ -z "$VERBOSE" ]; then
	    ./echo
	    ./echo "$testcase"
	fi
	rc=1
    fi
}
