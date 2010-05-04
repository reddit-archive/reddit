./echo "styles"

rc=0
MARKDOWN_FLAGS=

./echo -n '  <style> blocks -- one line ....... '

count=`./echo '<style> ul {display:none;} </style>' | ./markdown|wc -c`

if [ $count -eq 1 ]; then
    ./echo "ok"
else
    ./echo "FAILED"
    rc=1
fi

./echo -n '  <style> blocks -- multiline ...... '

ASK='<style>
ul {display:none;}
</style>'

count=`./echo "$ASK" | ./markdown | wc -c`

if [ $count -eq 1 ]; then
    ./echo "ok"
else
    ./echo "FAILED"
    rc=1
fi

exit $rc
