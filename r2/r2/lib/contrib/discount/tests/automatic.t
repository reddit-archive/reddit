. tests/functions.sh

title "automatic links"

rc=0
MARKDOWN_FLAGS=

try 'http url' '<http://here>' '<p><a href="http://here">http://here</a></p>'
try 'ftp url' '<ftp://here>' '<p><a href="ftp://here">ftp://here</a></p>'
match '<orc@pell.portland.or.us>' '<orc@pell.portland.or.us>' '<a href='
match '<orc@pell.com.>' '<orc@pell.com.>' '<a href='
try 'invalid <orc@>' '<orc@>' '<p>&lt;orc@></p>'
try 'invalid <@pell>' '<@pell>' '<p>&lt;@pell></p>'
try 'invalid <orc@pell>' '<orc@pell>' '<p>&lt;orc@pell></p>'
try 'invalid <orc@.pell>' '<orc@.pell>' '<p>&lt;orc@.pell></p>'
try 'invalid <orc@pell.>' '<orc@pell.>' '<p>&lt;orc@pell.></p>'
match '<mailto:orc@pell>' '<mailto:orc@pell>' '<a href='
match '<mailto:orc@pell.com>' '<mailto:orc@pell.com>' '<a href='
match '<mailto:orc@>' '<mailto:orc@>' '<a href='
match '<mailto:@pell>' '<mailto:@pell>' '<a href='

summary $0
exit $rc
