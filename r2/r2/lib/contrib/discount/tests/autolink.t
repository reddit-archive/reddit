. tests/functions.sh

title 'Reddit-style automatic links'
rc=0

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

summary $0
exit $rc
