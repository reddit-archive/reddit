. tests/functions.sh

title "The snakepit of Markdown.pl compatability"

rc=0
MARKDOWN_FLAGS=

try '[](single quote) text (quote)' \
    "[foo](http://Poe's law) will make this fail ('no, it won't!') here."\
    '<p><a href="http://Poe" title="s law) will make this fail ('"'no, it won't!"'">foo</a> here.</p>'

try '[](unclosed <url)' '[foo](<http://no trailing gt)' \
			'<p><a href="http://no%20trailing%20gt">foo</a></p>'

try '<unfinished <tags> (1)' \
'<foo [bar](foo)  <s>hi</s>' \
'<p><foo [bar](foo)  <s>hi</s></p>'
    
try '<unfinished &<tags> (2)' \
'<foo [bar](foo)  &<s>hi</s>' \
'<p><foo [bar](foo)  &<s>hi</s></p>'

try 'paragraph <br/> oddity' 'EOF  ' '<p>EOF</p>'
    
summary $0
exit $rc
