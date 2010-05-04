./echo "crashes"

rc=0
MARKDOWN_FLAGS=

./echo -n '  zero-length input ................ '

if ./markdown < /dev/null >/dev/null; then
    ./echo "ok"
else
    ./echo "FAILED"
    rc=1
fi

./echo -n '  hanging quote in list ............ '

./markdown >/dev/null 2>/dev/null << EOF
 * > this should not die

no.
EOF

if [ "$?" -eq 0 ]; then
    ./echo "ok"
else
    ./echo "FAILED"
    rc=1
fi

./echo -n '  dangling list item ............... '

if ./echo ' - ' | ./markdown >/dev/null 2>/dev/null; then
    ./echo "ok"
else
    ./echo "FAILED"
    rc=1
fi

./echo -n '  empty []() with baseurl .......... '

if ./markdown -bHOHO -s '[]()' >/dev/null 2>/dev/null; then
    ./echo "ok"
else
    ./echo "FAILED"
    rc=1
fi

./echo -n '  unclosed html block .............. '

if ./echo '<table></table' | ./markdown >/dev/null 2>/dev/null; then
    ./echo 'ok'
else
    ./echo "FAILED"
    rc=1
fi

exit $rc
