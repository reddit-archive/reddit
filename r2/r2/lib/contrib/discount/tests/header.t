. tests/functions.sh

title "headers"

rc=0
MARKDOWN_FLAGS=

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

summary $0
exit $rc
