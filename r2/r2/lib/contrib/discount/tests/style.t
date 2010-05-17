. tests/functions.sh

title "styles"

rc=0
MARKDOWN_FLAGS=

try '<style blocks -- one line' '<style> ul {display:none;} </style>' ''

ASK='<style>
ul {display:none;}
</style>'

try '<style> blocks -- multiline' "$ASK" ''

summary $0
exit $rc
