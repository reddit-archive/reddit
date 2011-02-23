. tests/functions.sh

title "code blocks"

rc=0
MARKDOWN_FLAGS=

try 'format for code block html' \
'    this is
    code' \
    '<pre><code>this is
code
</code></pre>'

try 'mismatched backticks' '```tick``' '<p><code>`tick</code></p>'
try 'mismatched backticks(2)' '``tick```' '<p>``tick```</p>'
try 'unclosed single backtick' '`hi there' '<p>`hi there</p>'
try 'unclosed double backtick' '``hi there' '<p>``hi there</p>'
try 'triple backticks' '```hi there```' '<p><code>hi there</code></p>'
try 'quadruple backticks' '````hi there````' '<p><code>hi there</code></p>'
try 'remove space around code' '`` hi there ``' '<p><code>hi there</code></p>'
try 'code containing backticks' '`` a```b ``' '<p><code>a```b</code></p>'
try 'backslash before backtick' '`a\`' '<p><code>a\</code></p>'
try '`>`' '`>`' '<p><code>&gt;</code></p>'
try '`` ` ``' '`` ` ``' '<p><code>`</code></p>'
try '````` ``` `' '````` ``` `' '<p><code>``</code> `</p>'
try '````` ` ```' '````` ` ```' '<p><code>`` `</code></p>'
try 'backslashes in code(1)' '    printf "%s: \n", $1;' \
'<pre><code>printf "%s: \n", $1;
</code></pre>'
try 'backslashes in code(2)' '`printf "%s: \n", $1;`' \
'<p><code>printf "%s: \n", $1;</code></p>'

summary $0
exit $rc
