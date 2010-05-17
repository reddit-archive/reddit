. tests/functions.sh

title "table-of-contents support"

rc=0
MARKDOWN_FLAGS=

try '-T -ftoc' 'table of contents' \
'#H1
hi' \
'
 <ul>
 <li><a href="#H1">H1</a> </li>
 </ul>
<h1 id="H1">H1</h1>

<p>hi</p>'
  

summary $0
exit $rc
