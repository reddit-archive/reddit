. tests/functions.sh

title "markdown 1.0 compatability"

rc=0
MARKDOWN_FLAGS=

LINKY='[this] is a test

[this]: /this'

try 'implicit reference links' "$LINKY" '<p><a href="/this">this</a> is a test</p>'
try -f1.0 'implicit reference links (-f1.0)' "$LINKY" '<p>[this] is a test</p>'

WSP=' '
WHITESPACE="
    white space$WSP
    and more"

try 'trailing whitespace' "$WHITESPACE" '<pre><code>white space ''
and more
</code></pre>'

try -f1.0 'trailing whitespace (-f1.0)' "$WHITESPACE" '<pre><code>white space''
and more
</code></pre>'

summary $0
exit $rc
