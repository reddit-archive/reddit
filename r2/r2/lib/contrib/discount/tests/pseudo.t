. tests/functions.sh

title "pseudo-protocols"

rc=0
MARKDOWN_FLAGS=

try '[](id:) links' '[foo](id:bar)' '<p><a id="bar">foo</a></p>'
try -fnoext  '[](id:) links with -fnoext' '[foo](id:bar)' '<p>[foo](id:bar)</p>'
try '[](class:) links' '[foo](class:bar)' '<p><span class="bar">foo</span></p>'
try -fnoext '[](class:) links with -fnoext' '[foo](class:bar)' '<p>[foo](class:bar)</p>'
try '[](lang:) links' '[foo](lang:en)' '<p><span lang="en">foo</span></p>'
try -fnoext '[](lang:) links with -fnoext' '[foo](lang:en)' '<p>[foo](lang:en)</p>'
try '[](raw:) links' '[foo](raw:bar)' '<p>bar</p>'
try -fnoext '[](raw:) links with -fnoext' '[foo](raw:bar)' '<p>[foo](raw:bar)</p>'

summary $0
exit $rc
